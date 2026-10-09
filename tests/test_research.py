"""Research by cell: a city's cells are planned, the most wanted are queued with their leads, a researcher's result
creates places and writing tasks, and the system worker resolves the places. The network is replaced by fixed
answers; places and names are invented."""

from __future__ import annotations

import json

import psycopg
import pytest

from psst.cli.tasks import research_problems
from psst.places import coords, leads, names, research
from psst.services.system_worker import SystemWorker
from psst.tasks import files
from tests import sample
from tests.flow import HAIKU, SONNET, Worker

LEGACY_ID = "pl_0123456789"


@pytest.fixture
def city(database, monkeypatch):
    system = Worker(database, kind="system")
    with database.connect("admin") as conn:
        sample.city(conn)
        conn.execute("INSERT INTO psst.area_parts (area_id, geom) SELECT id, geom FROM psst.areas WHERE id = %s",
                     (sample.CITY_ID,))
        conn.execute("DELETE FROM psst.cities WHERE id = %s", (sample.CITY_ID,))
        conn.execute("""INSERT INTO psst.legacy_places (id, name, wikidata_id, kind, geom, spot_ids)
                        VALUES (%s, 'Old Mill', 'Q900010', 'building', ST_SetSRID(ST_MakePoint(-0.05, 51.5), 4326),
                                '{testville/old-mill}')""", (LEGACY_ID,))
    with database.connect("system") as conn:
        planned = research.setup_city(conn, system.token, sample.CITY_ID, "testville", [], 1)
    assert planned > 0

    def fake_sweep(conn, cell, country):
        return [{"key": f"Q9000{n}{cell[-6:]}", "origin": "wikipedia", "name": f"Lead {n}", "fame": 30 - n,
                 "wikidata": f"Q9000{n}"} for n in range(2)], []

    monkeypatch.setattr(leads, "sweep", fake_sweep)
    monkeypatch.setattr(research.leads, "sweep", fake_sweep)
    with database.connect("system") as conn:
        conn.autocommit = False
        assert research.queue(conn, system.token, "testville", 2)["queued"] == 2
    return system


def lease_research(database):
    worker = Worker(database, HAIKU)
    task = worker.lease("research_cell")
    with database.connect("worker") as conn:
        document = files.build(conn, task)
    return worker, task, document


def result_for(document, wikidata="Q900010"):
    return {
        "places": [{"wikidata": wikidata, "name": "Old Mill", "kind": "building", "size": "medium", "ordinary": True,
                    "angles": [{"angle": "The mill's wheel pit is still under the pavement grate by the door.",
                                "category": "hidden", "sources": ["https://records.example.org/mill"]}]}],
        "leads": [{"lead": lead["lead"], "status": "added" if n == 0 else "skipped", "place": 0,
                   "reason": "an office block with nothing surprising in any source"}
                  for n, lead in enumerate(document["data"]["leads"])],
        "notes": "Covered the mill and the two leads.",
    }


def submit_research(database, worker, task, result):
    with database.connect("worker") as conn:
        return conn.execute("SELECT psst.submit_research(%s, %s, %s, 'test') AS r",
                            (worker.token, task["id"], json.dumps(result))).fetchone()["r"]


def test_research_creates_places_and_writing_tasks(database, city):
    worker, task, document = lease_research(database)
    assert [lead["name"] for lead in document["data"]["leads"]] == ["Lead 0", "Lead 1"]
    outcome = submit_research(database, worker, task, result_for(document))
    assert outcome == {"places": 1, "new_places": 1, "stories_queued": 1, "leads_open": 0}
    with database.connect("admin") as conn:
        place = conn.execute("SELECT id, state FROM psst.places WHERE wikidata_id = 'Q900010'").fetchone()
        identity = {r["legacy_id"] for r in conn.execute("SELECT legacy_id FROM psst.place_identity")}
        cell = conn.execute("SELECT state, passes FROM psst.research_cells WHERE cell = %s",
                            (task["input"]["cell"],)).fetchone()
        queued = {r["type"] for r in conn.execute("SELECT type FROM psst.tasks WHERE state = 'queued'")}
    assert place == {"id": LEGACY_ID, "state": "pending"}  # the previous id carries over
    assert identity == {LEGACY_ID, "testville/old-mill"}
    assert cell == {"state": "researched", "passes": 1}
    assert {"write_story", "write_guide", "resolve_places"} <= queued


def test_writing_waits_until_the_place_is_resolved(database, city, monkeypatch):
    worker, task, document = lease_research(database)
    submit_research(database, worker, task, result_for(document))
    assert Worker(database, SONNET).lease("write_story") is None
    monkeypatch.setattr(coords, "resolve", lambda places: {
        p["id"]: coords.Position(51.5, -0.05, "wikidata", p["wikidata"]) for p in places})
    monkeypatch.setattr(names, "osm_tags", lambda refs: {})
    monkeypatch.setattr("psst.places.resolve.http.wikidata_entities", lambda qids, props: {
        "Q900010": {"labels": {"zh-hans": {"value": "旧磨坊"}}}})
    system = SystemWorker(lambda: psycopg.connect(database.url("system"), row_factory=psycopg.rows.dict_row),
                          city.token)
    assert system.step()
    with database.connect("admin") as conn:
        place = conn.execute("SELECT state, city_id, h3_r7 FROM psst.places WHERE id = %s", (LEGACY_ID,)).fetchone()
        alt = conn.execute("SELECT name FROM psst.place_names WHERE place_id = %s AND role = 'alt'",
                           (LEGACY_ID,)).fetchone()
    assert place["state"] == "active" and place["city_id"] == sample.CITY_ID and place["h3_r7"]
    assert alt["name"] == "旧磨坊"
    assert Worker(database, SONNET).lease("write_story")["input"]["category"] == "hidden"
    assert Worker(database, HAIKU).lease("write_guide") is not None


def test_a_place_without_a_coordinate_is_refused_and_its_work_cancelled(database, city, monkeypatch):
    worker, task, document = lease_research(database)
    submit_research(database, worker, task, result_for(document, wikidata="Q900099"))
    monkeypatch.setattr(coords, "resolve", lambda places: {p["id"]: "Q900099 has no coordinate on Wikidata"
                                                           for p in places})
    monkeypatch.setattr(names, "osm_tags", lambda refs: {})
    monkeypatch.setattr("psst.places.resolve.http.wikidata_entities", lambda qids, props: {})
    system = SystemWorker(lambda: psycopg.connect(database.url("system"), row_factory=psycopg.rows.dict_row),
                          city.token)
    assert system.step()
    with database.connect("admin") as conn:
        place = conn.execute("SELECT state, state_reason FROM psst.places WHERE wikidata_id = 'Q900099'").fetchone()
        open_writing = conn.execute("SELECT count(*) AS n FROM psst.tasks WHERE type IN ('write_story', "
                                    "'write_guide') AND state = 'queued'").fetchone()["n"]
    assert place == {"state": "refused", "state_reason": "Q900099 has no coordinate on Wikidata"}
    assert open_writing == 0


def test_research_results_account_for_every_lead(database, city):
    _, _, document = lease_research(database)
    result = result_for(document)
    result["leads"] = result["leads"][:1]
    assert any("isn't accounted for" in p for p in research_problems(document["data"], result))
    result = result_for(document)
    result["leads"][1] |= {"status": "later"}
    assert any("is well known" in p for p in research_problems(document["data"], result))


def test_leads_that_are_not_places_are_skipped_by_the_system(database, city):
    with database.connect("system") as conn:
        cell = conn.execute("SELECT cell FROM psst.research_cells WHERE state = 'open' LIMIT 1").fetchone()["cell"]
        conn.execute("SELECT psst.record_leads(%s, %s, %s)", (city.token, cell, json.dumps([
            {"key": "Q9001", "origin": "wikipedia", "name": "Testville Water Company", "wikidata": "Q9001",
             "skip": "not a place to stand in front of: a company"}])))
    with database.connect("admin") as conn:
        lead = conn.execute("SELECT status, reason, decided_by FROM psst.leads WHERE key = 'Q9001'").fetchone()
    assert lead["status"] == "skipped" and lead["reason"].endswith("a company") and lead["decided_by"]


def test_the_console_queues_research_for_the_system_worker(database, city, monkeypatch):
    with database.connect("admin") as conn:
        conn.execute("SELECT psst.console_add_account('editor', 'a long test password')")
    with database.connect("console") as conn:
        session = conn.execute("SELECT psst.console_sign_in('editor', 'a long test password') AS t").fetchone()["t"]
        conn.execute("SELECT psst.console_queue_research(%s, %s, 2)", (session, sample.CITY_ID))
    system = SystemWorker(lambda: psycopg.connect(database.url("system"), row_factory=psycopg.rows.dict_row),
                          city.token)
    assert system.step()
    with database.connect("admin") as conn:
        queued = conn.execute("SELECT count(*) AS n FROM psst.tasks WHERE type = 'research_cell'").fetchone()["n"]
    assert queued == 4  # two from the fixture, two from the console
