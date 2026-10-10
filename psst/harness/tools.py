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

from psst.checks import runner
from psst.cli import fetching
from psst.core import http
from psst.evidence import fetch as reading
from psst.places import lookup

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
    "lookup_wikidata": {
        "description": "A Wikidata item's labels, description, coordinates, and number of encyclopedia articles.",
        "parameters": {"type": "object", "required": ["qid"], "properties": {"qid": _string("Q...")}}},
    "find_osm": {
        "description": "Wikidata items and OpenStreetMap elements with a name near a point.",
        "parameters": {"type": "object", "required": ["name", "lat", "lon"],
                       "properties": {"name": _string("the name on the ground"), "lat": {"type": "number"},
                                      "lon": {"type": "number"}, "language": _string("en, zh, ...")}}},
    "nearby_places": {
        "description": "Places already in the platform near a point, with their stories' headlines, so nothing is "
                       "added or told twice.",
        "parameters": {"type": "object", "required": ["lat", "lon"],
                       "properties": {"lat": {"type": "number"}, "lon": {"type": "number"},
                                      "meters": {"type": "integer"}}}},
    "check_draft": {
        "description": "Run the tool checks on a draft story or guide before submitting it. Returns the problems.",
        "parameters": {"type": "object", "required": ["type", "draft"],
                       "properties": {"type": {"enum": ["story", "guide"]},
                                      "draft": {"type": "object", "description": "{body, claims}"}}}},
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


def lookup_wikidata(ctx: Context, qid: str) -> dict[str, Any]:
    entity = http.wikidata_entities([qid], props="labels|descriptions|claims|sitelinks").get(qid)
    if not entity:
        return {"error": f"{qid} isn't on Wikidata"}
    coords = [c["mainsnak"].get("datavalue", {}).get("value") for c in entity.get("claims", {}).get("P625", [])]
    return {"qid": qid, "labels": {k: v["value"] for k, v in entity.get("labels", {}).items() if k in ("en", "zh")},
            "description": entity.get("descriptions", {}).get("en", {}).get("value"),
            "coordinates": [{"lat": c["latitude"], "lon": c["longitude"], "precision": c.get("precision")}
                            for c in coords if c],
            "articles": len(entity.get("sitelinks", {}))}


def find_osm(ctx: Context, name: str, lat: float, lon: float, language: str = "en") -> dict[str, Any]:
    return {"found": lookup.find(name, lat, lon, 1500, language)}


def nearby_places(ctx: Context, lat: float, lon: float, meters: int = 300) -> dict[str, Any]:
    rows = ctx.conn.execute("""
        SELECT p.id, (SELECT name FROM psst.place_names WHERE place_id = p.id AND role = 'display') AS name,
               p.wikidata_id AS wikidata, p.osm_ref AS osm,
               round(ST_Distance(p.geom::geography, ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography))
                   AS meters,
               coalesce((SELECT jsonb_agg(r.body ->> 'headline') FROM psst.items i
                         JOIN psst.revisions r ON r.id = i.current_revision
                         WHERE i.place_id = p.id AND i.type = 'story' AND i.state <> 'retired'), '[]') AS stories
        FROM psst.places p WHERE p.state IN ('pending', 'active')
          AND ST_DWithin(p.geom::geography, ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography, %(m)s)
        ORDER BY 5 LIMIT 40""", {"lat": lat, "lon": lon, "m": min(int(meters), 2000)}).fetchall()
    return {"places": [dict(r) for r in rows]}


def check_draft(ctx: Context, type: str, draft: dict[str, Any]) -> dict[str, Any]:
    check = runner.preflight(ctx.conn, type, ctx.place_id, draft, item_id=ctx.item_id)
    return {"problems": check.report.refusals, "warnings": check.report.flags}


IMPLEMENTATIONS: dict[str, Callable[..., dict[str, Any]]] = {
    "fetch_source": fetch_source, "search_snapshot": search_snapshot, "lookup_wikidata": lookup_wikidata,
    "find_osm": find_osm, "nearby_places": nearby_places, "check_draft": check_draft,
}


def call(ctx: Context, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Run one tool; a failure comes back as an error for the model to read, never as an exception."""
    name = name.rpartition(":")[2].rpartition(".")[2]  # some models prefix a namespace ("psst:check_draft")
    if name not in IMPLEMENTATIONS:
        return {"error": f"no tool {name}"}
    try:
        return IMPLEMENTATIONS[name](ctx, **arguments)
    except TypeError as error:
        return {"error": f"bad arguments for {name}: {error}"}
    except (ConnectionError, LookupError, ValueError, psycopg.Error) as error:
        return {"error": str(error)[:500]}
