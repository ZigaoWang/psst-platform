"""The harness (decision 28): a task done by an API model, with its tools, its fixes, its trace, and its budget. The
provider is replaced by scripted replies; stories and marks are invented."""

from __future__ import annotations

import json

import psycopg
import pytest

from psst.harness import executor as harness
from psst.harness import providers
from tests import sample
from tests.flow import Worker

MODEL = "openrouter:test/cheap-model"


@pytest.fixture
def roles(database, monkeypatch):
    for role in ("worker", "system", "admin"):
        monkeypatch.setenv(f"PSST_DATABASE_URL_{role.upper()}", database.url(role))


@pytest.fixture
def golden(database, city, roles):
    with database.connect("admin") as conn:
        for n, mark in enumerate(["good", "weak", "bad", "good", "weak", "good", "bad", "good", "weak", "good"]):
            conn.execute("""INSERT INTO psst.golden_stories (id, city_id, place, headline, short, long, sources, mark,
                            tier, reason, origin, marked_by) VALUES (psst.new_id('gs'), %s, %s, %s, %s, %s,
                            'Records Office', %s, %s, %s, 'invented', 'editor')""",
                         (sample.CITY_ID, f"Place {n}", f"Headline {n}", f"Short {n}.", f"Long {n}.", mark,
                          "map" if mark == "good" else None, f"Reason {n}."))
        return {r["id"]: (r["mark"], r["tier"]) for r in conn.execute("SELECT id, mark, tier FROM psst.golden_stories")}


def queue(database):
    system = Worker(database, kind="system")
    with database.connect("system") as conn:
        conn.execute("SELECT psst.queue_calibration(%s, %s, 'prompt000001', NULL)", (system.token, MODEL))


def lease(database):
    worker = Worker(database, MODEL)
    with database.connect("worker") as conn:
        task = conn.execute("SELECT * FROM psst.lease_task(%s, ARRAY['calibrate'])", (worker.token,)).fetchone()
    return worker, dict(task)


def marks_for(database, golden, task):
    with database.connect("admin") as conn:
        fold = [r["id"] for r in conn.execute("SELECT id FROM psst.golden_stories WHERE psst.golden_fold(id) = %s",
                                              (task["input"]["fold"],))]
    return {"marks": [{"golden": g, "mark": golden[g][0], "tier": golden[g][1], "reason": "read it"} for g in fold],
            "notes": "marked the fold"}


def scripted(replies):
    """A provider that answers with the replies in order, each costing a tenth of a cent."""
    calls = []

    def chat(model, messages, tools=None, max_tokens=4000, json_only=False, timeout=300):
        calls.append({"messages": list(messages), "tools": tools})
        reply = replies.pop(0)
        if isinstance(reply, providers.Reply):
            return reply
        return providers.Reply(text=json.dumps(reply), input_tokens=1000, cached_tokens=800, output_tokens=200,
                               cost_usd=0.001, latency_ms=5)
    return chat, calls


def test_a_calibration_done_by_a_model_is_traced_and_counted(database, golden, monkeypatch):
    queue(database)
    worker, task = lease(database)
    chat, calls = scripted([{"marks": []}, marks_for(database, golden, task)])  # the first answer misses every mark
    monkeypatch.setattr(providers, "chat", chat)
    outcome = harness.Executor(worker.token, MODEL).run(task)
    assert outcome["calls"] == 2 and outcome["cost_usd"] == pytest.approx(0.002)
    assert "Not submitted" in calls[1]["messages"][-1]["content"]  # the problems went back to the model
    assert calls[0]["messages"][0]["content"].startswith(harness.PREAMBLE[:40])  # shared prefix first
    with database.connect("admin") as conn:
        calibration = conn.execute("SELECT model, agreed, marked FROM psst.calibrations").fetchone()
        traced = conn.execute("SELECT count(*) AS n, sum(cost_usd) AS cost, min(step) AS step "
                              "FROM psst.harness_calls").fetchone()
    assert calibration["model"] == MODEL and calibration["agreed"] == calibration["marked"]
    assert traced["n"] == 2 and float(traced["cost"]) == pytest.approx(0.002) and traced["step"] == "calibrate"


def test_a_model_that_never_gets_it_right_gives_the_task_back(database, golden, monkeypatch):
    queue(database)
    worker, task = lease(database)
    chat, _ = scripted([{"marks": []}] * 3)
    monkeypatch.setattr(providers, "chat", chat)
    outcome = harness.Executor(worker.token, MODEL).run(task)
    assert outcome["outcome"] == "returned" and "still not right" in outcome["reason"]
    with database.connect("admin") as conn:
        state = conn.execute("SELECT state FROM psst.tasks WHERE id = %s", (task["id"],)).fetchone()
    assert state["state"] == "queued"


def test_the_harness_stops_at_its_budget(database, golden, monkeypatch):
    queue(database)
    worker, task = lease(database)
    with database.connect("admin") as conn:
        conn.execute("UPDATE psst.settings SET value = '0.0015' WHERE key = 'harness.budget_usd'")
    chat, _ = scripted([{"marks": []}, {"marks": []}, {"marks": []}])
    monkeypatch.setattr(providers, "chat", chat)
    with pytest.raises(harness.BudgetReached):
        harness.Executor(worker.token, MODEL).run(task)
    with database.connect("admin") as conn:
        spent = conn.execute("SELECT sum(cost_usd) AS s FROM psst.harness_calls").fetchone()
    assert float(spent["s"]) == pytest.approx(0.002)  # it stopped before a third call


def test_tool_calls_are_run_and_traced(database, city, roles, monkeypatch):
    from psst.harness import tools
    worker = Worker(database, MODEL)
    with database.connect("admin") as conn:
        snapshot = conn.execute("SELECT id FROM psst.snapshots LIMIT 1").fetchone()["id"]
    replies = [providers.Reply(text="", tool_calls=[providers.ToolCall("c1", "search_snapshot",
                                                                         {"snapshot": snapshot, "words": "1871"})],
                               input_tokens=100, output_tokens=10, cost_usd=0.0001),
               {"answer": "done"}]
    chat, calls = scripted(replies)
    monkeypatch.setattr(providers, "chat", chat)
    ctx = tools.Context(conn=psycopg.connect(database.url("worker"), row_factory=psycopg.rows.dict_row,
                                             autocommit=True), token=worker.token)
    answer = harness.Executor(worker.token, MODEL).converse(
        "review", "system", "user", {"id": None, "city_id": None}, "v1", lambda a: a, ctx, harness.Spend())
    assert answer == {"answer": "done"}
    assert calls[1]["messages"][-1]["role"] == "tool" and "1871" in calls[1]["messages"][-1]["content"]
    with database.connect("admin") as conn:
        tool = conn.execute("SELECT tool, input FROM psst.harness_tool_calls").fetchone()
    assert tool["tool"] == "search_snapshot" and tool["input"]["words"] == "1871"


@pytest.mark.parametrize("text", ['{"a": 1}', '```json\n{"a": 1}\n```', 'Here it is: {"a": 1} done'])
def test_a_json_answer_is_read_with_or_without_a_fence(text):
    assert harness.parse_json(text) == {"a": 1}


def test_the_service_works_what_is_routed_to_a_harness_model(database, golden, monkeypatch):
    import argparse

    from psst.cli import harness as harness_cli
    with database.connect("admin") as conn:
        conn.execute("UPDATE psst.settings SET value = %s WHERE key = 'routing.review'", (json.dumps(MODEL),))
    queue(database)

    def chat(model, messages, tools=None, max_tokens=4000, json_only=False, timeout=300):
        items = json.loads(messages[1]["content"])["data"]["items"]
        marks = [{"golden": i["id"], "mark": golden[i["id"]][0], "tier": golden[i["id"]][1], "reason": "read it"}
                 for i in items]
        return providers.Reply(text=json.dumps({"marks": marks, "notes": "marked the fold"}), cost_usd=0.001)
    monkeypatch.setattr(providers, "chat", chat)
    assert harness_cli.run_work(argparse.Namespace(once=True)) == 0
    with database.connect("admin") as conn:
        done = conn.execute("SELECT count(*) AS n FROM psst.calibrations WHERE model = %s", (MODEL,)).fetchone()
        open_runs = conn.execute("SELECT count(*) AS n FROM psst.runs WHERE notes = 'harness service' "
                                 "AND ended_at IS NULL").fetchone()
    assert done["n"] == 2 and open_runs["n"] == 0


def test_a_panel_takes_the_majority_mark_and_tier():
    def answer(*marks):
        return {"marks": [{"golden": f"gs_{n}", "mark": m, "tier": t, "reason": f"{m} {t}"}
                          for n, (m, t) in enumerate(marks)], "notes": "marked"}
    combined = harness.combine("calibrate", [answer(("good", "map"), ("weak", None), ("good", "featured")),
                                             answer(("good", "featured"), ("bad", None), ("weak", None)),
                                             answer(("good", "featured"), ("weak", None), ("bad", None))])
    marks = {m["golden"]: (m["mark"], m["tier"]) for m in combined["marks"]}
    assert marks == {"gs_0": ("good", "featured"), "gs_1": ("weak", None), "gs_2": ("bad", None)}  # a tie goes strict


def test_a_panel_calibrates_as_one_model(database, golden, monkeypatch):
    panel = "vote:openrouter:test/a+openrouter:test/b+openrouter:test/c"
    system = Worker(database, kind="system")
    with database.connect("system") as conn:
        conn.execute("SELECT psst.queue_calibration(%s, %s, 'prompt000001', NULL)", (system.token, panel))
    worker = Worker(database, panel)
    with database.connect("worker") as conn:
        task = dict(conn.execute("SELECT * FROM psst.lease_task(%s, ARRAY['calibrate'])", (worker.token,)).fetchone())

    def chat(model, messages, tools=None, max_tokens=4000, json_only=False, timeout=300):
        items = json.loads(messages[1]["content"])["data"]["items"]
        wrong = model == "openrouter:test/c"  # one member always says weak; the other two outvote it
        marks = [{"golden": i["id"], "mark": "weak" if wrong else golden[i["id"]][0],
                  "tier": None if wrong else golden[i["id"]][1], "reason": "read it"} for i in items]
        return providers.Reply(text=json.dumps({"marks": marks, "notes": "marked the fold"}), cost_usd=0.001)
    monkeypatch.setattr(providers, "chat", chat)
    outcome = harness.Executor(worker.token, panel).run(task)
    assert outcome["calls"] == 3
    with database.connect("admin") as conn:
        row = conn.execute("SELECT model, agreed, marked FROM psst.calibrations").fetchone()
    assert row["model"] == panel and row["agreed"] == row["marked"]


def test_a_namespaced_tool_name_reaches_the_tool(database, city, roles):
    from psst.harness import tools
    worker = Worker(database, MODEL)
    with database.connect("admin") as conn:
        snapshot = conn.execute("SELECT id FROM psst.snapshots LIMIT 1").fetchone()["id"]
    ctx = tools.Context(conn=psycopg.connect(database.url("worker"), row_factory=psycopg.rows.dict_row,
                                             autocommit=True), token=worker.token)
    found = tools.call(ctx, "psst:search_snapshot", {"snapshot": snapshot, "words": "1871"})
    assert "error" not in found and "1871" in found["passages"]
