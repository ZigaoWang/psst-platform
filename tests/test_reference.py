"""Reference data comes over from the previous database, read-only, once; no content does. The previous schema is
reproduced here with invented rows."""

from __future__ import annotations

import secrets

import psycopg
import pytest

from psst.places import reference
from tests.conftest import _url

OLD_SCHEMA = """
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE SCHEMA psst;
CREATE TABLE psst.admin_areas (id bigint PRIMARY KEY, source text, placetype text, level text, name text,
    country_code text, parent_id bigint, geom geometry(Geometry, 4326), is_point boolean, area_km2 float8,
    license text, wikidata_id text, osm_admin_level integer);
CREATE TABLE psst.admin_area_names (area_id bigint, lang text, name text);
CREATE TABLE psst.tags (id text, canonical_name text, type text, wikidata_id text);
CREATE TABLE psst.tag_labels (normalized text, tag_id text, label text, is_canonical boolean);
CREATE TABLE psst.tag_names (tag_id text, lang text, name text);
CREATE TABLE psst.demand (cell text, day date, count integer);
CREATE TABLE psst.places (id text, kind text, geom geometry(Point, 4326), wikidata_id text, osm_ref text,
    city_id bigint, region_id bigint);
CREATE TABLE psst.place_names (place_id text, role text, lang text, name text);
CREATE TABLE psst.legacy_place_ids (legacy_id text, place_id text);
CREATE TABLE psst.facts (id text, place_id text, headline text);
INSERT INTO psst.admin_areas VALUES
    (1, 'wof', 'country', 'country', 'Testland', 'gb', NULL,
     ST_GeomFromText('POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))', 4326), false, 12000, 'CC0', NULL, NULL),
    (2, 'wof', 'locality', 'city', 'Testville', 'gb', 1,
     ST_GeomFromText('POLYGON((0.1 0.1, 0.5 0.1, 0.5 0.5, 0.1 0.5, 0.1 0.1))', 4326), false, 600, 'CC0', 'Q1', NULL),
    (3, 'wof', 'neighbourhood', 'neighborhood', '', 'gb', 2, ST_SetSRID(ST_MakePoint(0.2, 0.2), 4326), true, NULL,
     'CC0', NULL, NULL);
INSERT INTO psst.admin_area_names VALUES (2, 'zh-Hans', '测试城'), (3, 'zh-Hans', '无名');
INSERT INTO psst.tags VALUES ('tg_aaaaaaaa', 'Lost rivers', 'theme', NULL);
INSERT INTO psst.tag_labels VALUES ('lost rivers', 'tg_aaaaaaaa', 'Lost rivers', true);
INSERT INTO psst.demand VALUES ('851f1d4bfffffff', '2026-10-01', 3);
INSERT INTO psst.places VALUES
    ('pl_0123456789', 'building', ST_SetSRID(ST_MakePoint(0.2, 0.2), 4326), 'Q2', NULL, 2, NULL);
INSERT INTO psst.place_names VALUES ('pl_0123456789', 'display', 'en', 'Old Mill');
INSERT INTO psst.legacy_place_ids VALUES ('testville/old-mill', 'pl_0123456789');
INSERT INTO psst.facts VALUES ('fa_0000000000', 'pl_0123456789', 'A story that must not come over');
"""


@pytest.fixture
def old_database(database):
    name = f"psst_test_old_{secrets.token_hex(4)}"
    with psycopg.connect(database.superuser, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')  # type: ignore[arg-type]
    url = _url(database.superuser, name)
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(OLD_SCHEMA)  # type: ignore[arg-type]
    yield url
    with psycopg.connect(database.superuser, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')  # type: ignore[arg-type]


def test_reference_data_comes_over_once_and_content_never_does(database, old_database):
    with psycopg.connect(old_database) as old, psycopg.connect(database.url("admin")) as new:
        counts = reference.import_reference(old, new)
        with pytest.raises(RuntimeError, match="imported once"):
            reference.import_reference(old, new)
    assert counts["areas"] == 2 and counts["legacy_places"] == 1 and counts["tags"] == 1 and counts["area_parts"] >= 2
    with database.connect("admin") as conn:
        legacy = conn.execute("SELECT name, spot_ids, wikidata_id FROM psst.legacy_places").fetchone()
        country = conn.execute("SELECT country_code FROM psst.areas WHERE id = 2").fetchone()["country_code"]
        stories = conn.execute("SELECT count(*) AS n FROM psst.items").fetchone()["n"]
    assert legacy == {"name": "Old Mill", "spot_ids": ["testville/old-mill"], "wikidata_id": "Q2"}
    assert country == "GB" and stories == 0
    with psycopg.connect(old_database) as old:
        assert old.execute("SELECT count(*) FROM psst.facts").fetchone()[0] == 1  # the previous database is untouched
