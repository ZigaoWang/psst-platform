"""Driving content through the task queue in tests: workers that lease and submit, and a sample story with its
claims. Everything here is invented."""

from __future__ import annotations

import json

from psst.checks import runner
from tests import sample

SONNET, HAIKU = "claude-sonnet-5-5", "claude-haiku-5-5"


class Worker:
    def __init__(self, database, model=None, kind="worker"):
        self.database = database
        self.role = "system" if kind == "system" else "worker"
        self.run, self.token = database.start_run(kind, model)

    def lease(self, *types, city=None):
        with self.database.connect(self.role) as conn:
            row = conn.execute("SELECT * FROM psst.lease_task(%s, %s, %s)", (self.token, list(types), city)).fetchone()
        return row

    def submit(self, task, result):
        with self.database.connect(self.role) as conn:
            return conn.execute("SELECT psst.submit_task(%s, %s, %s, 'test') AS r",
                                (self.token, task["id"], json.dumps(result))).fetchone()["r"]

    def tool_check(self):
        task = self.lease("tool_check")
        assert task, "no tool check queued"
        with self.database.connect("system") as conn:
            result = runner.run(conn, self.token, task["revision_id"], task["id"])
        self.submit(task, {"pass": result.ok})
        return result


def setup_city(database):
    """A city with one place and two saved sources: an official record and a newspaper."""
    admin, _ = database.start_run("system")
    with database.connect("admin") as conn:
        place = sample.place(conn, admin)
        record = sample.snapshot(conn, admin)
        paper = sample.snapshot(conn, admin, "Readers at the Mill Lane library sit under the old boiler beams.",
                                "https://news.example.com/library", "press")
    return {"admin": admin, "place": place, "record": record, "paper": paper}


def story_result(city, year="1871"):
    body = sample.story_body() | {
        "short": f"The library on Mill Lane was built in {year} to pump the town's water.",
        "long": ("Ada Thorne designed the pump house, and for eighty years its engines sent water up to the town. "
                 "When they stopped in 1952 the council kept the building and opened it as a library. Readers still "
                 "sit under the boiler beams, and the chimney that once carried the engine smoke rises above the "
                 "reading room, where nobody has lit a fire for decades.")}
    claims = [
        {"text": "The pump house was built in 1871, designed by Ada Thorne.", "kind": "date",
         "values": [{"value": "1871"}, {"value": "Ada Thorne"}],
         "evidence": [{"snapshot": city["record"], "quote": "built in 1871 by the engineer Ada Thorne"}]},
        {"text": "It became a library in 1952.", "kind": "event", "values": [{"value": "1952"}],
         "evidence": [{"snapshot": city["record"], "quote": "until 1952, when it was turned into a library"}]},
        {"text": "Readers sit under the old boiler beams.", "kind": "attribute", "values": [],
         "evidence": [{"snapshot": city["paper"], "quote": "sit under the old boiler beams"}]},
    ]
    return {"body": body, "claims": claims, "rulebook": sample.RULEBOOK, "reason": "first draft"}


def queue_story(database, city, n=0):
    with database.connect("admin") as conn:
        return conn.execute("SELECT psst.enqueue(%s, 'write_story', %s, '{}', %s, %s, NULL, NULL) AS id",
                            (city["admin"], f"write_story:test:{n}", sample.CITY_ID, city["place"])).fetchone()["id"]


def claim_ids(database, revision):
    with database.connect("admin") as conn:
        return [r["id"] for r in conn.execute("SELECT id FROM psst.claims WHERE revision_id = %s ORDER BY n",
                                              (revision,))]


def item_state(database, revision):
    with database.connect("admin") as conn:
        return conn.execute("SELECT i.state FROM psst.items i JOIN psst.revisions r ON r.item_id = i.id "
                            "WHERE r.id = %s", (revision,)).fetchone()["state"]


def verdicts(ids, verdict="supported"):
    return {"verdicts": [{"claim": c, "verdict": verdict, "note": "the passage says this"} for c in ids]}


def write_and_check(database, city, n=0, writer=None, system=None):
    """Write a story through the queue and take it through every check to acceptance."""
    queue_story(database, city, n)
    writer = writer or Worker(database, SONNET)
    system = system or Worker(database, kind="system")
    revision = writer.submit(writer.lease("write_story"), story_result(city))["revision"]
    assert system.tool_check().ok
    ids = claim_ids(database, revision)
    for task_type in ("check_claims_a", "check_claims_b"):
        checker = Worker(database, HAIKU)
        checker.submit(checker.lease(task_type), verdicts(ids))
    checker = Worker(database, HAIKU)
    checker.submit(checker.lease("check_item"), {"verdict": "pass", "note": "nothing beyond the claims",
                                                 "untraced": []})
    return revision
