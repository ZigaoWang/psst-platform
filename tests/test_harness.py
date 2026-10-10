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
        while conn.execute("""SELECT count(DISTINCT (psst.golden_fold(id), mark = 'good')) AS n
                              FROM psst.golden_stories""").fetchone()["n"] < 4:  # both folds, both kinds
            conn.execute("""UPDATE psst.golden_stories SET id = psst.new_id('gs')
                            WHERE id = (SELECT id FROM psst.golden_stories ORDER BY random() LIMIT 1)""")
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

    def chat(model, messages, tools=None, max_tokens=4000, json_only=False, timeout=300, reasoning=None):
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

    def chat(model, messages, tools=None, max_tokens=4000, json_only=False, timeout=300, reasoning=None):
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

    def chat(model, messages, tools=None, max_tokens=4000, json_only=False, timeout=300, reasoning=None):
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


def test_a_city_without_a_budget_gets_nothing(database, city, roles):
    with database.connect("admin") as conn:
        conn.execute("UPDATE psst.settings SET value = '{}' WHERE key = 'harness.city_budgets_usd'")
    with database.connect("worker") as conn:
        harness.check_budget(conn, None)  # calibrations count only against the total
        with pytest.raises(harness.BudgetReached, match="city's budget"):
            harness.check_budget(conn, sample.CITY_ID)


def test_featured_needs_a_second_model_to_agree(database, city, roles, monkeypatch):
    from tests.flow import research, tool_checks
    with database.connect("admin") as conn:
        conn.execute("UPDATE psst.settings SET value = %s WHERE key = 'routing.review'", (json.dumps(MODEL),))
        conn.execute("UPDATE psst.settings SET value = '\"openrouter:test/second\"' WHERE key = 'routing.tier_check'")
        conn.execute("""UPDATE psst.settings SET value = '{"testville": 1}' WHERE key = 'harness.city_budgets_usd'""")
    story, guide = research(database, city)
    tool_checks(database)
    worker = Worker(database, MODEL)
    with database.connect("worker") as conn:
        task = dict(conn.execute("SELECT * FROM psst.lease_task(%s, ARRAY['review'])", (worker.token,)).fetchone())

    def chat(model, messages, tools=None, max_tokens=4000, json_only=False, timeout=300, reasoning=None):
        if model == "openrouter:test/second":
            return providers.Reply(text=json.dumps({"tier": "map", "reason": "a smaller surprise"}), cost_usd=0.0001)
        return providers.Reply(text=json.dumps({"decisions": [
            {"revision": story, "mark": "good", "tier": "featured", "reason": "a real surprise", "fix": None},
            {"revision": guide, "mark": "good", "tier": None, "reason": "plain and claimed", "fix": None}],
            "notes": "a clean batch"}), cost_usd=0.001)
    monkeypatch.setattr(providers, "chat", chat)
    harness.Executor(worker.token, MODEL).run(task)
    with database.connect("admin") as conn:
        tier = conn.execute("SELECT tier FROM psst.items WHERE current_revision = %s", (story,)).fetchone()
        steps = [r["step"] for r in conn.execute("SELECT step FROM psst.harness_calls ORDER BY id")]
    assert tier["tier"] == "map" and steps == ["review", "tier_check"]


def test_a_cancelled_calibration_can_be_queued_again(database, golden):
    queue(database)
    with database.connect("admin") as conn:
        conn.execute("UPDATE psst.tasks SET state = 'cancelled' WHERE type = 'calibrate'")
    queue(database)
    with database.connect("admin") as conn:
        queued = conn.execute("SELECT count(*) AS n FROM psst.tasks WHERE type = 'calibrate' AND state = 'queued'")
        assert queued.fetchone()["n"] == 2


def test_openrouter_requests_ask_for_the_fastest_private_provider_and_the_reasoning_level(monkeypatch):
    sent = {}

    def post(url, body, headers, timeout):
        sent.update(body)
        return {"choices": [{"message": {"content": "{}"}}], "usage": {"cost": 0.0}}, 5
    monkeypatch.setattr(providers, "_post", post)
    monkeypatch.setenv("OPENROUTER_API_KEY", "invented")
    providers.chat("openrouter:test/model", [{"role": "user", "content": "x"}], reasoning="low")
    assert sent["provider"] == {"data_collection": "deny", "sort": "throughput"}
    assert sent["reasoning"] == {"effort": "low"}


def test_an_answer_cut_off_at_the_length_limit_is_asked_again_briefly(database, golden, monkeypatch):
    queue(database)
    worker, task = lease(database)
    replies = [providers.Reply(text='{"marks": [{"golden": "gs_', cut_off=True, cost_usd=0.001),
               marks_for(database, golden, task)]
    chat, calls = scripted(replies)
    monkeypatch.setattr(providers, "chat", chat)
    harness.Executor(worker.token, MODEL).run(task)
    assert "cut off at the length limit" in calls[1]["messages"][-1]["content"]


def test_a_tool_that_times_out_answers_with_an_error(database, city, roles, monkeypatch):
    from psst.harness import tools

    def slow(ctx, **arguments):
        raise TimeoutError("timed out")
    monkeypatch.setitem(tools.IMPLEMENTATIONS, "fetch_source", slow)
    ctx = tools.Context(conn=None, token="t")
    assert tools.call(ctx, "fetch_source", {"url": "https://a.example"}) == {"error": "timed out"}


def test_a_story_on_one_source_is_never_featured(database, city, roles, monkeypatch):
    from tests.flow import research, tool_checks
    with database.connect("admin") as conn:
        conn.execute("UPDATE psst.settings SET value = %s WHERE key = 'routing.review'", (json.dumps(MODEL),))
        conn.execute("UPDATE psst.settings SET value = '\"openrouter:test/second\"' WHERE key = 'routing.tier_check'")
        conn.execute("""UPDATE psst.settings SET value = '{"testville": 1}' WHERE key = 'harness.city_budgets_usd'""")
    story, guide = research(database, city)
    tool_checks(database)
    with database.connect("superuser") as conn:  # every claim of the story now quotes one page
        conn.execute("SET session_replication_role = replica")  # past the guard that keeps evidence fixed
        conn.execute("""UPDATE psst.evidence e SET snapshot_id = (SELECT min(snapshot_id) FROM psst.evidence x
                        JOIN psst.claims c ON c.id = x.claim_id WHERE c.revision_id = %s)
                        FROM psst.claims c WHERE c.id = e.claim_id AND c.revision_id = %s""", (story, story))
    worker = Worker(database, MODEL)
    with database.connect("worker") as conn:
        task = dict(conn.execute("SELECT * FROM psst.lease_task(%s, ARRAY['review'])", (worker.token,)).fetchone())

    def chat(model, messages, tools=None, max_tokens=4000, json_only=False, timeout=300, reasoning=None):
        assert model != "openrouter:test/second"  # no second reading is paid for
        return providers.Reply(text=json.dumps({"decisions": [
            {"revision": story, "mark": "good", "tier": "featured", "reason": "a real surprise", "fix": None},
            {"revision": guide, "mark": "good", "tier": None, "reason": "plain and claimed", "fix": None}],
            "notes": "a clean batch"}), cost_usd=0.001)
    monkeypatch.setattr(providers, "chat", chat)
    harness.Executor(worker.token, MODEL).run(task)
    with database.connect("admin") as conn:
        tier = conn.execute("SELECT tier FROM psst.items WHERE current_revision = %s", (story,)).fetchone()
    assert tier["tier"] == "map"


def test_an_unattended_window_caps_spend_and_stops_on_failing_passes(database, city):
    from psst.cli.harness import window_stop
    limits = {"types": None, "per_place": 0.02, "failed_share": 0.5}
    with database.connect("admin") as conn:
        conn.execute("""UPDATE psst.settings SET value = jsonb_build_object('from', now() - interval '1 hour',
                        'usd', 3) WHERE key = 'harness.window'""")
    with database.connect("worker") as conn:
        assert window_stop(conn, {"chosen": 4, "failed": 2}, limits) is None  # half failed, nothing spent yet
        assert window_stop(conn, {"chosen": 4, "failed": 3}, limits) == "3 of the pass's 4 places failed"
        harness.check_budget(conn, None)
    with database.connect("admin") as conn:
        conn.execute("""UPDATE psst.settings SET value = jsonb_build_object('from', now() - interval '1 hour',
                        'usd', 0) WHERE key = 'harness.window'""")
    with database.connect("worker") as conn, pytest.raises(harness.BudgetReached, match="window"):
        harness.check_budget(conn, None)


def test_the_report_counts_places_against_the_previous_app_and_sorts_skips(database, city):
    from psst.cli.harness import report, skip_kind
    from tests.flow import research
    research(database, city)
    with database.connect("system") as conn:
        found = report(conn, "2000-01-01T00:00:00Z", 5)
    assert found["places_standing"] >= 1 and found["samples"][0]["headline"]
    assert skip_kind("not a place to stand in front of: an area of London") == "triage: not one physical thing"
    assert skip_kind("couldn't be written to the bar: still not right after the fixes allowed: x is too long") \
        == "writing: length"


def test_words_imitating_a_tool_call_are_not_taken_as_a_skip():
    assert harness.TOOL_MARKUP.search('I will submit it. <invoke name="bash"> <parameter name="command">')
    assert not harness.TOOL_MARKUP.search("The passages give only the listing, with nothing to tell.")
