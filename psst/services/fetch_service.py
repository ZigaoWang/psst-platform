"""The fetch service: the only writer of snapshots (decisions.md, 2).

It listens on the server's loopback interface. A worker's CLI reaches it through the SSH tunnel and asks it to
read a page for the worker's run; the service reads the page itself, stores the snapshot under its own system run,
and returns the text. A worker can therefore never store text a source didn't say.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import psycopg

from psst import rules
from psst.evidence import fetch, urls

PORT = 8471
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
        self.slots = threading.BoundedSemaphore(4)  # pages read at once, so no site sees a burst from us

    def read(self, request: dict[str, Any]) -> dict[str, Any]:
        url = str(request.get("url") or "").strip()
        token = str(request.get("token") or "")
        address = urls.original(url)
        problem = urls.problem(address)
        if problem:
            raise RequestError(problem)
        kinds = rules.load().sources["kinds"]
        kind = "reference" if urls.is_reference_host(address) else str(request.get("kind") or "")
        if kind not in kinds:
            raise RequestError(f"kind must be one of {', '.join(kinds)}")
        title = str(request.get("title") or "").strip()
        publisher = str(request.get("publisher") or "").strip()
        language = str(request.get("language") or "").strip()
        if not (title and publisher and language):
            raise RequestError("a source needs its title, publisher, and language")
        with self.slots:
            page = self.reader.read(url, archive=bool(request.get("archive")))
        if not page.ok:
            raise RequestError(page.note or f"the page answered {page.status}")
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM psst.record_snapshot(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (self.system_token, token, address, urls.key(address), title, publisher, kind, language, page.status,
                 page.via, page.url, page.title, page.text)).fetchone()
            conn.commit()
        assert row
        return {"source": row["source_id"], "kind": row["source_kind"], "snapshot": row["snapshot_id"],
                "new": row["is_new"], "url": address, "read_url": page.url, "via": page.via,
                "archived_at": page.archived_at, "title": page.title, "note": page.note, "text": page.text,
                "links": page.links[:500]}


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
