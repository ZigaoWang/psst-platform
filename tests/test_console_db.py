"""The console's side of the database: accounts, sessions, and the editor actions, each logged (design.md,
section 12). Accounts and content are invented."""

from __future__ import annotations

import psycopg
import pytest

from tests import sample
from tests.flow import HAIKU, SONNET, Worker, claim_ids, item_state, queue_story, story_result, write_and_check

PASSWORD = "a long test password"


@pytest.fixture
def session(database):
    with database.connect("admin") as conn:
        conn.execute("SELECT psst.console_add_account('editor', %s)", (PASSWORD,))
    with database.connect("console") as conn:
        return conn.execute("SELECT psst.console_sign_in('editor', %s) AS t", (PASSWORD,)).fetchone()["t"]


def console(database, sql, *params):
    with database.connect("console") as conn:
        return conn.execute(sql, params).fetchone()


def test_signing_in_needs_the_right_password(database, session):
    assert session
    assert console(database, "SELECT psst.console_sign_in('editor', 'wrong password') AS t")["t"] is None
    assert console(database, "SELECT psst.console_sign_in('nobody', %s) AS t", PASSWORD)["t"] is None
    assert console(database, "SELECT * FROM psst.console_session(%s)", session)["name"] == "editor"


def test_a_signed_out_session_can_no_longer_act(database, session, city):
    console(database, "SELECT psst.console_sign_out(%s)", session)
    with pytest.raises(psycopg.errors.InvalidAuthorizationSpecification, match="sign in again"):
        console(database, "SELECT psst.console_plan_audits(%s, false)", session)


def test_passwords_never_leave_the_database(database, session):
    with database.connect("worker") as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("SELECT password_hash FROM psst.console_accounts")
    with database.connect("console") as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("SELECT token_hash FROM psst.console_sessions")


def test_an_editor_verdict_sends_accepted_work_back_and_is_logged(database, session, city):
    revision = write_and_check(database, city)
    claim = claim_ids(database, revision)[0]
    console(database, "SELECT psst.console_verdict(%s, %s, %s, 'contradicted', 'the listing says 1872')",
            session, revision, claim)
    assert item_state(database, revision) == "draft"
    assert Worker(database, SONNET).lease("revise")["input"]["problems"] == ["the listing says 1872"]
    with database.connect("console") as conn:
        actions = [r["action"] for r in conn.execute("SELECT action FROM psst.console_actions ORDER BY id")]
    assert actions == ["sign in", "verdict"]


def test_an_editor_can_retire_and_recheck(database, session, city):
    revision = write_and_check(database, city)
    with database.connect("admin") as conn:
        item = conn.execute("SELECT item_id FROM psst.revisions WHERE id = %s", (revision,)).fetchone()["item_id"]
    console(database, "SELECT psst.console_recheck(%s, %s, 'a reader says the date is wrong')", session, item)
    assert item_state(database, revision) == "checking"
    assert Worker(database, kind="system").lease("tool_check")
    with pytest.raises(psycopg.errors.InvalidParameterValue, match="say why"):
        console(database, "SELECT psst.console_retire(%s, %s, '')", session, item)
    console(database, "SELECT psst.console_retire(%s, %s, 'demolished in 2026')", session, item)
    assert item_state(database, revision) == "retired"


def test_task_controls(database, session, city):
    queue_story(database, city)
    task = Worker(database, SONNET).lease("write_story")
    assert console(database, "SELECT psst.console_task(%s, %s, 'release') AS s", session, task["id"])["s"] == "queued"
    assert console(database, "SELECT psst.console_task(%s, %s, 'cancel') AS s", session, task["id"])["s"] == "cancelled"
    assert console(database, "SELECT psst.console_task(%s, %s, 'requeue') AS s", session, task["id"])["s"] == "queued"


def test_settings_change_with_a_reason_and_keep_their_history(database, session):
    console(database, "SELECT psst.console_change_setting(%s, 'audit.threshold.story', '0.01', 'tighter for launch')",
            session)
    assert console(database, "SELECT psst.setting('audit.threshold.story') AS v")["v"] == 0.01
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        console(database, "SELECT psst.console_change_setting(%s, 'audit.threshold.story', '\"low\"', 'why')", session)
    with database.connect("console") as conn:
        change = conn.execute("SELECT old_value, new_value, reason FROM psst.setting_changes").fetchone()
    assert change == {"old_value": 0.02, "new_value": 0.01, "reason": "tighter for launch"}


def test_one_publish_request_at_a_time(database, session):
    console(database, "SELECT psst.console_request(%s, 'publish', '{\"only_staging\": true}')", session)
    with pytest.raises(psycopg.errors.RaiseException, match="already waiting"):
        console(database, "SELECT psst.console_request(%s, 'publish', '{}')", session)


def test_accuracy_counts_overturned_verdicts(database, session, city):
    queue_story(database, city)
    writer = Worker(database, SONNET)
    revision = writer.submit(writer.lease("write_story"), story_result(city))["revision"]
    Worker(database, kind="system").tool_check()
    ids = claim_ids(database, revision)
    first, second = Worker(database, HAIKU), Worker(database, HAIKU)
    first.submit(first.lease("check_claims_a"), {"verdicts": [
        {"claim": c, "verdict": "supported", "note": "says so"} for c in ids]})
    second.submit(second.lease("check_claims_b"), {"verdicts": [
        {"claim": c, "verdict": "unsupported" if c == ids[0] else "supported", "note": "checked"} for c in ids]})
    escalator = Worker(database, SONNET)
    escalator.submit(escalator.lease("escalate"), {"verdicts": [
        {"claim": ids[0], "verdict": "supported", "note": "the record says 1871"}]})
    with database.connect("console") as conn:
        rows = {r["kind"]: r for r in conn.execute("SELECT * FROM psst.model_accuracy")}
    assert rows["claim_b"]["overturned"] == 1 and rows["claim_b"]["judged"] == 1
    assert rows["claim_a"]["overturned"] == 0



def test_an_editor_corrects_a_place_link_and_its_guide_is_revised(database, city, monkeypatch):
    from psst.core import http
    from psst.places import coords, names
    from psst.services.system_worker import SystemWorker
    guide = write_and_check(database, city, kind="guide")
    with database.connect("admin") as conn:
        conn.execute("SELECT psst.console_add_account('editor', 'a long test password')")
        other = sample.place(conn, city["admin"], wikidata="Q900002")
    with database.connect("console") as conn:
        session = conn.execute("SELECT psst.console_sign_in('editor', 'a long test password') AS t").fetchone()["t"]
        with pytest.raises(psycopg.Error, match=f"already the item of place {other}"):
            conn.execute("SELECT psst.console_relink_place(%s, %s, 'Q900002', 'wrong item')", (session, city["place"]))
    with database.connect("console") as conn:
        conn.execute("SELECT psst.console_relink_place(%s, %s, 'Q900003', 'the item is the estate')",
                     (session, city["place"]))
    monkeypatch.setattr(coords, "resolve", lambda places: {
        places[0]["id"]: coords.Position(51.5002, -0.0501, "wikidata", "Q900003")})
    monkeypatch.setattr(http, "wikidata_entities", lambda qids, props: {
        "Q900003": {"labels": {"fr": {"value": "Station de pompage"}}}})
    monkeypatch.setattr(names, "osm_tags", lambda refs: {})
    system = SystemWorker(lambda: psycopg.connect(database.url("system"), row_factory=psycopg.rows.dict_row),
                          Worker(database, kind="system").token)
    assert system.step()
    assert item_state(database, guide) == "draft"
    with database.connect("admin") as conn:
        place = conn.execute("SELECT wikidata_id, coord_ref FROM psst.places WHERE id = %s",
                             (city["place"],)).fetchone()
        task = conn.execute("SELECT input FROM psst.tasks WHERE type = 'revise'").fetchone()
    assert place == {"wikidata_id": "Q900003", "coord_ref": "Q900003"}
    assert "from Q900001 to Q900003" in task["input"]["problems"][0]
