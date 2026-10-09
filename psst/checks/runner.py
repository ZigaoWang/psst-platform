"""Running the tool checks on a stored revision and recording the verdict (system role)."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from psst import rules

from .tools import Claim, Context, Evidence, Result, Snapshot, Stop, check

Connection = psycopg.Connection[dict[str, Any]]


def load(conn: Connection, revision_id: str) -> tuple[str, dict[str, Any], list[Claim], dict[str, Snapshot], Context]:
    """Everything the tool checks need for one revision."""
    revision = conn.execute("""
        SELECT r.body, r.translation_of, i.type, i.place_id, i.translates
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
    snapshot_ids = sorted({e.snapshot for c in claims.values() for e in c.evidence})
    snapshots = {r["id"]: Snapshot(r["id"], r["source_id"], r["url"], r["kind"], r["text"]) for r in conn.execute("""
        SELECT n.id, n.source_id, s.url, s.kind, n.text FROM psst.snapshots n JOIN psst.sources s ON s.id = n.source_id
        WHERE n.id = ANY(%s)""", (snapshot_ids,))}
    context = Context()
    if revision["place_id"]:
        context.names = [r["name"] for r in conn.execute("""
            SELECT name FROM psst.place_names WHERE place_id = %(p)s
            UNION SELECT a.name FROM psst.places p JOIN psst.areas a
                ON a.id IN (p.city_id, p.district_id, p.neighborhood_id, p.region_id) WHERE p.id = %(p)s""",
                                                             {"p": revision["place_id"]})]
    tags = revision["body"].get("tags") or []
    context.tags = {r["id"] for r in conn.execute("SELECT id FROM psst.tags WHERE id = ANY(%s)", (tags,))}
    if revision["type"] == "trail":
        stops = [s["place"] for s in revision["body"].get("stops", [])]
        context.stops = {r["id"]: Stop(r["lat"], r["lon"], r["published"]) for r in conn.execute("""
            SELECT p.id, ST_Y(p.geom) AS lat, ST_X(p.geom) AS lon,
                   EXISTS (SELECT 1 FROM psst.items i WHERE i.place_id = p.id AND i.type = 'story'
                           AND i.published_revision IS NOT NULL AND i.state <> 'retired') AS published
            FROM psst.places p WHERE p.id = ANY(%s) AND p.state = 'active'""", (stops,))}
    if revision["type"] == "photo":
        context.photo_pairs = {r["id"] for r in conn.execute("""
            SELECT i.id FROM psst.items i JOIN psst.revisions r ON r.id = i.current_revision
            WHERE i.place_id = %s AND i.type = 'photo' AND r.body ->> 'kind' = 'photo' AND i.state <> 'retired'""",
                                                             (revision["place_id"],))}
    if revision["type"] == "translation":
        source = conn.execute("""
            SELECT i.type, r.body FROM psst.revisions r JOIN psst.items i ON i.id = r.item_id WHERE r.id = %s""",
                              (revision["translation_of"],)).fetchone()
        if source:
            context.source_type, context.source_body = source["type"], source["body"]
    return revision["type"], revision["body"], list(claims.values()), snapshots, context


def run(conn: Connection, system_token: str, revision_id: str, task_id: str | None = None) -> Result:
    """Check one revision and record the verdict, with where each quote was found."""
    item_type, body, claims, snapshots, context = load(conn, revision_id)
    rulebook = rules.load()
    result = check(item_type, body, claims, snapshots, context, rulebook)
    note = "every tool check passed" if result.ok else "; ".join(result.report.refusals[:20])
    details = {**result.report.as_dict(), "rulebook": rulebook.version}
    conn.execute("SELECT psst.record_tool_check(%s, %s, %s, %s, %s, %s, %s)",
                 (system_token, task_id, revision_id, result.ok, note, Jsonb(details),
                  Jsonb(result.matches)))
    return result
