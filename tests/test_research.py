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
        found = place_problems(conn, "place 0", mill, [])
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
        conn.execute("""UPDATE psst.settings SET value = '{"testville": 1}' WHERE key = 'harness.city_budgets_usd'""")
        conn.execute("UPDATE psst.settings SET value = 'null' WHERE key = 'routing.research_writer'")
    worker = Worker(database, rotation)
    task = worker.lease("research_cell")
    with database.connect("worker") as conn:
        document = files.build(conn, task)
    first, second = (lead["lead"] for lead in document["data"]["leads"])
    place = result_for(database, document)["places"][0]
    place["stories"][0]["body"] |= {"tier": "map", "form": "story"}
    written = []

    claims = place["stories"][0]["claims"]
    facts = [{"id": f"f{n}"} | c for n, c in enumerate(claims + claims[:1], 1)]
    from psst.harness import research as harness_research
    passages = [{"snapshot": e["snapshot"], "kind": "official_record", "url": "https://records.example.org/mill",
                 "text": e["quote"]} for c in claims for e in c["evidence"]]
    monkeypatch.setattr(harness_research, "gather", lambda executor, lead: passages)
    identity = {k: place[k] for k in ("wikidata", "name", "kind", "size", "ordinary")}

    def chat(model, messages, tools=None, max_tokens=4000, json_only=False, timeout=300, reasoning=None):
        if "Triage a cell's leads" in messages[0]["content"]:
            answer = {"decisions": [{"lead": first, "action": "write", "form": "story", "tier": "map",
                                     "angle": "the wheel pit under the grate"},
                                    {"lead": second, "action": "skip", "reason": "an office block, nothing more"}],
                      "notes": "One place worth writing."}
        elif "Pick the evidence for one place" in messages[0]["content"]:
            answer = {"place": identity, "facts": facts}
        else:
            written.append(model)
            answer = {"stories": [{"body": place["stories"][0]["body"], "facts": [f["id"] for f in facts]}],
                      "guide": {"body": place["guide"]["body"], "facts": ["f1"]}}
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


def test_a_failing_chore_does_not_stop_the_system_worker(database, city, monkeypatch):
    system = SystemWorker(lambda: psycopg.connect(database.url("system"), row_factory=psycopg.rows.dict_row),
                          city.token)

    def broken():
        raise psycopg.errors.ForeignKeyViolation("an invented failure")
    broken.__name__ = "fill_hexagons"
    monkeypatch.setattr(system, "fill_hexagons", broken)
    system.work(once=True)  # returns instead of raising
    assert system._hexagons_filled > 0


def test_places_outside_the_platforms_cities_get_no_hexagon(database, city):
    with database.connect("admin") as conn:
        place = sample.place(conn, city.run)
        conn.execute("UPDATE psst.places SET city_id = (SELECT id FROM psst.areas WHERE id NOT IN "
                     "(SELECT id FROM psst.cities) LIMIT 1) WHERE id = %s", (place,))
    SystemWorker(lambda: psycopg.connect(database.url("system"), row_factory=psycopg.rows.dict_row),
                 city.token).fill_hexagons()
    with database.connect("admin") as conn:
        assert conn.execute("SELECT h3_r9 FROM psst.places WHERE id = %s", (place,)).fetchone()["h3_r9"] is None


def test_a_leads_official_record_is_gathered_from_its_wikidata_item(monkeypatch):
    from psst.harness import research as harness_research
    monkeypatch.setattr(harness_research.http, "wikidata_entities", lambda qids, props: {
        "Q900010": {"claims": {"P1216": [{"mainsnak": {"datavalue": {"value": "1000001"}}}]}}})
    found = harness_research.records("Q900010")
    assert found == [{"url": "https://historicengland.org.uk/listing/the-list/list-entry/1000001",
                      "title": "National Heritage List for England entry 1000001", "publisher": "Historic England",
                      "kind": "official_record", "language": "en"}]


def test_a_lead_without_the_evidence_for_a_story_is_skipped_with_the_reason(database, city, monkeypatch):
    from psst.harness import executor as harness
    from psst.harness import providers
    for role in ("worker", "system"):
        monkeypatch.setenv(f"PSST_DATABASE_URL_{role.upper()}", database.url(role))
    model = "openrouter:test/writer"
    with database.connect("admin") as conn:
        conn.execute("UPDATE psst.settings SET value = %s WHERE key IN ('routing.research_cell', "
                     "'routing.research_cell_dense')", (json.dumps(model),))
        conn.execute("""UPDATE psst.settings SET value = '{"testville": 1}' WHERE key = 'harness.city_budgets_usd'""")
    worker = Worker(database, model)
    task = worker.lease("research_cell")
    with database.connect("worker") as conn:
        document = files.build(conn, task)
    first, second = (lead["lead"] for lead in document["data"]["leads"])
    from psst.harness import research as harness_research
    monkeypatch.setattr(harness_research, "gather", lambda executor, lead: [
        {"snapshot": "sn_0000000000", "kind": "community", "url": "https://blog.example.org/mill", "text": "A blog."}])

    def chat(model, messages, tools=None, max_tokens=4000, json_only=False, timeout=300, reasoning=None):
        if "Triage a cell's leads" in messages[0]["content"]:
            answer = {"decisions": [{"lead": first, "action": "write", "form": "story", "tier": "map", "angle": "x"},
                                    {"lead": second, "action": "skip", "reason": "an office block, nothing more"}]}
        else:
            answer = {"skip": "only one blog repeats the story and nothing marks the spot"}
        return providers.Reply(text=json.dumps(answer), cost_usd=0.001)
    monkeypatch.setattr(providers, "chat", chat)
    harness.Executor(worker.token, model).run(dict(task))
    with database.connect("admin") as conn:
        lead = conn.execute("SELECT status, reason FROM psst.leads WHERE id = %s", (first,)).fetchone()
    assert lead["status"] == "skipped" and "only one blog" in lead["reason"]


def test_leads_with_an_official_record_are_marked_for_triage(monkeypatch):
    from psst.harness import research as harness_research
    monkeypatch.setattr(harness_research.http, "wikidata_entities", lambda qids, props: {
        "Q900010": {"claims": {"P1216": [{"mainsnak": {"datavalue": {"value": "1000001"}}}]}}, "Q900011": {}})
    leads = [{"lead": "ld_a", "wikidata": "Q900010"}, {"lead": "ld_b", "wikidata": "Q900011"}, {"lead": "ld_c"}]
    harness_research.mark_records(leads)
    assert [lead.get("record") for lead in leads] == ["National Heritage List for England entry 1000001", None, None]


def test_a_facts_values_come_from_its_quotes():
    from psst.harness import research as harness_research
    fact = {"values": [{"value": "around 1800"}], "evidence": [
        {"snapshot": "sn_1", "quote": "House, c.1800, No.33 Peckham Road, listed at Grade: II in 1954"}]}
    values = [v["value"] for v in harness_research.values_in(fact)]
    assert values == ["1800", "33", "1954", "House", "No", "Peckham Road", "Grade"]


def test_a_verified_fact_the_writer_forgot_to_name_is_attached():
    from psst.harness import research as harness_research
    facts = {"f1": {"text": "The mill closed in 1890.", "kind": "date", "values": [{"value": "1890"}],
                    "evidence": [{"snapshot": "sn_1", "quote": "closed in 1890"}]},
             "f2": {"text": "It was rebuilt in 1902.", "kind": "date", "values": [{"value": "1902"}],
                    "evidence": [{"snapshot": "sn_2", "quote": "rebuilt in 1902"}]}}
    answer = {"stories": [{"body": {"short": "The mill closed in 1890 and was rebuilt in 1902."}, "facts": ["f1"]}]}
    built = harness_research.assemble({"existing": "pl_x", "ordinary": True}, answer, facts)
    assert [c["text"] for c in built["stories"][0]["claims"]] == ["The mill closed in 1890.", "It was rebuilt in 1902."]


def test_a_fact_resting_only_on_a_reference_work_is_dropped(database, city):
    from psst.harness import research as harness_research
    with database.connect("admin") as conn:
        wiki = _snapshot(conn, "The Old Mill on River Lane closed in 1890 after a flood.",
                         "https://en.wikipedia.org/wiki/Old_Mill_River_Lane", "reference")
        record = _snapshot(conn, MILL, "https://records.example.org/mill", "official_record")
    with database.connect("worker") as conn:
        assert harness_research.reference_only(conn, {"evidence": [{"snapshot": wiki, "quote": "closed in 1890"}]})
        assert not harness_research.reference_only(conn, {"evidence": [{"snapshot": wiki, "quote": "closed"},
                                                                       {"snapshot": record, "quote": "closed"}]})


def test_items_with_an_official_record_become_leads(monkeypatch):
    payload = {"results": {"bindings": [
        {"item": {"value": "http://www.wikidata.org/entity/Q900020"},
         "itemLabel": {"value": "Invented Drinking Fountain"},
         "coord": {"value": "Point(-0.05 51.5)"}, "record": {"value": "1000002"}},
        {"item": {"value": "http://www.wikidata.org/entity/Q900021"}, "itemLabel": {"value": "Q900021"},
         "coord": {"value": "Point(-0.06 51.5)"}, "record": {"value": "1000003"}}]}}
    monkeypatch.setattr(leads.http, "get_json", lambda url, attempts=3: payload)
    found = leads.record_items("P1216", 51.4, -0.1, 51.6, 0.0)
    assert found == [{"wikidata": "Q900020", "name": "Invented Drinking Fountain", "lat": 51.5, "lon": -0.05,
                      "record": "1000002"}]  # an item with no name is left out


def test_gathering_follows_official_links_and_keeps_the_paragraphs_that_name_the_place(monkeypatch):
    from psst.harness import research as harness_research
    asked = []

    def read_all(executor, requests):
        asked.append([r["url"] for r in requests])
        if requests and "wikipedia" in requests[0]["url"]:
            return [{"snapshot": "sn_1", "kind": "reference", "url": requests[0]["url"],
                     "text": "Unrelated opening.\nThe Old Mill closed in 1890.\n" + "More unrelated text.\n" * 400,
                     "links": [{"text": "list entry", "url": "https://historicengland.org.uk/listing/1000001"},
                               {"text": "a blog", "url": "https://blog.example.org/mill"}]}]
        return [{"snapshot": "sn_2", "kind": "official_record", "url": r["url"], "text": "Old Mill, listed 1972.",
                 "links": []} for r in requests]
    monkeypatch.setattr(harness_research, "read_all", read_all)
    monkeypatch.setattr(harness_research, "records", lambda qid, entities=None: [])
    pages = harness_research.gather(None, {"name": "Old Mill", "url": "https://en.wikipedia.org/wiki/Old_Mill"})
    assert asked[1] == ["https://historicengland.org.uk/listing/1000001",
                        "https://blog.example.org/mill"]  # the record first, then the others
    assert "The Old Mill closed in 1890." in pages[0]["text"] and "More unrelated" not in pages[0]["text"]


def test_a_record_lead_is_stored(database, city):
    with database.connect("system") as conn:
        conn.execute("SELECT psst.record_leads(%s, %s, %s)", (city.token, sample.CELL, json.dumps([
            {"key": "Q900030", "origin": "record", "name": "Invented Kiosk", "wikidata": "Q900030",
             "url": "https://records.example.org/kiosk", "what": "list entry 1000004"}])))
    with database.connect("admin") as conn:
        stored = conn.execute("SELECT origin FROM psst.leads WHERE name = 'Invented Kiosk'").fetchone()
    assert stored["origin"] == "record"


def test_british_spellings_take_their_us_form_before_checking():
    from psst.harness import research as harness_research
    place = {"stories": [{"body": {"long": "A house of two storeys, its colour unchanged.", "tags": []}}],
             "guide": {"body": {"about": "Three storey houses."}}}
    harness_research.us_spelling(place)
    assert place["stories"][0]["body"]["long"] == "A house of two stories, its color unchanged."
    assert place["guide"]["body"]["about"] == "Three story houses."


def test_a_map_story_may_rest_on_its_record_alone_and_a_plain_record_makes_a_guide(database, city):
    from psst.harness import research as harness_research
    with database.connect("admin") as conn:
        record = _snapshot(conn, MILL, "https://historicengland.org.uk/listing/1000001", "official_record")
    with database.connect("worker") as conn:
        facts = [{"id": f"f{n}", "values": [], "evidence": [{"snapshot": record, "quote": q}]}
                 for n, q in enumerate(["closed in 1890", "its wheel pit survives", "the millstream still runs"], 1)]
        assert harness_research.verify(conn, facts) == []
        assert harness_research.verify(conn, facts, "guide") == []


def test_a_cell_swept_this_week_is_queued_without_sweeping_again(database, city, monkeypatch):
    with database.connect("admin") as conn:
        conn.execute("UPDATE psst.research_cells SET swept_at = now()")

    def no_sweep(conn, cell, country):
        raise AssertionError("swept again")
    monkeypatch.setattr(research.leads, "sweep", no_sweep)
    with database.connect("system") as conn:
        conn.autocommit = False
        assert research.queue(conn, city.token, "testville", 1)["queued"] == 1


def test_a_cell_whose_research_failed_is_opened_and_queued_again(database, city):
    with database.connect("admin") as conn:
        task = conn.execute("SELECT id, input ->> 'cell' AS cell FROM psst.tasks WHERE type = 'research_cell' "
                            "ORDER BY id LIMIT 1").fetchone()
        conn.execute("UPDATE psst.tasks SET state = 'failed' WHERE id = %s", (task["id"],))
        assert conn.execute("SELECT state FROM psst.research_cells WHERE cell = %s",
                            (task["cell"],)).fetchone()["state"] == "open"
    with database.connect("system") as conn:
        assert conn.execute("SELECT psst.queue_research(%s, %s) AS n",
                            (city.token, json.dumps([{"cell": task["cell"], "priority": 5}]))).fetchone()["n"] == 1
    with database.connect("admin") as conn:
        again = conn.execute("SELECT state, attempts FROM psst.tasks WHERE id = %s", (task["id"],)).fetchone()
    assert again["state"] == "queued" and again["attempts"] == 0


def test_one_named_cell_can_be_queued(database, city, monkeypatch):
    with database.connect("admin") as conn:
        cell = conn.execute("SELECT cell FROM psst.research_cells WHERE state = 'open' ORDER BY cell DESC LIMIT 1"
                            ).fetchone()["cell"]
        conn.execute("UPDATE psst.research_cells SET swept_at = now()")
    with database.connect("system") as conn:
        conn.autocommit = False
        assert research.queue(conn, city.token, "testville", 10, [cell])["queued"] == 1
    with database.connect("admin") as conn:
        assert conn.execute("SELECT state FROM psst.research_cells WHERE cell = %s", (cell,)).fetchone()["state"] \
            == "queued"


def test_a_records_shorthand_gives_the_values_the_prose_will_use():
    from psst.harness import research as harness_research
    values = harness_research.values_in({"evidence": [{"quote": "rebuilt in the late C16, restored in 1907-8"}]})
    assert values == [{"value": "16th", "source_form": "C16"}, {"value": "1907"},
                      {"value": "1908", "source_form": "1907-8"}]


def test_a_fact_saying_more_than_its_quotes_is_dropped():
    from psst.harness import research as harness_research
    fact = {"text": "It was listed in 1954 and restored in 1908.",
            "evidence": [{"quote": "restored in 1907-8"}]}
    fact["values"] = harness_research.values_in(fact)
    assert harness_research.unquoted(fact)
    fact["text"] = "It was restored in 1908, in the late 16th century style."
    fact["evidence"].append({"quote": "in the style of the late C16"})
    fact["values"] = harness_research.values_in(fact)
    assert not harness_research.unquoted(fact)


def test_a_pass_offers_the_previous_apps_places_first(database, city):
    with database.connect("admin") as conn:
        cell = conn.execute("SELECT input ->> 'cell' AS c FROM psst.tasks WHERE type = 'research_cell' LIMIT 1"
                            ).fetchone()["c"]
    with database.connect("system") as conn:
        conn.execute("SELECT psst.record_leads(%s, %s, %s)", (city.token, cell, json.dumps(
            [{"key": "legacy:old-pump", "origin": "legacy", "name": "Old Pump", "legacy": LEGACY_ID}])))
    with database.connect("worker") as conn:
        leads = files.research_brief(conn, cell)["leads"]
    assert leads[0]["name"] == "Old Pump" and leads[0]["origin"] == "legacy"


def test_a_known_place_without_stories_is_written_and_waits_beyond_the_pass():
    from psst.harness import research as harness_research
    decisions = [{"lead": "ld_a", "action": "known", "existing": "pl_a", "reason": "no stories yet"},
                 {"lead": "ld_b", "action": "known", "existing": "pl_b", "reason": "no stories yet"},
                 {"lead": "ld_c", "action": "known", "existing": "pl_c", "reason": "has two"}]
    harness_research.settle_storyless(decisions, {"pl_a", "pl_b"}, {}, 1)
    assert [d["action"] for d in decisions] == ["write", "later", "known"]


def test_a_decade_stays_whole_as_a_value():
    from psst.harness import research as harness_research
    assert {"value": "1880s"} in harness_research.values_in({"evidence": [{"quote": "remodelled in the 1880s"}]})


def test_a_similar_name_nearby_is_a_different_place_when_its_wikidata_item_differs(database, city, monkeypatch):
    from psst.places import resolve
    with database.connect("admin") as conn:
        sample.place(conn, city.run, "Q900001")
        other = sample.place(conn, city.run, "Q900002")
        conn.execute("UPDATE psst.places SET state = 'pending' WHERE id = %s", (other,))
    monkeypatch.setattr(coords, "resolve", lambda places: {
        p["id"]: coords.Position(51.5, -0.05, "wikidata", p["wikidata"]) for p in places})
    monkeypatch.setattr(names, "osm_tags", lambda refs: {})
    monkeypatch.setattr("psst.places.resolve.http.wikidata_entities", lambda qids, props: {})
    with database.connect("system") as conn:
        assert resolve.resolve(conn, city.token, [other])["active"] == 1
