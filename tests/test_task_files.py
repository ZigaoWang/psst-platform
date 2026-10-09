"""Task files give each worker what its task needs and nothing that would bias it, results are checked before
they're submitted, and the system worker runs tool checks from the queue."""

from __future__ import annotations

import json

import psycopg

from psst.cli import tasks as task_cli
from psst.services.system_worker import SystemWorker
from psst.tasks import files, prompts
from tests import sample
from tests.flow import SONNET, Worker, queue, research, story_result


def leased(database, worker, *types):
    task = worker.lease(*types)
    with database.connect("worker") as conn:
        return files.build(conn, task)


def written(database, city):
    """A story researched for the city's place, through the system worker's tool check."""
    (revision,) = research(database, city, guide=False)
    system = Worker(database, kind="system")
    worker = SystemWorker(lambda: psycopg.connect(database.url("system"), row_factory=psycopg.rows.dict_row),
                          system.token)
    assert worker.step() and not worker.step()
    return revision


def add_reference(database):
    with database.connect("admin") as conn:
        conn.execute("""INSERT INTO psst.style_references (id, city_id, place, headline, short, long, look, why, origin)
                        VALUES (psst.new_id('sr'), %s, 'Old Pump House', 'A library that pumped water',
                                'The reading room was the engine house.', 'An invented reference story.',
                                'Look up at the chimney.', 'specific and told plainly', 'invented')""",
                     (sample.CITY_ID,))


def test_the_reviewer_sees_the_prose_beside_its_claims_and_passages(database, city):
    add_reference(database)
    written(database, city)
    document = leased(database, Worker(database, SONNET), "review")
    item = document["data"]["items"][0]
    assert item["body"]["headline"] and item["type"] == "story"
    assert item["claims"][0]["passages"][0]["quote"] == "built in 1871 by the engineer Ada Thorne"
    assert item["claims"][0]["passages"][0]["before"].endswith("was ")
    assert document["data"]["reference_stories"][0]["headline"] == "A library that pumped water"
    assert document["prompt_version"] == prompts.load("review").version


def test_research_sees_the_reference_stories_and_the_rules(database, city):
    add_reference(database)
    queue(database, city, "research_cell", "files", task_input={"cell": sample.CELL})
    document = leased(database, Worker(database, SONNET), "research_cell")
    assert document["data"]["reference_stories"][0]["why"] == "specific and told plainly"
    assert {"story", "guide", "kinds"} <= set(document["data"]["rules"])


def test_the_system_worker_runs_queued_tool_checks(database, city):
    revision = written(database, city)
    with database.connect("admin") as conn:
        verdict = conn.execute("SELECT verdict FROM psst.checks WHERE revision_id = %s AND kind = 'tool'",
                               (revision,)).fetchone()["verdict"]
        queued = {r["type"] for r in conn.execute("SELECT type FROM psst.tasks WHERE state = 'queued'")}
    assert verdict == "pass"
    assert queued == {"review"}


def test_a_result_is_refused_before_submitting_when_it_breaks_the_rules(database, city, monkeypatch):
    monkeypatch.setenv("PSST_DATABASE_URL_WORKER", database.url("worker"))
    queue(database, city, "research_cell", "refused", task_input={"cell": sample.CELL})
    document = leased(database, Worker(database, SONNET), "research_cell")
    wrong = story_result(city, year="1872")
    result = {"places": [{"existing": city["place"], "ordinary": True,
                          "stories": [{k: wrong[k] for k in ("body", "claims")}]}],
              "leads": [], "notes": "one story"}
    assert any("'1872' isn't among the claims' values" in p for p in task_cli.problems(document, result))


def test_audits_must_decide(database, city, monkeypatch):
    monkeypatch.setenv("PSST_DATABASE_URL_WORKER", database.url("worker"))
    document = {"type": "audit", "data": {}, "result_schema": {"type": "object"}}
    found = task_cli.problems(document, {"verdicts": [{"claim": "cl_x", "verdict": "unclear", "note": "hard"}]})
    assert found == ["claim cl_x: decide; 'unclear' isn't an option here"]


def test_every_prompt_loads_with_the_shared_instructions():
    for path in sorted(prompts.PROMPTS.glob("[a-z]*.md")):
        prompt = prompts.load(path.stem)
        assert "uv run psst task submit" in prompt.text
        assert "—" not in prompt.text and "–" not in prompt.text


def test_a_guide_revision_sees_the_wikidata_lines_and_the_lead(database, city):
    from tests import sample
    from tests.flow import write_and_check
    guide = write_and_check(database, city, kind="guide")
    with database.connect("admin") as conn:
        item = conn.execute("SELECT item_id FROM psst.revisions WHERE id = %s", (guide,)).fetchone()["item_id"]
        conn.execute("SELECT psst.enqueue(%s, 'revise', 'revise:test', '{\"problems\": [\"fix it\"]}', %s, %s, %s, %s)",
                     (city["admin"], sample.CITY_ID, city["place"], item, guide))
    task = Worker(database, SONNET).lease("revise")
    lookups = files.Lookups(key_facts=lambda place: {"lines": ["built (P571): 1871"]}, lead=lambda place: "A lead.")
    with database.connect("worker") as conn:
        data = files.build(conn, task, lookups)["data"]
    assert data["wikidata"] == {"lines": ["built (P571): 1871"]} and data["encyclopedia_lead"] == "A lead."


def test_the_queue_command_counts_a_citys_tasks(database, city, monkeypatch, capsys):
    import argparse
    from contextlib import contextmanager

    from psst.core import db

    @contextmanager
    def connect(role):
        with database.connect(role) as conn:
            yield conn

    monkeypatch.setattr(db, "connect", connect)
    queue(database, city, "research_cell", "count", task_input={"cell": sample.CELL})
    task_cli.show_queue(argparse.Namespace(city="testville"))
    shown = json.loads(capsys.readouterr().out)
    assert shown["tasks"][f"research_cell ({SONNET})"] == {"queued": 1, "leased": 0, "waiting_for_editor": 0,
                                                            "model": SONNET}
    assert shown["no_open_run_for"] == [f"research_cell ({SONNET})"]  # no Sonnet run is open to take it


def test_a_stopped_system_worker_gives_back_its_task(database, city):
    import pytest
    research(database, city, guide=False)
    system = SystemWorker(lambda: psycopg.connect(database.url("system"), row_factory=psycopg.rows.dict_row),
                          Worker(database, kind="system").token)

    def stopped(conn, task):
        raise SystemExit(0)  # what SIGTERM raises in the middle of a task

    system.handlers["tool_check"] = stopped
    with pytest.raises(SystemExit):
        system.work()
    with database.connect("admin") as conn:
        task = conn.execute("SELECT state FROM psst.tasks WHERE type = 'tool_check'").fetchone()
    assert task["state"] == "queued"


def test_a_long_page_keeps_every_quoted_passage():
    text = "Opening words. " + "filler " * 20000 + "built in 1871 by the engineer Ada Thorne" + " more" * 20000
    start = text.index("built in 1871")
    shown = files.excerpt(text, [(start, start + 40)], window=100)
    assert shown.startswith("Opening words.") and "built in 1871 by the engineer Ada Thorne" in shown
    assert "[...]" in shown and len(shown) < 500
