"""The review gate (decision 25): the reviewer re-marks the golden set blind, in two folds, and must agree with the
editor before reviews run or anything publishes. Stories and marks are invented."""

from __future__ import annotations

import psycopg
import pytest

from psst.publish.run import PublishError
from psst.services.system_worker import SystemWorker
from tests import sample
from tests.flow import SONNET, Worker, research, run_publish, tool_checks

MARKS = ["good", "good", "weak", "bad", "good", "weak", "good", "bad", "good", "weak"]


@pytest.fixture
def golden(database, city):
    with database.connect("admin") as conn:
        conn.execute("UPDATE psst.settings SET value = 'false' WHERE key = 'gate.open'")
        for n, mark in enumerate(MARKS):
            conn.execute("""INSERT INTO psst.golden_stories (id, city_id, place, headline, short, long, sources, mark,
                            reason, origin, marked_by) VALUES (psst.new_id('gs'), %s, %s, %s, %s, %s, 'Records Office',
                            %s, %s, 'invented', 'editor')""",
                         (sample.CITY_ID, f"Place {n}", f"Headline {n}", f"Short {n}.", f"Long {n}.", mark,
                          f"Reason {n}."))
        return {r["id"]: r["mark"] for r in conn.execute("SELECT id, mark FROM psst.golden_stories")}


def refresh(database, city):
    system = SystemWorker(lambda: psycopg.connect(database.url("system"), row_factory=psycopg.rows.dict_row),
                          Worker(database, kind="system").token)
    return system.refresh_gate()


def calibrate(database, golden, wrong=0):
    """Mark both folds, getting `wrong` of the editor's marks wrong."""
    flips = {"good": "weak", "weak": "bad", "bad": "good"}
    misses = set(sorted(golden)[:wrong])
    while (task := (worker := Worker(database, SONNET)).lease("calibrate")) is not None:
        with database.connect("admin") as conn:
            fold = [r["id"] for r in conn.execute("SELECT id FROM psst.golden_stories WHERE psst.golden_fold(id) = %s",
                                                  (task["input"]["fold"],))]
        marks = [{"golden": g, "mark": flips[golden[g]] if g in misses else golden[g], "reason": "read it"}
                 for g in fold]
        with database.connect("worker") as conn:
            conn.execute("SELECT psst.submit_calibration(%s, %s, %s, %s)",
                         (worker.token, task["id"], psycopg.types.json.Jsonb({"marks": marks, "notes": "n"}),
                          task["input"]["prompt_version"]))


def test_reviews_wait_while_the_gate_is_closed(database, city, golden):
    research(database, city)
    tool_checks(database)
    assert Worker(database, SONNET).lease("review") is None


def test_the_gate_opens_when_both_folds_agree_with_the_editor(database, city, golden):
    status = refresh(database, city)
    assert status["open"] is False and sorted(status["missing_folds"]) == [0, 1]
    calibrate(database, golden)
    status = refresh(database, city)
    assert status["open"] is True and float(status["agreement"]) == 1.0
    research(database, city)
    tool_checks(database)
    assert Worker(database, SONNET).lease("review") is not None


def test_the_gate_stays_closed_below_the_agreement_required(database, city, golden):
    refresh(database, city)
    calibrate(database, golden, wrong=2)  # 8 of 10, under 90 percent
    status = refresh(database, city)
    assert status["open"] is False and float(status["agreement"]) == 0.8


def test_a_new_review_prompt_needs_a_new_calibration(database, city, golden, monkeypatch):
    refresh(database, city)
    calibrate(database, golden)
    assert refresh(database, city)["open"] is True
    from psst.tasks import prompts
    real = prompts.load
    changed = type("Prompt", (), {"version": "changed00000", "text": "a new review prompt"})()
    monkeypatch.setattr(prompts, "load", lambda kind: changed if kind == "review" else real(kind))
    assert refresh(database, city)["open"] is False


def test_nothing_publishes_while_the_gate_is_closed(database, city, golden, site):
    with pytest.raises(PublishError, match="review gate is closed"):
        run_publish(database, site)
