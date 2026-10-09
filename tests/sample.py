"""Small invented records for tests. Nothing here is real content: the city, place, source, and text are made up."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import psycopg

CITY_ID = 900001
RULEBOOK = "0123456789ab"
SNAPSHOT_TEXT = ("The Old Pump House on Mill Lane was built in 1871 by the engineer Ada Thorne. "
                 "It pumped water to the town until 1952, when it was turned into a library.")


def city(conn: psycopg.Connection[dict[str, Any]]) -> int:
    conn.execute("""
        INSERT INTO psst.areas (id, source, placetype, level, name, country_code, geom, area_km2, license)
        VALUES (%s, 'wof', 'locality', 'city', 'Testville', 'GB',
                ST_GeomFromText('POLYGON((-0.2 51.4, 0.1 51.4, 0.1 51.6, -0.2 51.6, -0.2 51.4))', 4326), 600, 'CC0')
        ON CONFLICT DO NOTHING""", (CITY_ID,))
    conn.execute("""
        INSERT INTO psst.cities (id, slug, name, country_code, research_order)
        VALUES (%s, 'testville', 'Testville', 'GB', 1) ON CONFLICT DO NOTHING""", (CITY_ID,))
    return CITY_ID


def place(conn: psycopg.Connection[dict[str, Any]], run_id: str, wikidata: str = "Q900001") -> str:
    city(conn)
    row = conn.execute("""
        INSERT INTO psst.places (id, kind, state, wikidata_id, geom, coord_source, coord_ref, h3_r7, country_code,
                                 city_id, created_by_run)
        VALUES (psst.new_id('pl'), 'building', 'active', %s, ST_SetSRID(ST_MakePoint(-0.05, 51.5), 4326), 'wikidata',
                %s, '87195da49ffffff', 'GB', %s, %s)
        RETURNING id""", (wikidata, wikidata, CITY_ID, run_id)).fetchone()
    assert row
    conn.execute("INSERT INTO psst.place_names (place_id, role, lang, name, source) VALUES (%s, 'display', 'en', %s, "
                 "'wikidata')", (row["id"], f"Old Pump House {wikidata}"))
    return str(row["id"])


def snapshot(conn: psycopg.Connection[dict[str, Any]], run_id: str, text: str = SNAPSHOT_TEXT,
             url: str = "https://records.example.org/pump-house", kind: str = "official_record") -> str:
    source = conn.execute("""
        INSERT INTO psst.sources (id, url, url_key, title, publisher, kind, language, created_by_run)
        VALUES (psst.new_id('so'), %s, %s, 'Pump House record', 'Testville Records Office', %s, 'en', %s)
        ON CONFLICT (url_key) DO UPDATE SET title = EXCLUDED.title RETURNING id""",
                          (url, url.removeprefix("https://"), kind, run_id)).fetchone()
    assert source
    row = conn.execute("""
        INSERT INTO psst.snapshots (id, source_id, http_status, via, read_url, content_hash, text, run_id)
        VALUES (psst.new_id('sn'), %s, 200, 'live', %s, %s, %s, %s) RETURNING id""",
                       (source["id"], url, hashlib.sha256(text.encode()).digest(), text, run_id)).fetchone()
    assert row
    return str(row["id"])


def story_body() -> dict[str, Any]:
    return {
        "category": "history", "veracity": "fact", "headline": "A pump house that became a library",
        "short": "The library on Mill Lane was built in 1871 to pump the town's water.",
        "long": "x" * 320, "look": "Stand across Mill Lane and look at the tall chimney above the reading room.",
        "tags": [],
    }


def claims(snapshot_id: str) -> list[dict[str, Any]]:
    return [
        {"text": "The pump house was built in 1871.", "kind": "date", "values": [{"value": "1871"}],
         "evidence": [{"snapshot": snapshot_id, "quote": "was built in 1871"}]},
        {"text": "It became a library in 1952.", "kind": "event", "values": [{"value": "1952"}],
         "evidence": [{"snapshot": snapshot_id, "quote": "until 1952, when it was turned into a library"}]},
    ]


def create_story(conn: psycopg.Connection[dict[str, Any]], run_id: str, place_id: str, snapshot_id: str,
                 item_id: str | None = None) -> str:
    row = conn.execute("""
        SELECT psst.create_revision(%s, NULL, %s, 'story', %s, NULL, NULL, NULL, 'en', %s, %s, %s, 'written')
            AS revision""", (run_id, item_id, place_id, json.dumps(story_body()), json.dumps(claims(snapshot_id)),
                             RULEBOOK)).fetchone()
    assert row
    return str(row["revision"])
