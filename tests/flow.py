"""Driving content through the task queue in tests: workers that lease and submit, and a sample story with its
claims. Everything here is invented."""

from __future__ import annotations

import gzip
import itertools
import json

from psst.checks import runner
from psst.publish.run import publish
from tests import sample

SONNET, HAIKU = "claude-sonnet-5-5", "claude-haiku-5-5"
SESSIONS = itertools.count()  # each research session is its own task


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
        conn.execute("UPDATE psst.settings SET value = 'true' WHERE key = 'gate.open'")  # calibrated in test_gate
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
         "values": [{"value": "1871"}, {"value": "Ada Thorne"}, {"value": "Mill Lane"}],
         "evidence": [{"snapshot": city["record"],
                       "quote": "on Mill Lane was built in 1871 by the engineer Ada Thorne"}]},
        {"text": "It became a library in 1952.", "kind": "event", "values": [{"value": "1952"}],
         "evidence": [{"snapshot": city["record"], "quote": "until 1952, when it was turned into a library"}]},
        {"text": "Readers sit under the old boiler beams.", "kind": "attribute", "values": [],
         "evidence": [{"snapshot": city["paper"], "quote": "sit under the old boiler beams"},
                      {"snapshot": city["record"], "quote": "The boiler beams still cross the reading room"}]},
    ]
    return {"body": body, "claims": claims, "rulebook": sample.RULEBOOK, "reason": "first draft"}


def guide_result(city):
    body = {"identifier": "Former pumping station, 1871, by Ada Thorne",
            "about": "A former pumping station on Mill Lane, designed by the engineer Ada Thorne and finished in 1871. "
                     "It supplied the town's water until 1952, when it became a library.",
            "key_facts": [{"property": "P571", "value": "1871", "claim": 1}]}
    claims = story_result(city)["claims"][:2]
    return {"body": body, "claims": claims, "rulebook": sample.RULEBOOK, "reason": "first draft"}


def queue(database, city, task_type, n=0, place=None, task_input=None):
    with database.connect("admin") as conn:
        return conn.execute("SELECT psst.enqueue(%s, %s, %s, %s, %s, %s, NULL, NULL) AS id",
                            (city["admin"], task_type, f"{task_type}:test:{n}", json.dumps(task_input or {}),
                             sample.CITY_ID, place)).fetchone()["id"]


def research(database, city, stories=1, guide=True, place=None, n=0, writer=None, story=None):
    """A research session writes stories (and guide information) for a place. Returns the revisions, stories
    first."""
    queue(database, city, "research_cell", f"{n}:{next(SESSIONS)}", task_input={"cell": sample.CELL})
    writer = writer or Worker(database, SONNET)
    task = writer.lease("research_cell")
    assert task, "no research task"
    entry = {"existing": place or city["place"], "ordinary": True,
             "stories": [story or story_result(city) for _ in range(stories)]}
    if guide:
        entry["guide"] = guide_result(city)
    with database.connect("worker") as conn:
        conn.execute("SELECT psst.submit_research(%s, %s, %s, 'test')", (writer.token, task["id"], json.dumps(
            {"places": [entry], "leads": [], "notes": "covered the place", "rulebook": sample.RULEBOOK})))
        return [r["id"] for r in conn.execute("""
            SELECT r.id FROM psst.revisions r JOIN psst.items i ON i.id = r.item_id
            WHERE r.created_by_task = %s ORDER BY i.type DESC, r.id""", (task["id"],))]


def tool_checks(database, system=None):
    """Run every queued tool check, as the system worker does."""
    system = system or Worker(database, kind="system")
    results = []
    while (task := system.lease("tool_check")) is not None:
        with database.connect("system") as conn:
            result = runner.run(conn, system.token, task["revision_id"], task["id"])
        system.submit(task, {"pass": result.ok})
        results.append(result)
    with database.connect("system") as conn:
        conn.execute("SELECT psst.plan_reviews(%s)", (system.token,))  # the worker batches waiting reviews
    return results


def approve(revision):
    return {"mark": "good", "reason": "the records say this, and it is worth telling"}


def review(database, decide=approve, reviewer=None):
    """Lease the next review and decide every item in it."""
    reviewer = reviewer or Worker(database, SONNET)
    task = reviewer.lease("review")
    assert task, "no review queued"
    decisions = [{"revision": r, "fix": None} | decide(r) for r in task["input"]["revisions"]]
    return reviewer.submit(task, {"decisions": decisions, "notes": "reviewed the batch", "rulebook": sample.RULEBOOK})


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


def write_and_check(database, city, n=0, kind="story", place=None):
    """Research a story or a guide for a place and take it through the tool checks and review to acceptance."""
    revisions = research(database, city, stories=1 if kind == "story" else 0, guide=kind == "guide", place=place, n=n)
    assert all(r.ok for r in tool_checks(database))
    review(database)
    return revisions[0]


def audit_everything(database, verdict="supported"):
    """Plan audits for everything accepted and pass (or fail) every sampled revision."""
    system = Worker(database, kind="system")
    with database.connect("system") as conn:
        conn.execute("SELECT psst.plan_audits(%s, true)", (system.token,))
    while True:
        auditor = Worker(database, SONNET)
        task = auditor.lease("audit")
        if task is None:
            return
        auditor.submit(task, verdicts(claim_ids(database, task["revision_id"]), verdict)
                       | {"item": {"verdict": "pass", "note": "agrees with the claims"}})


def run_publish(database, site, **options):
    with database.connect("publisher") as conn:
        token = conn.execute("SELECT * FROM psst.start_run('publisher', 'test')").fetchone()["token"]
    with database.connect("publisher") as conn:
        conn.autocommit = False
        return publish(conn, token, site["channels"], site["url"], site["work"], **options)


def production_city(site):
    production = site["public"] / "content" / "production" / "v2"
    manifest = json.loads((production / "manifest.json").read_text())
    entry = manifest["cities"][0]
    return manifest, json.loads(gzip.decompress((production / entry["file"]).read_bytes()))
