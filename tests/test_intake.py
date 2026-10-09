"""Reader intake: a report records the problem and sends a published item back to checking while it stays live; it
is resolved when the item is published again. Demand counts only valid cells. Content is invented."""

from __future__ import annotations

import psycopg
import pytest

from psst.services.intake import Intake
from tests.flow import HAIKU, Worker, audit_everything, claim_ids, item_state, run_publish, verdicts, write_and_check


@pytest.fixture
def intake(database):
    return Intake(lambda: psycopg.connect(database.url("api")))


def published(database, city, site):
    story = write_and_check(database, city, kind="story")
    write_and_check(database, city, kind="guide")
    audit_everything(database)
    run_publish(database, site)
    with database.connect("admin") as conn:
        return story, conn.execute("SELECT item_id FROM psst.revisions WHERE id = %s", (story,)).fetchone()["item_id"]


def test_a_report_sends_a_published_item_back_to_checking_and_it_stays_live(database, city, site, intake):
    revision, item = published(database, city, site)
    assert intake.report({"factId": item, "reason": "wrong", "message": "The date is 1872.", "appVersion": "2.0"}) \
        == (201, {"status": "received"})
    assert intake.report({"factId": item, "reason": "wrong"})[0] == 201
    with database.connect("admin") as conn:
        live = conn.execute("SELECT published_revision FROM psst.items WHERE id = %s", (item,)).fetchone()
        reports = conn.execute("SELECT count(*) AS n FROM psst.reports WHERE state = 'open'").fetchone()["n"]
    assert item_state(database, revision) == "checking" and live["published_revision"] == revision
    assert reports == 2


def test_reports_are_resolved_when_the_item_is_published_again(database, city, site, intake):
    revision, item = published(database, city, site)
    intake.report({"factId": item, "reason": "outdated"})
    Worker(database, kind="system").tool_check()
    for task_type in ("check_claims_a", "check_claims_b", "check_item"):
        checker = Worker(database, HAIKU)
        checker.submit(checker.lease(task_type), verdicts(claim_ids(database, revision)) if task_type != "check_item"
                       else {"verdict": "pass", "note": "still right", "untraced": []})
    assert item_state(database, revision) == "accepted"
    run_publish(database, site)
    assert item_state(database, revision) == "published"
    with database.connect("admin") as conn:
        assert conn.execute("SELECT state FROM psst.reports").fetchone()["state"] == "resolved"


def test_reports_need_a_published_item_and_a_known_reason(database, intake):
    assert intake.report({"factId": "it_0000000000", "reason": "wrong"})[0] == 422
    assert intake.report({"factId": "fa_0000000000", "reason": "wrong"})[0] == 400
    assert intake.report({"factId": "it_0000000000", "reason": "boring"})[0] == 400


def test_demand_counts_only_resolution_5_cells(database, intake):
    assert intake.demand({"cell": "85194ad3fffffff"})[0] == 204
    assert intake.demand({"cell": "85194ad3fffffff"})[0] == 204
    assert intake.demand({"cell": "87194ad32ffffff"})[0] == 400
    with database.connect("admin") as conn:
        assert conn.execute("SELECT count FROM psst.demand").fetchone()["count"] == 2
