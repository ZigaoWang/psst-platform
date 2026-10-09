"""Task files: everything a worker needs for one task, in one JSON document, so nobody hunts through briefs.

A checker sees only what its check needs (design.md, section 7.3): the claim checks get claims and passages and
never the prose; the translation check gets the translation and the English claims and never the English text.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import psycopg

from psst import rules
from psst.core.text import find_quote

from . import prompts, results

Connection = psycopg.Connection[dict[str, Any]]
CONTEXT_CHARS = 500
FULL_SNAPSHOT_CHARS = 60_000

# What a writer, checker, or auditor is told about the place: who and where, never the stories' verdicts.
LeadFinder = Callable[[dict[str, Any]], dict[str, Any] | None]


def place_summary(conn: Connection, place_id: str | None) -> dict[str, Any] | None:
    if not place_id:
        return None
    row = conn.execute("""
        SELECT p.id, p.kind, p.size, p.state, p.wikidata_id, p.osm_ref, ST_Y(p.geom) AS lat, ST_X(p.geom) AS lon,
               (SELECT name FROM psst.place_names WHERE place_id = p.id AND role = 'display') AS name,
               (SELECT jsonb_build_object('lang', lang, 'name', name) FROM psst.place_names
                WHERE place_id = p.id AND role = 'local') AS local_name,
               (SELECT name FROM psst.areas WHERE id = p.neighborhood_id) AS neighborhood,
               (SELECT name FROM psst.areas WHERE id = p.district_id) AS district,
               (SELECT name FROM psst.areas WHERE id = coalesce(p.city_id, p.region_id)) AS city
        FROM psst.places p WHERE p.id = %s""", (place_id,)).fetchone()
    return dict(row) if row else None


def revision_of(conn: Connection, revision_id: str) -> dict[str, Any]:
    row = conn.execute("""
        SELECT r.id, r.number, r.body, r.translation_of, i.id AS item, i.type, i.place_id, i.language
        FROM psst.revisions r JOIN psst.items i ON i.id = r.item_id WHERE r.id = %s""", (revision_id,)).fetchone()
    if row is None:
        raise LookupError(f"unknown revision {revision_id}")
    return dict(row)


def claims_with_passages(conn: Connection, revision_id: str, only: list[str] | None = None,
                         window: int = CONTEXT_CHARS) -> list[dict[str, Any]]:
    """Each claim with its passages and the text around each passage, so a checker can see what a quote is
    about (a replica or the original, a closing year or a building year)."""
    claims: dict[str, dict[str, Any]] = {}
    for row in conn.execute("""
            SELECT c.id, c.n, c.text, c.kind, c."values", c.role, e.quote, e.quote_start, e.quote_end, n.text AS page,
                   s.title, s.publisher, s.kind AS source_kind, s.url
            FROM psst.claims c JOIN psst.evidence e ON e.claim_id = c.id
            JOIN psst.snapshots n ON n.id = e.snapshot_id JOIN psst.sources s ON s.id = n.source_id
            WHERE c.revision_id = %s AND (%s::text[] IS NULL OR c.id = ANY(%s))
            ORDER BY c.n, e.id""", (revision_id, only, only)):
        claim = claims.setdefault(row["id"], {"claim": row["id"], "n": row["n"], "text": row["text"],
                                              "kind": row["kind"], "values": row["values"], "role": row["role"],
                                              "passages": []})
        start, end = row["quote_start"], row["quote_end"]
        if start is None:
            span = find_quote(row["page"], row["quote"])
            start, end = span if span else (0, 0)
        claim["passages"].append({
            "source": {"title": row["title"], "publisher": row["publisher"], "kind": row["source_kind"],
                       "url": row["url"]},
            "quote": row["quote"],
            "before": row["page"][max(0, start - window):start],
            "after": row["page"][end:end + window],
        })
    return list(claims.values())


def full_snapshots(conn: Connection, revision_id: str) -> list[dict[str, Any]]:
    return [{"snapshot": r["id"], "title": r["title"], "publisher": r["publisher"], "kind": r["kind"],
             "url": r["url"], "text": r["text"][:FULL_SNAPSHOT_CHARS]} for r in conn.execute("""
        SELECT DISTINCT n.id, s.title, s.publisher, s.kind, s.url, n.text
        FROM psst.claims c JOIN psst.evidence e ON e.claim_id = c.id JOIN psst.snapshots n ON n.id = e.snapshot_id
        JOIN psst.sources s ON s.id = n.source_id WHERE c.revision_id = %s ORDER BY n.id""", (revision_id,))]


def other_items(conn: Connection, place_id: str | None, exclude_item: str | None) -> list[dict[str, Any]]:
    """The place's other stories, so a writer doesn't repeat them."""
    if not place_id:
        return []
    return [{"item": r["id"], "state": r["state"], "headline": r["body"].get("headline"),
             "short": r["body"].get("short")} for r in conn.execute("""
        SELECT i.id, i.state, r.body FROM psst.items i JOIN psst.revisions r ON r.id = i.current_revision
        WHERE i.place_id = %s AND i.type = 'story' AND i.state <> 'retired' AND i.id IS DISTINCT FROM %s
        ORDER BY i.position""", (place_id, exclude_item))]


def build(conn: Connection, task: dict[str, Any], lead: LeadFinder | None = None) -> dict[str, Any]:
    """The task file for a leased task."""
    rulebook = rules.load()
    kind = task["type"]
    data: dict[str, Any] = {"place": place_summary(conn, task["place_id"])}
    revision = revision_of(conn, task["revision_id"]) if task["revision_id"] else None
    item_type = revision["type"] if revision else None

    if kind in ("check_claims_a", "check_claims_b"):
        data = {"claims": claims_with_passages(conn, task["revision_id"])}
    elif kind == "escalate":
        assert revision
        data |= {"claims": claims_with_passages(conn, task["revision_id"], task["input"].get("claims") or None),
                 "snapshots": full_snapshots(conn, task["revision_id"]),
                 "earlier_verdicts": earlier_verdicts(conn, task["revision_id"])}
        if task["input"].get("item"):
            data |= {"type": item_type, "body": revision["body"],
                     "questions": rulebook.type(str(item_type)).get("item_questions", [])}
    elif kind in ("check_item", "check_photo"):
        assert revision
        data |= {"type": item_type, "body": revision["body"],
                 "claims": [{k: c[k] for k in ("claim", "n", "text", "values", "role")}
                            for c in claims_with_passages(conn, task["revision_id"])],
                 "questions": rulebook.type(str(item_type))["item_questions"],
                 "other_stories": other_items(conn, task["place_id"], task["item_id"]),
                 "encyclopedia_lead": lead(data["place"]) if lead and data["place"] else None}
    elif kind == "check_translation":
        assert revision
        source = revision_of(conn, revision["translation_of"])
        data |= {"language": revision["language"], "translation": revision["body"],
                 "english_claims": [{k: c[k] for k in ("n", "text", "values")}
                                    for c in claims_with_passages(conn, source["id"])],
                 "questions": rulebook.type("translation")["item_questions"]}
    elif kind == "audit":
        assert revision
        data |= {"type": item_type, "body": revision["body"],
                 "claims": claims_with_passages(conn, task["revision_id"]),
                 "snapshots": full_snapshots(conn, task["revision_id"]),
                 "questions": rulebook.type(str(item_type)).get("item_questions", [])}
    elif kind in ("write_story", "write_guide", "write_trail"):
        item_type = kind.removeprefix("write_")
        data |= {"brief": task["input"], "other_stories": other_items(conn, task["place_id"], None),
                 "rules": rulebook.type(item_type)}
    elif kind == "revise":
        assert revision
        data |= {"type": item_type, "body": revision["body"],
                 "claims": claims_with_passages(conn, task["revision_id"]),
                 "problems": task["input"].get("problems") or [],
                 "check_notes": earlier_verdicts(conn, task["revision_id"]),
                 "other_stories": other_items(conn, task["place_id"], task["item_id"]),
                 "rules": rulebook.type(str(item_type)) if item_type != "translation" else rulebook.type("translation")}
    elif kind == "translate":
        assert revision
        data |= {"type": item_type, "language": "zh-Hans", "body": revision["body"],
                 "claims": [{k: c[k] for k in ("n", "text", "values")}
                            for c in claims_with_passages(conn, task["revision_id"])],
                 "rules": rulebook.type("translation")}
    else:
        data |= {"input": task["input"]}

    prompt = prompts.load(kind)
    return {
        "task": task["id"], "type": kind, "revision": task["revision_id"], "leased_until": str(task["leased_until"]),
        "prompt": prompt.text, "prompt_version": prompt.version, "rulebook": rulebook.version,
        "data": data, "result_schema": results.schema(kind, item_type),
    }


def earlier_verdicts(conn: Connection, revision_id: str) -> list[dict[str, Any]]:
    """The verdicts given in the revision's current round of checks (for escalation and revision)."""
    return [dict(r) for r in conn.execute("""
        SELECT k.kind, c.n AS claim, k.verdict, k.note FROM psst.checks k
        JOIN psst.revisions r ON r.id = k.revision_id JOIN psst.items i ON i.id = r.item_id
        LEFT JOIN psst.claims c ON c.id = k.claim_id
        WHERE k.revision_id = %s AND k.created_at >= coalesce(i.checking_since, '-infinity') AND k.kind <> 'tool'
        ORDER BY k.id""", (revision_id,))] + [
        {"kind": "tool", "verdict": r["verdict"], "note": r["note"]} for r in conn.execute(
            "SELECT verdict, note FROM psst.checks WHERE revision_id = %s AND kind = 'tool' ORDER BY id DESC LIMIT 1",
            (revision_id,))]
