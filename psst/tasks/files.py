"""Task files: everything a worker needs for one task, in one JSON document, so nobody hunts through briefs.

A checker sees only what its check needs (design.md, section 7.3): the claim checks get claims and passages and
never the prose; the translation check gets the translation and the English claims and never the English text.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import psycopg

from psst import rules
from psst.core.text import find_quote

from . import prompts, results

Connection = psycopg.Connection[dict[str, Any]]
CONTEXT_CHARS = 500
FULL_SNAPSHOT_CHARS = 60_000

Lookup = Callable[[dict[str, Any]], Any]


@dataclass
class Lookups:
    """What a task file needs from the network, passed in by the command line and left out in tests: the place's
    encyclopedia lead, the key facts its Wikidata item gives, photo candidates with local previews to look at, and
    a local copy of a photo under check."""
    lead: Lookup | None = None
    key_facts: Lookup | None = None
    photo_candidates: Lookup | None = None
    photo_file: Lookup | None = None


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


def build(conn: Connection, task: dict[str, Any], lookups: Lookups | None = None) -> dict[str, Any]:
    """The task file for a leased task."""
    lookups = lookups or Lookups()
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
                 # Who each claim comes from, so "the listing says" can be traced, but never the passages.
                 "claims": [{**{k: c[k] for k in ("claim", "n", "text", "values", "role")},
                             "sources": sorted({f"{p['source']['publisher']} ({p['source']['kind']})"
                                                for p in c["passages"]})}
                            for c in claims_with_passages(conn, task["revision_id"])],
                 "questions": rulebook.type(str(item_type))["item_questions"],
                 "other_stories": other_items(conn, task["place_id"], task["item_id"]),
                 "encyclopedia_lead": lookups.lead(data["place"]) if lookups.lead and data["place"] else None}
        if kind == "check_photo":
            data["photo_file"] = lookups.photo_file(revision["body"]) if lookups.photo_file else None
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
        if kind == "write_guide":
            data |= guide_references(lookups, data["place"])
    elif kind == "research_cell":
        data = research_brief(conn, task["input"]["cell"])
    elif kind == "find_photos":
        existing = [{"item": r["id"], "kind": r["body"]["kind"], "alt": r["body"]["alt"], "state": r["state"]}
                    for r in conn.execute("""
            SELECT i.id, i.state, r.body FROM psst.items i JOIN psst.revisions r ON r.id = i.current_revision
            WHERE i.place_id = %s AND i.type = 'photo' AND i.state <> 'retired'""", (task["place_id"],))]
        data |= {"existing_photos": existing, "stories": other_items(conn, task["place_id"], None),
                 "candidates": lookups.photo_candidates({**(data["place"] or {}), "task": task["id"]})
                 if lookups.photo_candidates and data["place"] else [],
                 "rules": rulebook.type("photo")}
    elif kind == "revise":
        assert revision
        data |= {"type": item_type, "body": revision["body"],
                 "claims": claims_with_passages(conn, task["revision_id"]),
                 "problems": task["input"].get("problems") or [],
                 "check_notes": earlier_verdicts(conn, task["revision_id"]),
                 "other_stories": other_items(conn, task["place_id"], task["item_id"]),
                 "rules": rulebook.type(str(item_type)) if item_type != "translation" else rulebook.type("translation")}
        if item_type == "guide":
            data |= guide_references(lookups, data["place"])
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


def guide_references(lookups: Lookups, place: dict[str, Any] | None) -> dict[str, Any]:
    """The place's Wikidata lines and encyclopedia lead, for writing a guide and for revising one."""
    if not place:
        return {}
    return {"wikidata": lookups.key_facts(place) if lookups.key_facts else None,
            "encyclopedia_lead": lookups.lead(place) if lookups.lead else None}


def research_brief(conn: Connection, cell: str) -> dict[str, Any]:
    """Everything a researcher needs for one cell: where it is, its leads (best known first), and the places
    already in it and around it, so nothing is added twice."""
    import h3

    from psst.places import cells

    spec = rules.load().places
    south, west, north, east = cells.bounds(cell)
    around = [cell] + [c for c in h3.grid_disk(cell, 1) if c != cell]
    leads = [dict(r) | {"well_known": (r["fame"] or 0) >= spec["well_known_sitelinks"]} for r in conn.execute("""
        SELECT id AS lead, name, origin, wikidata_id AS wikidata, osm_ref AS osm, url, what, fame, status
        FROM psst.leads WHERE cell = %s AND status IN ('open', 'later')
        ORDER BY fame DESC NULLS LAST, name LIMIT %s""", (cell, spec["max_leads_per_pass"]))]
    waiting = conn.execute("SELECT count(*) AS n FROM psst.leads WHERE cell = %s AND status IN ('open', 'later')",
                           (cell,)).fetchone()
    places = [dict(r) for r in conn.execute("""
        SELECT p.id, p.kind, p.h3_r7 = %s AS in_cell, p.wikidata_id AS wikidata, p.osm_ref AS osm,
               (SELECT name FROM psst.place_names n WHERE n.place_id = p.id AND n.role = 'display') AS name,
               coalesce((SELECT jsonb_agg(r.body ->> 'headline') FROM psst.items i
                         JOIN psst.revisions r ON r.id = i.current_revision
                         WHERE i.place_id = p.id AND i.type = 'story' AND i.state <> 'retired'), '[]') AS stories
        FROM psst.places p WHERE p.h3_r7 = ANY(%s) AND p.state IN ('active', 'pending')
        ORDER BY p.h3_r7 = %s DESC, p.id""", (cell, around, cell))]
    neighborhoods = [r["name"] for r in conn.execute("""
        SELECT DISTINCT a.name FROM psst.areas a JOIN psst.research_cells c ON c.cell = %s
        WHERE a.level = 'neighborhood' AND ST_Intersects(a.geom, c.geom) ORDER BY a.name""", (cell,))]
    return {"cell": cell, "bounds": {"south": south, "west": west, "north": north, "east": east},
            "neighborhoods": neighborhoods, "leads": leads,
            "leads_after_this_pass": max(0, int(waiting["n"] if waiting else 0) - len(leads)),
            "places_nearby": places,
            "rules": {"kinds": spec["kinds"], "sizes": spec["sizes"],
                      "categories": rules.load().type("story")["categories"],
                      "min_ordinary_share": spec["min_ordinary_share"],
                      "well_known_sitelinks": spec["well_known_sitelinks"]}}


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
