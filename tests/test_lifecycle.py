"""The lifecycle rules the database enforces (design.md, section 6), including the ones it must refuse."""

from __future__ import annotations

import json

import psycopg
import pytest

from tests import sample


@pytest.fixture
def story(database):
    """A story revision under check, written by a worker run, with a system run and two checker runs."""
    writer, _ = database.start_run("worker", "claude-sonnet-5-5")
    system, _ = database.start_run("system")
    checker_a, _ = database.start_run("worker", "claude-haiku-5-5")
    checker_b, _ = database.start_run("worker", "claude-haiku-5-5")
    with database.connect("admin") as conn:
        place = sample.place(conn, writer)
        snapshot = sample.snapshot(conn, system)
        revision = sample.create_story(conn, writer, place, snapshot)
        item = conn.execute("SELECT item_id FROM psst.revisions WHERE id = %s", (revision,)).fetchone()["item_id"]
        claims = [r["id"] for r in conn.execute(
            "SELECT id FROM psst.claims WHERE revision_id = %s ORDER BY n", (revision,))]
    return {"writer": writer, "system": system, "a": checker_a, "b": checker_b, "place": place,
            "snapshot": snapshot, "revision": revision, "item": item, "claims": claims}


def check(conn, run, story, kind, verdict, claim=None, note="checked"):
    return conn.execute("SELECT psst.record_check(%s, NULL, %s, %s, %s, %s, %s)",
                        (run, story["revision"], claim, kind, verdict, note)).fetchone()


def state(conn, item):
    return conn.execute("SELECT state FROM psst.items WHERE id = %s", (item,)).fetchone()["state"]


def settle(conn, story):
    return conn.execute("SELECT psst.settle(%s, NULL, %s) AS r", (story["system"], story["revision"])).fetchone()["r"]


def pass_everything(conn, story):
    check(conn, story["system"], story, "tool", "pass")
    for claim in story["claims"]:
        check(conn, story["a"], story, "claim_a", "supported", claim)
        check(conn, story["b"], story, "claim_b", "supported", claim)
    check(conn, story["a"], story, "item", "pass")


def test_submitting_creates_the_item_claims_evidence_and_history(database, story):
    with database.connect("admin") as conn:
        assert state(conn, story["item"]) == "checking"
        moves = [(r["from_state"], r["to_state"]) for r in conn.execute(
            "SELECT from_state, to_state FROM psst.transitions WHERE item_id = %s ORDER BY id", (story["item"],))]
        assert moves == [(None, "draft"), ("draft", "checking")]
        assert len(story["claims"]) == 2
        evidence = conn.execute("SELECT count(*) AS n FROM psst.evidence e JOIN psst.claims c ON c.id = e.claim_id "
                                "WHERE c.revision_id = %s", (story["revision"],)).fetchone()
        assert evidence["n"] == 2


def test_everything_passing_accepts(database, story):
    with database.connect("admin") as conn:
        pass_everything(conn, story)
        assert settle(conn, story)["outcome"] == "accept"
        assert state(conn, story["item"]) == "accepted"


def test_nothing_is_accepted_before_the_tool_check(database, story):
    with database.connect("admin") as conn:
        for claim in story["claims"]:
            check(conn, story["a"], story, "claim_a", "supported", claim)
            check(conn, story["b"], story, "claim_b", "supported", claim)
        check(conn, story["a"], story, "item", "pass")
        assert settle(conn, story) == {"outcome": "wait", "missing": "tool"}
        assert state(conn, story["item"]) == "checking"


def test_a_failed_tool_check_sends_the_revision_back(database, story):
    with database.connect("admin") as conn:
        check(conn, story["system"], story, "tool", "fail", note="claim 1: the quote is not in the snapshot")
        assert settle(conn, story)["outcome"] == "revise"
        assert state(conn, story["item"]) == "draft"


def test_disagreeing_checks_escalate_and_the_escalation_decides(database, story):
    escalator, _ = database.start_run("worker", "claude-sonnet-5-5")
    with database.connect("admin") as conn:
        check(conn, story["system"], story, "tool", "pass")
        first, second = story["claims"]
        check(conn, story["a"], story, "claim_a", "supported", first)
        check(conn, story["b"], story, "claim_b", "unsupported", first)
        check(conn, story["a"], story, "claim_a", "supported", second)
        check(conn, story["b"], story, "claim_b", "supported", second)
        check(conn, story["a"], story, "item", "pass")
        result = settle(conn, story)
        assert result["outcome"] == "escalate" and result["claims"] == [first]
        check(conn, escalator, story, "escalation", "contradicted", first, "the record says 1872")
        assert settle(conn, story)["outcome"] == "revise"
        assert state(conn, story["item"]) == "draft"


def test_an_unclear_item_check_escalates(database, story):
    with database.connect("admin") as conn:
        pass_everything(conn, story)
        check(conn, story["b"], story, "item", "unclear", note="can't tell which chimney")
        assert settle(conn, story) == {"outcome": "escalate", "claims": [], "item": True}


def test_a_run_never_checks_its_own_writing(database, story):
    with database.connect("admin") as conn, pytest.raises(psycopg.errors.InsufficientPrivilege, match="own writing"):
        check(conn, story["writer"], story, "claim_a", "supported", story["claims"][0])


def test_the_two_claim_checks_come_from_different_runs(database, story):
    with database.connect("admin") as conn:
        check(conn, story["a"], story, "claim_a", "supported", story["claims"][0])
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="different runs"):
            check(conn, story["a"], story, "claim_b", "supported", story["claims"][0])


def test_only_the_system_records_tool_checks(database, story):
    with database.connect("admin") as conn, pytest.raises(psycopg.errors.InsufficientPrivilege, match="system"):
        check(conn, story["a"], story, "tool", "pass")


def test_moves_outside_the_state_machine_are_refused(database, story):
    refused = pytest.raises(psycopg.errors.RaiseException, match="from checking to published")
    with database.connect("admin") as conn, refused:
        conn.execute("SELECT psst.transition(%s, 'published', %s, NULL, 'skip the checks')",
                     (story["item"], story["system"]))


def test_state_never_changes_without_a_transition(database, story):
    refused = pytest.raises(psycopg.errors.InsufficientPrivilege, match="psst.transition")
    with database.connect("admin") as conn, refused:
        conn.execute("UPDATE psst.items SET state = 'published' WHERE id = %s", (story["item"],))


@pytest.mark.parametrize("statement", [
    "UPDATE psst.revisions SET reason = 'changed'",
    "DELETE FROM psst.claims",
    "UPDATE psst.snapshots SET text = 'something else'",
    "DELETE FROM psst.transitions",
])
def test_history_is_never_changed(database, story, statement):
    with database.connect("admin") as conn, pytest.raises(psycopg.errors.RaiseException, match="never changed"):
        conn.execute(statement)


def test_a_new_revision_waits_for_the_current_checks(database, story):
    with database.connect("admin") as conn, pytest.raises(psycopg.errors.RaiseException, match="waits until"):
        sample.create_story(conn, story["writer"], story["place"], story["snapshot"], item_id=story["item"])


def test_rechecking_ignores_earlier_verdicts(database, story):
    with database.connect("admin") as conn:
        pass_everything(conn, story)
        settle(conn, story)
    with database.connect("admin") as conn:
        conn.execute("SELECT psst.transition(%s, 'checking', %s, NULL, 'reader report')",
                     (story["item"], story["system"]))
        assert settle(conn, story) == {"outcome": "wait", "missing": "tool"}


def test_a_translation_carries_no_claims_and_names_what_it_translates(database, story):
    translator, _ = database.start_run("worker", "claude-sonnet-5-5")
    body = json.dumps({"headline": "test", "short": "test", "long": "test", "look": "test"})
    with database.connect("admin") as conn:
        with pytest.raises(psycopg.errors.InvalidParameterValue, match="names the revision"):
            conn.execute("SELECT psst.create_revision(%s, NULL, NULL, 'translation', NULL, NULL, %s, NULL, 'zh-Hans', "
                         "%s, '[]', %s, 'translated')", (translator, story["item"], body, sample.RULEBOOK))
        revision = conn.execute(
            "SELECT psst.create_revision(%s, NULL, NULL, 'translation', NULL, NULL, %s, %s, 'zh-Hans', %s, '[]', %s, "
            "'translated') AS r", (translator, story["item"], story["revision"], body, sample.RULEBOOK)).fetchone()["r"]
        translation = conn.execute("SELECT item_id FROM psst.revisions WHERE id = %s",
                                   (revision,)).fetchone()["item_id"]
        conn.execute("SELECT psst.retire(%s, %s, 'place closed')", (story["system"], story["item"]))
        assert state(conn, translation) == "retired"


def test_runs_are_started_only_by_their_own_role(database):
    with database.connect("worker") as conn, pytest.raises(psycopg.errors.InsufficientPrivilege, match="system run"):
        conn.execute("SELECT * FROM psst.start_run('system', 'test')")


def test_an_ended_run_can_no_longer_act(database):
    _, token = database.start_run("worker", "claude-haiku-5-5")
    with database.connect("worker") as conn:
        conn.execute("SELECT psst.end_run(%s)", (token,))
        with pytest.raises(psycopg.errors.InvalidAuthorizationSpecification, match="has ended"):
            conn.execute("SELECT psst.end_run(%s)", (token,))


@pytest.mark.parametrize("statement", [
    "INSERT INTO psst.runs (id, kind, operator, token_hash) VALUES ('ru_0000000000', 'system', 'x', '\\x00')",
    "UPDATE psst.items SET position = 3",
    "SELECT psst.transition('it_0000000000', 'published', 'ru_0000000000', NULL, 'x')",
    "SELECT psst.record_check('ru_0000000000', NULL, 'rv_0000000000', NULL, 'tool', 'pass', 'x')",
    "SELECT token_hash FROM psst.runs",
])
def test_a_worker_can_only_read(database, statement):
    with database.connect("worker") as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(statement)
