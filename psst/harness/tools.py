"""The typed tools a model may call inside a judgment step (decision 28). Each is a thin wrapper over what the
command line already does, so the harness and a worker session share one implementation: sources are read only
through the fetch service, which snapshots them; drafts are checked by the same tool checks as a submission."""

from __future__ import annotations

import hashlib
import json
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import psycopg

from psst.cli import fetching
from psst.evidence import fetch as reading

Connection = psycopg.Connection[dict[str, Any]]

TEXT_LIMIT = 12000  # characters of a page shown at once; search_snapshot finds the rest
LINK_LIMIT = 60


@dataclass
class Context:
    conn: Connection
    token: str
    place_id: str | None = None
    item_id: str | None = None
    read: set[str] = field(default_factory=set)   # snapshots fetched or searched for this item


def _string(description: str) -> dict[str, Any]:
    return {"type": "string", "description": description}


DEFINITIONS: dict[str, dict[str, Any]] = {
    "fetch_source": {
        "description": "Read a web page or PDF and save a snapshot of it. Quote only from snapshots. Returns the "
                       "snapshot id, the text (or the passages around `find`), and the page's links to other sites. "
                       "Never guess an address: follow a link from a page you read, such as an article's references.",
        "parameters": {"type": "object", "required": ["url", "title", "publisher", "kind", "language"],
                       "properties": {"url": _string("the full https address"), "title": _string("the page title"),
                                      "publisher": _string("who publishes it"),
                                      "kind": {"enum": ["official_record", "archive", "operator", "scholarly",
                                                        "press", "reference", "community"]},
                                      "language": _string("en, zh, ..."),
                                      "find": _string("optional words to show the passages around")}}},
    "search_snapshot": {
        "description": "Find the passages in a saved snapshot that contain some words.",
        "parameters": {"type": "object", "required": ["snapshot", "words"],
                       "properties": {"snapshot": _string("a snapshot id, sn_..."),
                                      "words": _string("words to find")}}},
}
VERSION = hashlib.sha256(json.dumps(DEFINITIONS, sort_keys=True).encode()).hexdigest()[:12]


def definitions(names: list[str]) -> list[dict[str, Any]]:
    return [{"name": n, **DEFINITIONS[n]} for n in names]


def fetch_source(ctx: Context, url: str, title: str, publisher: str, kind: str, language: str,
                 find: str | None = None, full: bool = False) -> dict[str, Any]:
    result = fetching.request({"token": ctx.token, "url": url, "title": title, "publisher": publisher, "kind": kind,
                               "language": language, "archive": False})
    text = result["text"]
    shown = text if full else reading.passages(text, find, TEXT_LIMIT) if find else text[:TEXT_LIMIT]
    # The page's own links to other sites: an article's references are the way to the records it rests on, so the
    # writer follows real citations instead of guessing addresses.
    links = [{"text": label, "url": href} for label, href in result.get("links") or []
             if href.startswith("https://") and urllib.parse.urlsplit(href).netloc != urllib.parse.urlsplit(url).netloc
             and "wikipedia.org" not in href and "wikimedia.org" not in href][:LINK_LIMIT]
    ctx.read.add(result["snapshot"])
    return {"snapshot": result["snapshot"], "kind": result["kind"], "url": result["url"],
            "characters": len(text), "text": shown, "links": links}


def search_snapshot(ctx: Context, snapshot: str, words: str) -> dict[str, Any]:
    row = ctx.conn.execute("SELECT text FROM psst.snapshots WHERE id = %s", (snapshot,)).fetchone()
    if row is None:
        return {"error": f"no snapshot {snapshot}"}
    ctx.read.add(snapshot)
    return {"snapshot": snapshot, "passages": reading.passages(row["text"], words, TEXT_LIMIT)}


IMPLEMENTATIONS: dict[str, Callable[..., dict[str, Any]]] = {
    "fetch_source": fetch_source, "search_snapshot": search_snapshot,
}


def call(ctx: Context, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Run one tool; a failure comes back as an error for the model to read, never as an exception."""
    name = name.rpartition(":")[2].rpartition(".")[2]  # some models prefix a namespace ("psst:search_snapshot")
    if name not in IMPLEMENTATIONS:
        return {"error": f"no tool {name}"}
    try:
        return IMPLEMENTATIONS[name](ctx, **arguments)
    except TypeError as error:
        return {"error": f"bad arguments for {name}: {error}"}
    except (OSError, LookupError, ValueError, psycopg.Error) as error:  # a timeout included
        return {"error": str(error)[:500]}
