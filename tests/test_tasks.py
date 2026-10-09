"""The task queue (design.md, sections 7 and 8): leases and routing, research to review to acceptance, the one
revision a rejected item gets, and the audit that gates publishing. Records are invented."""

from __future__ import annotations

import threading

import psycopg
import pytest

from tests import sample
from tests.flow import (
    HAIKU,
    SONNET,
    Worker,
    audit_everything,
    claim_ids,
    item_state,
    queue,
    research,
    review,
    story_result,
    tool_checks,
    verdicts,
    write_and_check,
)


def queue_research(database, city, n=0):
    return queue(database, city, "research_cell", f"queue:{n}", task_input={"cell": sample.CELL})


def test_research_goes_through_review_to_accepted(database, city):
    revision = write_and_check(database, city)
    assert item_state(database, revision) == "accepted"


def test_tasks_go_only_to_the_model_they_are_routed_to(database, city):
    queue_research(database, city)
    assert Worker(database, HAIKU).lease("research_cell") is None
    assert Worker(database, SONNET).lease("research_cell") is not None


def test_routing_is_read_when_a_task_is_leased(database, city):
    queue_research(database, city)
    with database.connect("admin") as conn:
        conn.execute("UPDATE psst.settings SET value = %s WHERE key = 'routing.research_cell'", (f'"{HAIKU}"',))
    assert Worker(database, HAIKU).lease("research_cell") is not None


def test_a_writer_never_reviews_its_own_writing(database, city):
    writer = Worker(database, SONNET)
    research(database, city, writer=writer)
    tool_checks(database)
    assert writer.lease("review") is None
    assert Worker(database, SONNET).lease("review") is not None


def test_a_review_decides_every_item_of_the_submission(database, city):
    research(database, city, stories=2)
    tool_checks(database)
    reviewer = Worker(database, SONNET)
    task = reviewer.lease("review")
    assert len(task["input"]["revisions"]) == 3  # two stories and the guide, reviewed together
    with pytest.raises(psycopg.errors.InvalidParameterValue, match="decide every item"):
        reviewer.submit(task, {"decisions": [{"revision": task["input"]["revisions"][0], "decision": "approve",
                                              "note": "checked"}], "notes": "partial", "rulebook": sample.RULEBOOK})


def test_an_edit_is_the_reviewers_revision_and_needs_no_second_review(database, city):
    story, _ = research(database, city)
    tool_checks(database)
    edited = story_result(city)
    edited["body"]["headline"] = "The library that used to pump water"

    def decide(revision):
        if revision == story:
            return {"decision": "edit", "note": "a plainer headline", "body": edited["body"],
                    "claims": edited["claims"]}
        return {"decision": "approve", "note": "the record says this"}

    review(database, decide)
    with database.connect("admin") as conn:
        current = conn.execute("SELECT i.current_revision, i.state FROM psst.items i JOIN psst.revisions r "
                               "ON r.item_id = i.id WHERE r.id = %s", (story,)).fetchone()
    assert current["current_revision"] != story and current["state"] == "checking"
    tool_checks(database)
    assert item_state(database, current["current_revision"]) == "accepted"
    assert Worker(database, SONNET).lease("review") is None


def test_a_rejection_gets_one_revision_and_a_second_rejection_retires_it(database, city):
    story, _ = research(database, city)
    tool_checks(database)
    review(database, lambda r: {"decision": "reject", "note": "the telling stitches quotes together",
                                "revisable": True} if r == story else {"decision": "approve", "note": "fine"})
    assert item_state(database, story) == "draft"
    reviser = Worker(database, SONNET)
    task = reviser.lease("revise")
    assert task["input"]["problems"] == ["the telling stitches quotes together"]
    second = reviser.submit(task, story_result(city))["revision"]
    tool_checks(database)
    review(database, lambda r: {"decision": "reject", "note": "still not surprising", "revisable": True})
    assert item_state(database, second) == "retired"
    assert Worker(database, SONNET).lease("revise") is None


def test_a_rejection_no_revision_could_fix_retires_the_item(database, city):
    story, guide = research(database, city)
    tool_checks(database)
    review(database, lambda r: {"decision": "reject", "note": "a statistic, not a story", "revisable": False}
           if r == story else {"decision": "approve", "note": "fine"})
    assert item_state(database, story) == "retired"
    assert item_state(database, guide) == "accepted"


def test_a_failed_tool_check_queues_a_revision(database, city):
    (story,) = research(database, city, guide=False, story=story_result(city, year="1872"))
    assert not tool_checks(database)[0].ok
    assert item_state(database, story) == "draft"
    assert Worker(database, SONNET).lease("revise")["revision_id"] == story


def test_a_settled_review_is_audited_by_a_random_tenth(database, city):
    research(database, city, stories=3)
    tool_checks(database)
    review(database)
    with database.connect("admin") as conn:
        batch = conn.execute("SELECT size, sample_size, outcome FROM psst.audit_batches").fetchone()
    assert batch == {"size": 4, "sample_size": 1, "outcome": "open"}
    audit_everything(database)
    with database.connect("admin") as conn:
        assert conn.execute("SELECT outcome FROM psst.audit_batches").fetchone()["outcome"] == "passed"
        assert conn.execute("SELECT count(*) AS n FROM psst.publishable").fetchone()["n"] == 4


def test_a_failed_audit_revises_the_error_and_reviews_the_rest_again(database, city):
    revisions = research(database, city, stories=3)
    tool_checks(database)
    review(database)
    auditor = Worker(database, SONNET)
    task = auditor.lease("audit")
    auditor.submit(task, verdicts(claim_ids(database, task["revision_id"]), "contradicted")
                   | {"item": {"verdict": "fail", "note": "the record dates the chimney to 1902"}})
    assert item_state(database, task["revision_id"]) == "draft"
    rest = [r for r in revisions if r != task["revision_id"]]
    assert {item_state(database, r) for r in rest} == {"checking"}
    tool_checks(database)
    again = Worker(database, SONNET).lease("review")
    assert sorted(again["input"]["revisions"]) == sorted(rest)


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
    queue_research(database, city)
    for attempt in range(3):
        worker = Worker(database, SONNET)
        task = worker.lease("research_cell")
        assert task and task["attempts"] == attempt + 1
        with database.connect("admin") as conn:
            conn.execute("UPDATE psst.tasks SET leased_until = now() - interval '1 minute' WHERE id = %s",
                         (task["id"],))
        with database.connect("worker") as conn, pytest.raises(psycopg.errors.InsufficientPrivilege,
                                                               match="expired"):
            conn.execute("SELECT psst.submit_research(%s, %s, '{}', 'test')", (worker.token, task["id"]))
    assert Worker(database, SONNET).lease("research_cell") is None
    with database.connect("admin") as conn:
        assert conn.execute("SELECT state FROM psst.tasks WHERE id = %s", (task["id"],)).fetchone()["state"] == "failed"


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
    queue_research(database, city)
    first = Worker(database, SONNET)
    task = first.lease("research_cell")
    with database.connect("worker") as conn:
        conn.execute("SELECT psst.return_task(%s, %s, 'the cell needs a second look')", (first.token, task["id"]))
    assert first.lease("research_cell") is None
    assert Worker(database, SONNET).lease("research_cell")["id"] == task["id"]


def test_ending_a_run_gives_back_its_tasks(database, city):
    queue_research(database, city)
    worker = Worker(database, SONNET)
    task = worker.lease("research_cell")
    with database.connect("worker") as conn:
        conn.execute("SELECT psst.end_run(%s)", (worker.token,))
    assert Worker(database, SONNET).lease("research_cell")["id"] == task["id"]


def test_a_worker_learns_why_its_task_was_taken_away(database, city):
    queue_research(database, city)
    worker = Worker(database, SONNET)
    task = worker.lease("research_cell")
    with database.connect("admin") as conn:
        conn.execute("UPDATE psst.tasks SET state = 'cancelled', leased_by = NULL, leased_until = NULL, "
                     "problem = 'the cell was queued again' WHERE id = %s", (task["id"],))
    with pytest.raises(psycopg.Error, match="no longer yours: the cell was queued again"):
        worker.submit(task, {})
