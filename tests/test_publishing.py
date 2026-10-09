"""A city publishes from the database to staging, checks out, and is promoted (design.md, section 19, M4).
Content is invented."""

from __future__ import annotations

import pytest

from psst.publish.run import PublishError, rollback
from tests import sample
from tests.flow import audit_everything, item_state, production_city, run_publish, write_and_check


def ready(database, city, n=0, place=None):
    story = write_and_check(database, city, n, kind="story", place=place)
    guide = write_and_check(database, city, n, kind="guide", place=place)
    return story, guide


def test_a_city_publishes_through_staging_to_production(database, city, site):
    story, guide = ready(database, city)
    audit_everything(database)
    outcome = run_publish(database, site)
    assert outcome.promoted and outcome.counts == {"places": 1, "facts": 1, "trails": 0}
    assert item_state(database, story) == item_state(database, guide) == "published"
    manifest, pack = production_city(site)
    place = pack["places"][0]
    fact = place["facts"][0]
    assert fact["long"].endswith(fact["look"])  # the current app shows `look` as the last paragraph
    assert fact["sources"][fact["claims"][0]["sources"][0]]["url"] == "https://records.example.org/pump-house"
    assert place["guide"]["keyFacts"] == [{"property": "P571", "label": "built", "value": "1871"}]
    assert manifest["cities"][0]["cityId"] == str(sample.CITY_ID)


def test_nothing_publishes_before_its_audit_passes(database, city, site):
    ready(database, city)
    with pytest.raises(Exception, match="Nothing can publish yet"):
        run_publish(database, site)


def test_a_place_waits_for_its_guide(database, city, site):
    ready(database, city)
    with database.connect("admin") as conn:
        other = sample.place(conn, city["admin"], wikidata="Q900002")
    write_and_check(database, city, 1, kind="story", place=other)
    audit_everything(database)
    outcome = run_publish(database, site)
    assert outcome.counts["places"] == 1
    assert {"place": other, "reason": "no guide information ready"} in outcome.held


def test_publishing_again_changes_nothing(database, city, site):
    ready(database, city)
    audit_everything(database)
    first = run_publish(database, site)
    _, pack_before = production_city(site)
    second = run_publish(database, site)
    _, pack_after = production_city(site)
    assert second.changes == {"added": [], "removed": [], "updated": []}
    assert pack_before == pack_after and second.version >= first.version


def test_a_drop_in_places_is_refused_unless_explained(database, city, site):
    ready(database, city)
    with database.connect("admin") as conn:
        other = sample.place(conn, city["admin"], wikidata="Q900002")
    story, _ = ready(database, city, 1, place=other)
    audit_everything(database)
    run_publish(database, site)
    with database.connect("admin") as conn:
        item = conn.execute("SELECT item_id FROM psst.revisions WHERE id = %s", (story,)).fetchone()["item_id"]
        conn.execute("SELECT psst.retire(%s, %s, 'the place was demolished')", (city["admin"], item))
    with pytest.raises(PublishError) as refused:
        run_publish(database, site)
    assert any("places would drop from 2 to 1" in p for p in refused.value.problems)
    assert production_city(site)[0]["counts"]["places"] == 2
    assert run_publish(database, site, allow_shrink="the place was demolished").promoted


def test_rollback_points_production_at_the_version_before(database, city, site):
    ready(database, city)
    audit_everything(database)
    first = run_publish(database, site)
    with database.connect("admin") as conn:
        other = sample.place(conn, city["admin"], wikidata="Q900002")
    ready(database, city, 1, place=other)
    audit_everything(database)
    second = run_publish(database, site)
    assert second.version != first.version
    with database.connect("publisher") as conn:
        token = conn.execute("SELECT * FROM psst.start_run('publisher', 'test')").fetchone()["token"]
        conn.autocommit = False
        assert rollback(conn, token, site["channels"]) == (second.version, first.version)
    assert production_city(site)[0]["contentVersion"] == first.version
