"""The task queue (design.md, section 8): leases, routing, independence, the flow from writing to acceptance,
escalation, and audits. Records are invented."""

from __future__ import annotations

import threading

import psycopg
import pytest

from tests import sample
from tests.flow import (
    HAIKU,
    SONNET,
    Worker,
    claim_ids,
    item_state,
    queue_story,
    story_result,
    verdicts,
    write_and_check,
)


def test_a_story_goes_from_writing_to_accepted_through_the_queue(database, city):
    revision = write_and_check(database, city)
    assert item_state(database, revision) == "accepted"


def test_tasks_go_only_to_the_model_they_are_routed_to(database, city):
    queue_story(database, city)
    assert Worker(database, HAIKU).lease("write_story") is None
    assert Worker(database, SONNET).lease("write_story") is not None


def test_a_writer_never_checks_its_own_story(database, city):
    queue_story(database, city)
    writer = Worker(database, HAIKU)
    with database.connect("admin") as conn:
        conn.execute("UPDATE psst.tasks SET model = %s WHERE type = 'write_story'", (HAIKU,))
    writer.submit(writer.lease("write_story"), story_result(city))
    Worker(database, kind="system").tool_check()
    assert writer.lease("check_claims_a", "check_claims_b", "check_item") is None


def test_one_run_never_does_two_checks_of_the_same_revision(database, city):
    queue_story(database, city)
    writer = Worker(database, SONNET)
    writer.submit(writer.lease("write_story"), story_result(city))
    Worker(database, kind="system").tool_check()
    checker = Worker(database, HAIKU)
    assert checker.lease("check_claims_a")["type"] == "check_claims_a"
    assert checker.lease("check_claims_b", "check_item") is None


def test_disagreement_escalates_to_a_stronger_model(database, city):
    queue_story(database, city)
    writer = Worker(database, SONNET)
    revision = writer.submit(writer.lease("write_story"), story_result(city))["revision"]
    Worker(database, kind="system").tool_check()
    ids = claim_ids(database, revision)
    first = Worker(database, HAIKU)
    first.submit(first.lease("check_claims_a"), verdicts(ids))
    second = Worker(database, HAIKU)
    second.submit(second.lease("check_claims_b"), {"verdicts": verdicts(ids[:2])["verdicts"] + [
        {"claim": ids[2], "verdict": "unsupported", "note": "the passage is about readers, not beams"}]})
    item = Worker(database, HAIKU)
    item.submit(item.lease("check_item"), {"verdict": "pass", "note": "fine", "untraced": []})
    assert Worker(database, HAIKU).lease("escalate") is None
    escalator = Worker(database, SONNET)
    task = escalator.lease("escalate")
    assert task["input"]["claims"] == [ids[2]]
    escalator.submit(task, {"verdicts": [{"claim": ids[2], "verdict": "supported", "note": "it says beams"}]})
    assert item_state(database, revision) == "accepted"


def test_untraced_details_fail_the_item_check(database, city):
    queue_story(database, city)
    writer = Worker(database, SONNET)
    revision = writer.submit(writer.lease("write_story"), story_result(city))["revision"]
    Worker(database, kind="system").tool_check()
    checker = Worker(database, HAIKU)
    task = checker.lease("check_item")
    with pytest.raises(psycopg.errors.InvalidParameterValue, match="details no claim states"):
        checker.submit(task, {"verdict": "pass", "note": "fine", "untraced": ["the council"]})
    checker.submit(task, {"verdict": "fail", "note": "names the council, which no claim states",
                          "untraced": ["the council"]})
    assert item_state(database, revision) == "draft"
    assert Worker(database, HAIKU).lease("check_claims_a", "check_claims_b") is None
    reviser = Worker(database, SONNET)
    task = reviser.lease("revise")
    assert "the whole-item check failed" in task["input"]["problems"]


def test_a_failed_tool_check_queues_a_revision(database, city):
    queue_story(database, city)
    writer = Worker(database, SONNET)
    revision = writer.submit(writer.lease("write_story"), story_result(city, year="1872"))["revision"]
    assert not Worker(database, kind="system").tool_check().ok
    assert item_state(database, revision) == "draft"
    assert Worker(database, SONNET).lease("revise")["revision_id"] == revision


def test_parallel_workers_never_get_the_same_task(database, city):
    with database.connect("admin") as conn:
        for n in range(40):
            conn.execute("SELECT psst.enqueue(%s, 'find_photos', %s, '{}', %s, %s, NULL, NULL)",
                         (city["admin"], f"find_photos:{n}", sample.CITY_ID, city["place"]))
    taken: list[str] = []
    lock = threading.Lock()

    def work():
        worker = Worker(database, HAIKU)
        while (task := worker.lease("find_photos")) is not None:
            with lock:
                taken.append(task["id"])

    threads = [threading.Thread(target=work) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(taken) == 40 and len(set(taken)) == 40


def test_an_expired_lease_returns_the_task_and_the_last_attempt_waits_for_an_editor(database, city):
    queue_story(database, city)
    for attempt in range(3):
        worker = Worker(database, SONNET)
        task = worker.lease("write_story")
        assert task and task["attempts"] == attempt + 1
        with database.connect("admin") as conn:
            conn.execute("UPDATE psst.tasks SET leased_until = now() - interval '1 minute' WHERE id = %s",
                         (task["id"],))
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="expired"):
            worker.submit(task, story_result(city))
    assert Worker(database, SONNET).lease("write_story") is None
    with database.connect("admin") as conn:
        assert conn.execute("SELECT state FROM psst.tasks WHERE id = %s", (task["id"],)).fetchone()["state"] == "failed"


def audit(database, city, count, wrong=0):
    system = Worker(database, kind="system")
    revisions = [write_and_check(database, city, n, system=system) for n in range(count)]
    with database.connect("system") as conn:
        assert conn.execute("SELECT psst.plan_audits(%s, true) AS n", (system.token,)).fetchone()["n"] == 1
    for index in range(count):
        auditor = Worker(database, SONNET)
        task = auditor.lease("audit")
        ids = claim_ids(database, task["revision_id"])
        verdict = "contradicted" if index < wrong else "supported"
        auditor.submit(task, verdicts(ids, verdict) | {"item": {"verdict": "pass", "note": "agrees"}})
    with database.connect("admin") as conn:
        batch = conn.execute("SELECT * FROM psst.audit_batches").fetchone()
    return revisions, batch


def test_a_clean_audit_passes_the_batch(database, city):
    revisions, batch = audit(database, city, 3)
    assert batch["outcome"] == "passed" and batch["errors"] == 0
    assert all(item_state(database, r) == "accepted" for r in revisions)


def test_a_failed_audit_reopens_the_batch(database, city):
    revisions, batch = audit(database, city, 3, wrong=1)
    assert batch["outcome"] == "failed" and batch["errors"] == 1
    states = sorted(item_state(database, r) for r in revisions)
    assert states == ["checking", "checking", "draft"]
    assert Worker(database, SONNET).lease("revise") is not None
    assert Worker(database, kind="system").lease("tool_check") is not None


def test_a_rule_change_rechecks_what_was_checked_under_the_old_rulebook(database, city, monkeypatch):
    from psst.checks import rechecks
    revision = write_and_check(database, city)
    assert item_state(database, revision) == "accepted"
    system = Worker(database, kind="system")
    monkeypatch.setattr(rechecks.rules, "load", lambda: type("Rulebook", (), {"version": "fedcba987654"})())
    with database.connect("system") as conn:
        conn.autocommit = False
        assert rechecks.recheck(conn, system.token) == {"rechecked": 0, "sent_back": 1}
    assert item_state(database, revision) == "checking"
    assert Worker(database, kind="system").lease("tool_check") is not None


def test_a_task_given_back_goes_to_another_run(database, city):
    queue_story(database, city)
    first = Worker(database, SONNET)
    task = first.lease("write_story")
    with database.connect("worker") as conn:
        conn.execute("SELECT psst.return_task(%s, %s, 'the angle does not hold up')", (first.token, task["id"]))
    assert first.lease("write_story") is None
    assert Worker(database, SONNET).lease("write_story")["id"] == task["id"]


def test_ending_a_run_gives_back_its_tasks(database, city):
    queue_story(database, city)
    worker = Worker(database, SONNET)
    task = worker.lease("write_story")
    with database.connect("worker") as conn:
        conn.execute("SELECT psst.end_run(%s)", (worker.token,))
    assert Worker(database, SONNET).lease("write_story")["id"] == task["id"]
