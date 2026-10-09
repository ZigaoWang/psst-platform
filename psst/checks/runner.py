"""Running the tool checks: on a stored revision (the system worker, authoritative) and on a result a writer is
about to submit (the CLI, so problems are fixed before anything is stored). Both load snapshots and context the
same way and run the same checks."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from psst import rules

from .tools import Claim, Context, Evidence, Result, Snapshot, Stop, check

Connection = psycopg.Connection[dict[str, Any]]


def snapshots_for(conn: Connection, ids: list[str]) -> dict[str, Snapshot]:
    return {r["id"]: Snapshot(r["id"], r["source_id"], r["url"], r["kind"], r["text"]) for r in conn.execute("""
        SELECT n.id, n.source_id, s.url, s.kind, n.text FROM psst.snapshots n JOIN psst.sources s ON s.id = n.source_id
        WHERE n.id = ANY(%s)""", (ids,))}


def context_for(conn: Connection, item_type: str, place_id: str | None, body: dict[str, Any],
                translation_of: str | None, item_id: str | None = None) -> Context:
    context = Context()
    if place_id and item_type == "story":
        context.siblings = [r["told"] for r in conn.execute("""
            SELECT concat_ws(' ', r.body ->> 'headline', r.body ->> 'short') AS told
            FROM psst.items i JOIN psst.revisions r ON r.id = i.current_revision
            WHERE i.place_id = %(place)s AND i.type = 'story' AND i.state <> 'retired'
              AND (%(item)s::text IS NULL OR i.created_at < (SELECT created_at FROM psst.items WHERE id = %(item)s))
            ORDER BY i.created_at""", {"place": place_id, "item": item_id})]  # an earlier story keeps its angle
    if place_id:
        context.names = [r["name"] for r in conn.execute("""
            SELECT name FROM psst.place_names WHERE place_id = %(p)s
            UNION SELECT a.name FROM psst.places p JOIN psst.areas a
                ON a.id IN (p.city_id, p.district_id, p.neighborhood_id, p.region_id) WHERE p.id = %(p)s""",
                                                             {"p": place_id})]
    tags = [t for t in body.get("tags") or [] if isinstance(t, str)]
    context.tags = {r["id"] for r in conn.execute("SELECT id FROM psst.tags WHERE id = ANY(%s)", (tags,))}
    if item_type == "trail":
        stops = [s.get("place") for s in body.get("stops", []) if isinstance(s, dict)]
        context.stops = {r["id"]: Stop(r["lat"], r["lon"], r["published"]) for r in conn.execute("""
            SELECT p.id, ST_Y(p.geom) AS lat, ST_X(p.geom) AS lon,
                   EXISTS (SELECT 1 FROM psst.items i WHERE i.place_id = p.id AND i.type = 'story'
                           AND i.published_revision IS NOT NULL AND i.state <> 'retired') AS published
            FROM psst.places p WHERE p.id = ANY(%s) AND p.state = 'active'""", (stops,))}
    if item_type == "photo":
        context.photo_pairs = {r["id"] for r in conn.execute("""
            SELECT i.id FROM psst.items i JOIN psst.revisions r ON r.id = i.current_revision
            WHERE i.place_id = %s AND i.type = 'photo' AND r.body ->> 'kind' = 'photo' AND i.state <> 'retired'""",
                                                             (place_id,))}
    if item_type == "translation" and translation_of:
        source = conn.execute("""
            SELECT i.type, r.body FROM psst.revisions r JOIN psst.items i ON i.id = r.item_id WHERE r.id = %s""",
                              (translation_of,)).fetchone()
        if source:
            context.source_type, context.source_body = source["type"], source["body"]
    return context


def claims_from_result(raw: list[dict[str, Any]]) -> list[Claim]:
    """Claims as a writer submits them, numbered in order."""
    return [Claim(n, str(c.get("text", "")), str(c.get("kind", "")), list(c.get("values") or []),
                  [Evidence(str(e.get("snapshot", "")), str(e.get("quote", ""))) for e in c.get("evidence") or []],
                  str(c.get("role", "fact")))
            for n, c in enumerate(raw, 1)]


def preflight(conn: Connection, item_type: str, place_id: str | None, result: dict[str, Any],
              translation_of: str | None = None) -> Result:
    """The tool checks on a result before it is submitted."""
    body = result.get("body") or {}
    claims = claims_from_result(result.get("claims") or [])
    snapshots = snapshots_for(conn, sorted({e.snapshot for c in claims for e in c.evidence}))
    return check(item_type, body, claims, snapshots, context_for(conn, item_type, place_id, body, translation_of))


def load(conn: Connection, revision_id: str) -> tuple[str, dict[str, Any], list[Claim], dict[str, Snapshot], Context]:
    """Everything the tool checks need for one stored revision."""
    revision = conn.execute("""
        SELECT r.body, r.translation_of, i.id, i.type, i.place_id
        FROM psst.revisions r JOIN psst.items i ON i.id = r.item_id WHERE r.id = %s""", (revision_id,)).fetchone()
    if revision is None:
        raise LookupError(f"unknown revision {revision_id}")
    claims: dict[str, Claim] = {}
    for row in conn.execute("""
            SELECT c.id, c.n, c.text, c.kind, c."values", c.role, e.id AS evidence_id, e.snapshot_id, e.quote
            FROM psst.claims c JOIN psst.evidence e ON e.claim_id = c.id
            WHERE c.revision_id = %s ORDER BY c.n, e.id""", (revision_id,)):
        claim = claims.setdefault(row["id"], Claim(row["n"], row["text"], row["kind"], row["values"], [], row["role"]))
        claim.evidence.append(Evidence(row["snapshot_id"], row["quote"], row["evidence_id"]))
    snapshots = snapshots_for(conn, sorted({e.snapshot for c in claims.values() for e in c.evidence}))
    context = context_for(conn, revision["type"], revision["place_id"], revision["body"], revision["translation_of"],
                          revision["id"])
    return revision["type"], revision["body"], list(claims.values()), snapshots, context


def run(conn: Connection, system_token: str, revision_id: str, task_id: str | None = None) -> Result:
    """Check one stored revision and record the verdict, with where each quote was found."""
    item_type, body, claims, snapshots, context = load(conn, revision_id)
    rulebook = rules.load()
    result = check(item_type, body, claims, snapshots, context, rulebook)
    note = "every tool check passed" if result.ok else "; ".join(result.report.refusals[:20])
    details = {**result.report.as_dict(), "rulebook": rulebook.version}
    conn.execute("SELECT psst.record_tool_check(%s, %s, %s, %s, %s, %s, %s)",
                 (system_token, task_id, revision_id, result.ok, note, Jsonb(details), Jsonb(result.matches)))
    return result
