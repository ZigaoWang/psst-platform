"""Importing reference data from the previous system's database (design.md, section 17): boundaries, the tag
vocabulary, demand counts, and the place list as a coverage checklist. No stories, guides, or photos are read.
The previous database is opened read-only and never changed.
"""

from __future__ import annotations

from typing import Any

import psycopg

Connection = psycopg.Connection[Any]

# (target table, target columns, query on the previous database)
COPIES = [
    ("areas", "id, source, placetype, level, name, country_code, parent_id, geom, area_km2, license, wikidata_id, "
              "osm_admin_level",
     "SELECT id, source, placetype, level, name, upper(country_code), parent_id, geom, area_km2, license, "
     "wikidata_id, osm_admin_level FROM psst.admin_areas WHERE btrim(name) <> ''"),
    ("area_names", "area_id, lang, name",
     "SELECT n.area_id, n.lang, n.name FROM psst.admin_area_names n JOIN psst.admin_areas a ON a.id = n.area_id "
     "WHERE btrim(a.name) <> '' AND btrim(n.name) <> ''"),
    ("tags", "id, canonical_name, type, wikidata_id", "SELECT id, canonical_name, type, wikidata_id FROM psst.tags"),
    ("tag_labels", "normalized, tag_id, label, is_canonical",
     "SELECT normalized, tag_id, label, is_canonical FROM psst.tag_labels"),
    ("tag_names", "tag_id, lang, name", "SELECT tag_id, lang, name FROM psst.tag_names"),
    ("demand", "cell, day, count", "SELECT cell, day, count FROM psst.demand"),
    ("legacy_places", "id, name, local_name, wikidata_id, osm_ref, kind, geom, city_id, spot_ids",
     """SELECT p.id, (SELECT name FROM psst.place_names WHERE place_id = p.id AND role = 'display'),
               (SELECT name FROM psst.place_names WHERE place_id = p.id AND role = 'local'),
               p.wikidata_id, p.osm_ref, p.kind, p.geom, coalesce(p.city_id, p.region_id),
               coalesce((SELECT array_agg(legacy_id ORDER BY legacy_id) FROM psst.legacy_place_ids
                         WHERE place_id = p.id), '{}')
        FROM psst.places p
        WHERE EXISTS (SELECT 1 FROM psst.place_names WHERE place_id = p.id AND role = 'display')"""),
]


def import_reference(old: Connection, new: Connection) -> dict[str, int]:
    """Copy everything in COPIES into an empty platform database, then cut boundaries into parts."""
    old.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
    row = new.execute("SELECT count(*) FROM psst.areas").fetchone()
    if row and row[0]:
        raise RuntimeError("the platform database already has boundaries; reference data is imported once")
    counts: dict[str, int] = {}
    with new.transaction():
        for table, columns, query in COPIES:
            count = 0
            with old.cursor().copy(f"COPY ({query}) TO STDOUT") as source, \
                    new.cursor().copy(f"COPY psst.{table} ({columns}) FROM STDIN") as target:  # type: ignore[arg-type]
                for chunk in source:
                    target.write(chunk)
                    count += bytes(chunk).count(b"\n")
            counts[table] = count
        new.execute("""
            INSERT INTO psst.area_parts (area_id, geom)
            SELECT id, part FROM (
                SELECT id, (ST_Dump(ST_Subdivide(ST_MakeValid(geom), 255))).geom AS part
                FROM psst.areas WHERE NOT is_point) parts
            WHERE GeometryType(part) = 'POLYGON'""")
        parts = new.execute("SELECT count(*) FROM psst.area_parts").fetchone()
        counts["area_parts"] = int(parts[0]) if parts else 0
    old.rollback()
    return counts
