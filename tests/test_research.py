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
from tests.flow import SONNET, Worker, tool_checks

LEGACY_ID = "pl_0123456789"


@pytest.fixture
def city(database, monkeypatch):
    system = Worker(database, kind="system")
    with database.connect("admin") as conn:
        conn.execute("UPDATE psst.settings SET value = 'true' WHERE key = 'gate.open'")  # calibrated in test_gate
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
    worker = Worker(database, SONNET)
    task = worker.lease("research_cell")
    with database.connect("worker") as conn:
        document = files.build(conn, task)
    return worker, task, document


MILL = ("The Old Mill on River Lane closed in 1890, but its wheel pit survives under the iron pavement grate by the "
        "door, where the millstream still runs.")


def result_for(database, document, wikidata="Q900010"):
    """A researcher's result: the Old Mill with one story and its guide, and every lead accounted for."""
    with database.connect("admin") as conn:
        record = _snapshot(conn, MILL, "https://records.example.org/mill", "official_record")
        paper = _snapshot(conn, "Walkers on River Lane can still hear the millstream below the grate.",
                          "https://news.example.com/mill", "press")
    claims = [{"text": "The mill closed in 1890.", "kind": "date", "values": [{"value": "1890"}],
               "evidence": [{"snapshot": record, "quote": "The Old Mill on River Lane closed in 1890"}]},
              {"text": "Its wheel pit survives under the pavement grate by the door.", "kind": "attribute",
               "values": [], "evidence": [{"snapshot": record, "quote": "its wheel pit survives under the iron "
                                                                         "pavement grate by the door"},
                                          {"snapshot": paper, "quote": "can still hear the millstream below the "
                                                                       "grate"}]}]
    story = {"body": sample.story_body() | {
        "headline": "The mill wheel pit under the pavement",
        "short": "Milling on River Lane ended in 1890, yet the wheel pit is still down there under a grate.",
        "long": " ".join(["y"] * 160),
        "look": "Stand at the door and look down through the iron grate into the wheel pit.",
        "category": "hidden"}, "claims": claims}
    guide = {"body": {"identifier": "Former watermill",
                      "about": "A watermill on River Lane that closed in 1890. The pit that held its wheel is still "
                               "below a grate outside, with water flowing through it.",
                      "key_facts": []}, "claims": claims[:1]}
    return {
        "places": [{"wikidata": wikidata, "name": "Old Mill", "kind": "building", "size": "medium", "ordinary": True,
                    "stories": [story], "guide": guide}],
        "leads": [{"lead": lead["lead"], "status": "added" if n == 0 else "skipped", "place": 0,
                   "reason": "an office block with nothing surprising in any source"}
                  for n, lead in enumerate(document["data"]["leads"])],
        "notes": "Covered the mill and the two leads.",
        "rulebook": sample.RULEBOOK,
    }


def _snapshot(conn, text, url, kind):
    found = conn.execute("SELECT n.id FROM psst.snapshots n JOIN psst.sources s ON s.id = n.source_id "
                         "WHERE s.url = %s", (url,)).fetchone()
    if found:
        return found["id"]
    run = conn.execute("SELECT id FROM psst.runs ORDER BY started_at LIMIT 1").fetchone()["id"]
    return sample.snapshot(conn, run, text, url, kind)


def submit_research(database, worker, task, result):
    with database.connect("worker") as conn:
        return conn.execute("SELECT psst.submit_research(%s, %s, %s, 'test') AS r",
                            (worker.token, task["id"], json.dumps(result))).fetchone()["r"]


def test_research_creates_places_stories_and_guides(database, city):
    worker, task, document = lease_research(database)
    assert [lead["name"] for lead in document["data"]["leads"]] == ["Lead 0", "Lead 1"]
    outcome = submit_research(database, worker, task, result_for(database, document))
    assert outcome == {"places": 1, "new_places": 1, "stories": 1, "guides": 1, "leads_open": 0, "guides_skipped": []}
    with database.connect("admin") as conn:
        place = conn.execute("SELECT id, state FROM psst.places WHERE wikidata_id = 'Q900010'").fetchone()
        identity = {r["legacy_id"] for r in conn.execute("SELECT legacy_id FROM psst.place_identity")}
        cell = conn.execute("SELECT state, passes FROM psst.research_cells WHERE cell = %s",
                            (task["input"]["cell"],)).fetchone()
        items = {r["type"]: r["state"] for r in conn.execute("SELECT type, state FROM psst.items")}
        queued = {r["type"] for r in conn.execute("SELECT type FROM psst.tasks WHERE state = 'queued'")}
    assert place == {"id": LEGACY_ID, "state": "pending"}  # the previous id carries over
    assert identity == {LEGACY_ID, "testville/old-mill"}
    assert cell == {"state": "researched", "passes": 1}
    assert items == {"story": "checking", "guide": "checking"}
    assert {"tool_check", "resolve_places"} <= queued


def test_review_waits_until_the_place_is_resolved(database, city, monkeypatch):
    worker, task, document = lease_research(database)
    submit_research(database, worker, task, result_for(database, document))
    assert all(r.ok for r in tool_checks(database))
    assert Worker(database, SONNET).lease("review") is None
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
    assert len(Worker(database, SONNET).lease("review")["input"]["revisions"]) == 2  # the story and its guide


def test_a_place_without_a_coordinate_is_refused_and_its_work_cancelled(database, city, monkeypatch):
    worker, task, document = lease_research(database)
    submit_research(database, worker, task, result_for(database, document, wikidata="Q900099"))
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
    result = result_for(database, document)
    result["leads"] = result["leads"][:1]
    assert any("isn't accounted for" in p for p in research_problems(document["data"], result))
    result = result_for(database, document)
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


def test_a_place_outside_its_city_is_refused(database, city, monkeypatch):
    worker, task, document = lease_research(database)
    submit_research(database, worker, task, result_for(database, document))
    monkeypatch.setattr(coords, "resolve", lambda places: {
        p["id"]: coords.Position(52.9, -1.2, "wikidata", p["wikidata"]) for p in places})  # far outside Testville
    monkeypatch.setattr(names, "osm_tags", lambda refs: {})
    monkeypatch.setattr("psst.places.resolve.http.wikidata_entities", lambda qids, props: {})
    system = SystemWorker(lambda: psycopg.connect(database.url("system"), row_factory=psycopg.rows.dict_row),
                          city.token)
    assert system.step()
    with database.connect("admin") as conn:
        place = conn.execute("SELECT state, state_reason FROM psst.places WHERE id = %s", (LEGACY_ID,)).fetchone()
    assert place == {"state": "refused", "state_reason": "its coordinate is outside the city it was researched for"}


def test_a_second_session_skips_a_guide_the_place_already_has(database, city):
    worker, task, document = lease_research(database)
    submit_research(database, worker, task, result_for(database, document))
    with database.connect("admin") as conn:
        conn.execute("SELECT psst.enqueue(%s, 'research_cell', 'research_cell:again', %s, %s, NULL, NULL, NULL)",
                     (city.run, json.dumps(task["input"]), sample.CITY_ID))
    again, second, document = lease_research(database)
    outcome = submit_research(database, again, second, result_for(database, document))
    assert outcome["guides"] == 0 and outcome["guides_skipped"] == [LEGACY_ID] and outcome["stories"] == 1


def test_a_place_without_a_precise_coordinate_is_caught_before_submitting(monkeypatch):
    from psst.cli.tasks import position_problems
    monkeypatch.setattr(coords, "resolve", lambda places: {
        places[0]["id"]: "Q900098's coordinate is only precise to 0.01 degrees; give the OpenStreetMap element"})
    assert position_problems("place 0", {"name": "Invented Square", "wikidata": "Q900098"}) == [
        "place 0 (Invented Square): Q900098's coordinate is only precise to 0.01 degrees; give the OpenStreetMap "
        "element"]


def submit_place(database, worker, task, place, leads):
    with database.connect("worker") as conn:
        return conn.execute("SELECT psst.submit_research_place(%s, %s, %s, %s, %s, NULL) AS r",
                            (worker.token, task["id"], json.dumps(place), json.dumps(leads),
                             sample.RULEBOOK)).fetchone()["r"]


def test_a_place_is_stored_as_soon_as_it_is_submitted_and_reviewed_with_the_cell(database, city):
    worker, task, document = lease_research(database)
    full = result_for(database, document)
    first, second = (lead["lead"] for lead in document["data"]["leads"])
    with database.connect("admin") as conn:
        conn.execute("UPDATE psst.tasks SET leased_until = now() + interval '1 minute' WHERE id = %s", (task["id"],))
    outcome = submit_place(database, worker, task, full["places"][0], [first])
    assert outcome["new"] is True and outcome["written"] == 2
    tool_checks(database)
    with database.connect("admin") as conn:
        lead = conn.execute("SELECT status, place_id FROM psst.leads WHERE id = %s", (first,)).fetchone()
        lease = conn.execute("SELECT leased_until > now() + interval '1 hour' AS renewed FROM psst.tasks "
                             "WHERE id = %s", (task["id"],)).fetchone()
        reviews = conn.execute("SELECT count(*) AS n FROM psst.tasks WHERE type = 'review'").fetchone()
    assert lead == {"status": "added", "place_id": outcome["place"]} and lease["renewed"]
    assert reviews["n"] == 0  # the cell isn't finished
    final = {"places": [], "leads": [{"lead": second, "status": "skipped", "reason": "an office block, nothing more"}],
             "notes": "One place.", "rulebook": sample.RULEBOOK}
    assert research_problems(document["data"], final, {first}) == []
    assert submit_research(database, worker, task, final)["leads_open"] == 0
    with database.connect("admin") as conn:
        review = conn.execute("SELECT input FROM psst.tasks WHERE type = 'review'").fetchone()
    assert len(review["input"]["revisions"]) == 2


def test_a_stopped_session_hands_its_cell_to_the_next_researcher(database, city):
    worker, task, document = lease_research(database)
    submit_place(database, worker, task, result_for(database, document)["places"][0], [])
    with database.connect("admin") as conn:
        conn.execute("UPDATE psst.tasks SET leased_until = now() - interval '1 minute' WHERE id = %s", (task["id"],))
    resumed = Worker(database, SONNET).lease("research_cell")
    with database.connect("admin") as conn:
        stopped = conn.execute("SELECT ended_at IS NOT NULL AS ended, notes FROM psst.runs WHERE id = %s",
                               (worker.run,)).fetchone()
    assert resumed["id"] == task["id"] and stopped["ended"] and "lease ran out" in stopped["notes"]


def test_a_new_place_that_already_exists_is_caught_before_submitting(database, city):
    from psst.cli.tasks import place_problems
    worker, task, document = lease_research(database)
    mill = result_for(database, document)["places"][0]
    submit_place(database, worker, task, mill, [])
    with database.connect("worker") as conn:
        found = place_problems(conn, "place 0", mill)
    assert len(found) == 1 and "is already" in found[0] and "submit it as existing" in found[0]


def test_places_and_dense_cells_get_density_hexagons(database, city, monkeypatch):
    with database.connect("admin") as conn:
        conn.execute("UPDATE psst.settings SET value = '1' WHERE key = 'research.dense_leads'")
        place = sample.place(conn, city.run)
    system = SystemWorker(lambda: psycopg.connect(database.url("system"), row_factory=psycopg.rows.dict_row),
                          city.token)
    system.fill_hexagons()
    with database.connect("admin") as conn:
        cell = conn.execute("SELECT h3_r9 FROM psst.places WHERE id = %s", (place,)).fetchone()["h3_r9"]
        hexagons = conn.execute("SELECT count(*) AS n, count(*) FILTER (WHERE cell = %s) AS own FROM psst.hexagons",
                                (cell,)).fetchone()
        density = conn.execute("SELECT stories FROM psst.hexagon_density WHERE cell = %s", (cell,)).fetchone()
    assert cell and hexagons["own"] == 1 and hexagons["n"] > 49  # its own, plus every hexagon of the dense cells
    assert density["stories"] == 0


def test_the_harness_researches_a_cell_place_by_place(database, city, monkeypatch):
    from psst.harness import executor as harness
    from psst.harness import providers
    for role in ("worker", "system"):
        monkeypatch.setenv(f"PSST_DATABASE_URL_{role.upper()}", database.url(role))
    monkeypatch.setattr(coords, "resolve", lambda places: {
        p["id"]: coords.Position(51.5, -0.05, "wikidata", p["wikidata"] or "Q900010") for p in places})
    rotation = "rotate:openrouter:test/writer-a+openrouter:test/writer-b"
    with database.connect("admin") as conn:
        conn.execute("UPDATE psst.settings SET value = %s WHERE key IN ('routing.research_cell', "
                     "'routing.research_cell_dense')", (json.dumps(rotation),))
    worker = Worker(database, rotation)
    task = worker.lease("research_cell")
    with database.connect("worker") as conn:
        document = files.build(conn, task)
    first, second = (lead["lead"] for lead in document["data"]["leads"])
    place = result_for(database, document)["places"][0]
    place["stories"][0]["body"] |= {"tier": "map", "form": "story"}
    written = []

    def chat(model, messages, tools=None, max_tokens=4000, json_only=False, timeout=300):
        if "Triage a cell's leads" in messages[0]["content"]:
            answer = {"decisions": [{"lead": first, "action": "write", "form": "story", "tier": "map",
                                     "angle": "the wheel pit under the grate"},
                                    {"lead": second, "action": "skip", "reason": "an office block, nothing more"}],
                      "notes": "One place worth writing."}
        else:
            written.append(model)
            answer = {"place": place, "leads": [first]}
        return providers.Reply(text=json.dumps(answer), cost_usd=0.002)
    monkeypatch.setattr(providers, "chat", chat)
    outcome = harness.Executor(worker.token, rotation).run(dict(task))
    assert outcome["outcome"]["leads_open"] == 0 and written == ["openrouter:test/writer-a"]
    with database.connect("admin") as conn:
        lead = conn.execute("SELECT status FROM psst.leads WHERE id = %s", (first,)).fetchone()
        tied = conn.execute("SELECT count(*) AS n FROM psst.harness_calls WHERE step = 'write' "
                            "AND place_id IS NOT NULL AND model = 'openrouter:test/writer-a'").fetchone()
        state = conn.execute("SELECT state FROM psst.tasks WHERE id = %s", (task["id"],)).fetchone()
    assert lead["status"] == "added" and tied["n"] == 1 and state["state"] == "done"


def test_a_place_with_malformed_leads_is_refused_not_crashed(database, city, monkeypatch):
    from psst.cli import tasks as task_cli
    monkeypatch.setenv("PSST_DATABASE_URL_WORKER", database.url("worker"))
    worker, task, document = lease_research(database)
    place = result_for(database, document)["places"][0]
    with pytest.raises(task_cli.NotSubmitted, match="leads"):
        task_cli.submit_one_place(document, {"place": place, "leads": [{"lead": "ld_x"}]})
