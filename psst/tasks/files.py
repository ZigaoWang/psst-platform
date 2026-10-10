"""Task files: everything a worker needs for one task, in one JSON document, so nobody hunts through briefs.

A checker sees only what its check needs (design.md, section 7.3): the claim checks get claims and passages and
never the prose; the translation check gets the translation and the English claims and never the English text.
"""

from __future__ import annotations

import json
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
EXCERPT_CHARS = 3_000  # around each quoted passage, when a page is too long to send whole

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
    """Every snapshot the revision cites. A page longer than FULL_SNAPSHOT_CHARS comes as its opening and a wide
    window around each passage the revision quotes from it, so every quote can still be read in place."""
    rows = conn.execute("""
        SELECT n.id, s.title, s.publisher, s.kind, s.url, n.text,
               array_agg(e.quote ORDER BY e.id) AS quotes, array_agg(e.quote_start ORDER BY e.id) AS starts,
               array_agg(e.quote_end ORDER BY e.id) AS ends
        FROM psst.claims c JOIN psst.evidence e ON e.claim_id = c.id JOIN psst.snapshots n ON n.id = e.snapshot_id
        JOIN psst.sources s ON s.id = n.source_id WHERE c.revision_id = %s
        GROUP BY n.id, s.title, s.publisher, s.kind, s.url, n.text ORDER BY n.id""", (revision_id,))
    snapshots = []
    for r in rows:
        text, excerpted = r["text"], len(r["text"]) > FULL_SNAPSHOT_CHARS
        if excerpted:
            spans = []
            for quote, start, end in zip(r["quotes"], r["starts"], r["ends"], strict=True):
                found = (start, end) if start is not None else find_quote(text, quote)
                if found:
                    spans.append(found)
            text = excerpt(text, spans)
        snapshots.append({"snapshot": r["id"], "title": r["title"], "publisher": r["publisher"], "kind": r["kind"],
                          "url": r["url"], "text": text, "excerpted": excerpted})
    return snapshots


def excerpt(text: str, quoted: list[tuple[int, int]], window: int = EXCERPT_CHARS) -> str:
    """The opening of a long text and a window around each quoted span, overlapping windows merged."""
    spans = sorted([(0, window)] + [(max(0, start - window), min(len(text), end + window)) for start, end in quoted])
    merged: list[list[int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return "\n[...]\n".join(text[start:end] for start, end in merged)


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

    if kind == "check_photo":
        assert revision
        data |= {"type": item_type, "body": revision["body"],
                 "claims": [{k: c[k] for k in ("claim", "n", "text", "values", "role")}
                            for c in claims_with_passages(conn, task["revision_id"])],
                 "questions": rulebook.type("photo")["item_questions"],
                 "other_stories": other_items(conn, task["place_id"], task["item_id"]),
                 "photo_file": lookups.photo_file(revision["body"]) if lookups.photo_file else None}
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
    elif kind == "write_trail":
        item_type = "trail"
        data |= {"brief": task["input"], "rules": rulebook.type("trail")}
    elif kind == "research_cell":
        data = research_brief(conn, task["input"]["cell"])
        data["rules"] |= {"story": rulebook.type("story"), "guide": rulebook.type("guide")}
        data["reference_stories"] = style_references(conn, task["city_id"])
        data["marked_examples"] = golden_examples(conn)
    elif kind == "calibrate":
        fold = int(task["input"]["fold"])
        golden = [dict(r) for r in conn.execute("""
            SELECT id, place, headline, short, long, look, sources, claims, mark, tier, reason,
                   psst.golden_fold(id) = %s AS blind
            FROM psst.golden_stories ORDER BY md5(id)""", (fold,))]
        data = {"items": [{k: g[k] for k in ("id", "place", "headline", "short", "long", "look", "sources", "claims")}
                          for g in golden if g["blind"]],
                "marked_examples": [{k: g[k] for k in ("place", "headline", "short", "long", "look", "sources",
                                                       "mark", "tier", "reason")} for g in golden if not g["blind"]],
                "reference_stories": style_references(conn, task["city_id"]),
                "rules": {"story": rulebook.type("story"), "guide": rulebook.type("guide")},
                "calibration": "Mark each story good, weak, or bad as you would in a review, from its text and "
                               "its claims (what the sources confirm). A good story gets its tier, and its fix when "
                               "it needs one. Return {'marks': [{'golden': <id>, 'mark': ..., 'tier': ..., "
                               "'fix': ..., 'reason': ...}], 'notes': ...}."}
    elif kind == "review":
        data = {"items": [review_item(conn, lookups, revision_id)
                          for revision_id in task["input"]["revisions"] if being_checked(conn, revision_id)],
                "marked_examples": golden_examples(conn),
                "reference_stories": style_references(conn, task["city_id"]),
                "rules": {"story": rulebook.type("story"), "guide": rulebook.type("guide")}}
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

    bar = golden_bar(conn) if kind in BAR_TASKS else None
    if bar:
        data["golden_bar"] = bar["body"]
    prompt = prompts.load("review" if kind == "calibrate" else kind)  # calibration measures the review prompt
    return {
        "task": task["id"], "type": kind, "revision": task["revision_id"], "leased_until": str(task["leased_until"]),
        "prompt": prompt.text, "prompt_version": prompt.version, "rulebook": rulebook.version,
        "bar_version": bar["version"] if bar else None,
        "data": data, "result_schema": results.schema(kind, item_type),
    }


BAR_TASKS = {"research_cell", "review", "calibrate", "revise", "write_trail"}


def golden_bar(conn: Connection) -> dict[str, Any] | None:
    """The current golden bar: worked examples of good and weak writing, kept in the database (decision 25)."""
    row = conn.execute(
        "SELECT version, body FROM psst.current_guidance('golden_bar') WHERE version IS NOT NULL").fetchone()
    return dict(row) if row else None


def being_checked(conn: Connection, revision_id: str) -> bool:
    return conn.execute("SELECT 1 FROM psst.items WHERE current_revision = %s AND state = 'checking'",
                        (revision_id,)).fetchone() is not None


def review_item(conn: Connection, lookups: Lookups, revision_id: str) -> dict[str, Any]:
    """One story or guide as the reviewer sees it: the prose, each claim beside its passages, and what the reader
    may already know about the place."""
    revision = revision_of(conn, revision_id)
    item = conn.execute("SELECT id, place_id FROM psst.items WHERE current_revision = %s", (revision_id,)).fetchone()
    assert item
    place = place_summary(conn, item["place_id"])
    claims = claims_with_passages(conn, revision_id)
    return {"revision": revision_id, "type": revision["type"], "place": place, "body": revision["body"],
            "claims": claims, "quote_repairs": quote_repairs(conn, item["place_id"], claims),
            "other_stories": other_items(conn, item["place_id"], item["id"]),
            "encyclopedia_lead": lookups.lead(place) if lookups.lead and place else None}


def quote_repairs(conn: Connection, place_id: str | None, claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Passages the harness put in place of a writer's near quote (decision 30): judge each claim against the
    passage, never against what the writer typed."""
    if not place_id:
        return []
    quoted = json.dumps(claims, ensure_ascii=False, default=str)
    return [dict(r) for r in conn.execute("""
        SELECT snapshot_id AS snapshot, written, exact, similarity FROM psst.quote_repairs
        WHERE place_id = %s ORDER BY id""", (place_id,)) if r["exact"] in quoted]


def golden_examples(conn: Connection) -> list[dict[str, Any]]:
    """The editor's marked stories with the mark and the reason: what good, weak, and bad mean here."""
    return [dict(r) for r in conn.execute("""
        SELECT place, headline, short, long, look, sources, mark, tier, reason FROM psst.golden_stories
        ORDER BY created_at, id""")]


def style_references(conn: Connection, city_id: int | None) -> list[dict[str, Any]]:
    """The stories an editor chose as the standard for voice and surprise, the city's own first."""
    return [dict(r) for r in conn.execute("""
        SELECT place, headline, short, long, look, why FROM psst.style_references
        ORDER BY city_id IS NOT DISTINCT FROM %s DESC, created_at, id""", (city_id,))]


def guide_references(lookups: Lookups, place: dict[str, Any] | None) -> dict[str, Any]:
    """The place's Wikidata lines and encyclopedia lead, for writing a guide and for revising one."""
    if not place:
        return {}
    return {"wikidata": lookups.key_facts(place) if lookups.key_facts else None,
            "encyclopedia_lead": lookups.lead(place) if lookups.lead else None}


def research_brief(conn: Connection, cell: str) -> dict[str, Any]:
    """Everything a researcher needs for one cell: where it is, its leads (the previous app's places first, then the
    best known), and the places already in it and around it, so nothing is added twice."""
    import h3

    from psst.places import cells

    spec = rules.load().places
    south, west, north, east = cells.bounds(cell)
    around = [cell] + [c for c in h3.grid_disk(cell, 1) if c != cell]
    leads = [dict(r) | {"well_known": (r["fame"] or 0) >= spec["well_known_sitelinks"]} for r in conn.execute("""
        SELECT id AS lead, name, origin, wikidata_id AS wikidata, osm_ref AS osm, url, what, fame, status,
               place_id AS existing
        FROM psst.leads WHERE cell = %s AND status IN ('open', 'later')
        ORDER BY status = 'later', origin <> 'legacy', fame DESC NULLS LAST, name LIMIT %s""",
        (cell, spec["max_leads_per_pass"]))]  # places the previous app had come first, then the best known
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
