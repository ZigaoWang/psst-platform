"""The fetch service: the only writer of snapshots (decisions.md, 2).

It listens on the server's loopback interface. A worker's CLI reaches it through the SSH tunnel and asks it to
read a page for the worker's run; the service reads the page itself, stores the snapshot under its own system run,
and returns the text. A worker can therefore never store text a source didn't say.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.parse
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from psst import rules
from psst.evidence import fetch, urls, wikidata

PORT = 8471
CACHE_DAYS = 30
SITE_PAUSE_SECONDS = 0.3
SITE_READS = 3
MAX_REQUEST_BYTES = 16_384
log = logging.getLogger("psst.fetch")


class RequestError(ValueError):
    pass


class FetchService:
    def __init__(self, connect: Callable[[], psycopg.Connection[dict[str, Any]]], system_token: str,
                 reader: fetch.Reader | None = None) -> None:
        self.connect = connect
        self.system_token = system_token
        self.reader = reader or fetch.Reader()
        self.slots = threading.BoundedSemaphore(16)  # pages read at once, across all sites
        self.sites: dict[str, threading.BoundedSemaphore] = {}  # SITE_READS pages at a time from any one site
        self.sites_lock = threading.Lock()

    def read(self, request: dict[str, Any]) -> dict[str, Any]:
        url = str(request.get("url") or "").strip()
        token = str(request.get("token") or "")
        address = urls.original(url)
        problem = urls.problem(address)
        if problem:
            raise RequestError(problem)
        kinds = rules.load().sources["kinds"]
        kind = urls.host_kind(address) or str(request.get("kind") or "")
        if kind not in kinds:
            raise RequestError(f"kind must be one of {', '.join(kinds)}")
        title = str(request.get("title") or "").strip()
        publisher = str(request.get("publisher") or "").strip()
        language = str(request.get("language") or "").strip()
        if not (title and publisher and language):
            raise RequestError("a source needs its title, publisher, and language")
        recent = self.recent(urls.key(address))
        if recent:
            return recent
        with self.slots, self.site(address):
            page = self.read_page(url, bool(request.get("archive")))
            time.sleep(SITE_PAUSE_SECONDS)  # the polite pause belongs to the site, not to every read
        if not page.ok:
            raise RequestError(page.note or f"the page answered {page.status}")
        # A web page's own title and site name beat typed ones; PDFs and plain text keep what the worker typed.
        title, publisher = page.headline or title, page.site_name or publisher
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM psst.record_snapshot(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (self.system_token, token, address, urls.key(address), title, publisher, kind, language, page.status,
                 page.via, page.url, page.title, page.text)).fetchone()
            assert row
            conn.execute("SELECT psst.record_snapshot_links(%s, %s, %s)",
                         (self.system_token, row["snapshot_id"], Jsonb([list(link) for link in page.links[:500]])))
            conn.commit()
        assert row
        return {"source": row["source_id"], "kind": row["source_kind"], "snapshot": row["snapshot_id"],
                "new": row["is_new"], "url": address, "read_url": page.url, "via": page.via,
                "archived_at": page.archived_at, "title": page.title, "note": page.note, "text": page.text,
                "links": page.links[:500]}


    def site(self, address: str) -> threading.BoundedSemaphore:
        host = urllib.parse.urlsplit(address).netloc.lower()
        with self.sites_lock:
            return self.sites.setdefault(host, threading.BoundedSemaphore(SITE_READS))

    def recent(self, key: str) -> dict[str, Any] | None:
        """A page read in the last CACHE_DAYS is reused, not read again: the same snapshot, so every claim on it
        cites the same text."""
        with self.connect() as conn:
            row = conn.execute("""
                SELECT n.id AS snapshot, s.id AS source, s.kind, s.url, n.read_url, n.via, n.title, n.text, l.links
                FROM psst.snapshots n JOIN psst.sources s ON s.id = n.source_id
                LEFT JOIN psst.snapshot_links l ON l.snapshot_id = n.id
                WHERE s.url_key = %s AND n.fetched_at > now() - make_interval(days => %s) AND n.http_status < 400
                ORDER BY n.fetched_at DESC LIMIT 1""", (key, CACHE_DAYS)).fetchone()
        if row is None:
            return None
        return {"source": row["source"], "kind": row["kind"], "snapshot": row["snapshot"], "new": False,
                "url": row["url"], "read_url": row["read_url"], "via": row["via"], "archived_at": None,
                "title": row["title"], "note": "read earlier; the saved snapshot is reused", "text": row["text"],
                "links": [tuple(link) for link in row["links"] or []]}

    def read_page(self, url: str, archive: bool) -> fetch.Page:
        """A Wikidata item is saved as its key-fact lines (psst/evidence/wikidata.py); anything else as page text."""
        entity = wikidata.ENTITY_URL.match(url)
        if entity:
            try:
                item, values = wikidata.fetch(entity.group(1))
            except (LookupError, ConnectionError) as error:
                raise RequestError(str(error)) from None
            return fetch.Page(url, 200, wikidata.label(item) or entity.group(1),
                              wikidata.render(entity.group(1), item, values))
        return self.reader.read(url, archive=archive)


def handler(service: FetchService) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 (the standard library's name)
            if self.path != "/read":
                return self._send(404, {"error": "unknown path"})
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_REQUEST_BYTES:
                return self._send(413, {"error": "request too large"})
            try:
                request = json.loads(self.rfile.read(length) or b"{}")
                return self._send(200, service.read(request))
            except (RequestError, json.JSONDecodeError) as error:
                return self._send(400, {"error": str(error)})
            except psycopg.Error as error:
                message = error.diag.message_primary if error.diag else None
                return self._send(403 if error.sqlstate in ("28000", "42501") else 500,
                                  {"error": message or "database error"})

        def _send(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            log.info("%s %s", self.address_string(), format % args)

    return Handler


def serve(service: FetchService, host: str = "127.0.0.1", port: int = PORT) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), handler(service))
