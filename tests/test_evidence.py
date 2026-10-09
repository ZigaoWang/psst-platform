"""Snapshots come only from the fetch service, and a stored story with a wrong year or a missing passage is sent
back by the tool checks alone (design.md, section 19, M2). Pages and records are invented."""

from __future__ import annotations

import json

import psycopg
import pytest

from psst.checks import runner
from psst.evidence.fetch import Page
from psst.services.fetch_service import FetchService, RequestError
from tests import sample

PAGES = {
    "https://records.example.org/pump-house": sample.SNAPSHOT_TEXT,
    "https://news.example.com/pump-house": "Staff at the Mill Lane library say readers still sit under the old "
                                           "boiler beams of the pump house.",
    "https://en.wikipedia.org/wiki/Old_Pump_House": "The Old Pump House is a former pumping station.",
}


class FakeReader:
    def read(self, url: str, archive: bool = False) -> Page:
        text = PAGES.get(url.rstrip("/"))
        return Page(url, 200 if text else 404, "", text or "", note=None if text else "not found")


@pytest.fixture
def service(database):
    _, system_token = database.start_run("system")

    def connect():
        return psycopg.connect(database.url("system"), row_factory=psycopg.rows.dict_row)

    return FetchService(connect, system_token, FakeReader())


def read(service, token, url, kind="official_record"):
    return service.read({"token": token, "url": url, "title": "A page", "publisher": "A publisher", "kind": kind,
                         "language": "en"})


def test_reading_stores_one_snapshot_per_distinct_text(database, service):
    _, token = database.start_run("worker", "claude-sonnet-5-5")
    first = read(service, token, "https://records.example.org/pump-house")
    again = read(service, token, "https://records.example.org/pump-house/")
    assert first["new"] and not again["new"]
    assert first["snapshot"] == again["snapshot"] and first["source"] == again["source"]


def test_reference_works_are_always_reference(database, service):
    _, token = database.start_run("worker", "claude-sonnet-5-5")
    result = read(service, token, "https://en.wikipedia.org/wiki/Old_Pump_House", kind="official_record")
    assert result["kind"] == "reference"


def test_reading_needs_an_open_run(database, service):
    with pytest.raises(psycopg.errors.InvalidAuthorizationSpecification):
        read(service, "not-a-token", "https://records.example.org/pump-house")


@pytest.mark.parametrize("url", ["http://records.example.org/pump-house", "https://www.google.com/search?q=pump"])
def test_some_addresses_are_never_sources(database, service, url):
    _, token = database.start_run("worker", "claude-sonnet-5-5")
    with pytest.raises(RequestError):
        read(service, token, url)


def test_a_worker_cannot_store_a_snapshot_itself(database):
    _, token = database.start_run("worker", "claude-sonnet-5-5")
    with database.connect("worker") as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("SELECT * FROM psst.record_snapshot(%s, %s, 'https://a.example', 'a.example', 't', 'p', "
                     "'press', 'en', 200, 'live', 'https://a.example', '', 'invented text')", (token, token))


def submit(database, service, story_changes=None, claim_changes=None):
    """A story stored through create_revision, citing snapshots the service saved."""
    writer, token = database.start_run("worker", "claude-sonnet-5-5")
    record = read(service, token, "https://records.example.org/pump-house")["snapshot"]
    paper = read(service, token, "https://news.example.com/pump-house", kind="press")["snapshot"]
    body = sample.story_body() | {
        "short": "The library on Mill Lane was built in 1871 to pump the town's water.",
        "long": ("Ada Thorne designed the pump house in 1871, and for eighty years its engines sent water up to the "
                 "town. When they stopped in 1952 the council kept the building and opened it as a library. Readers "
                 "still sit under the boiler beams, and the chimney that once carried the engine smoke rises above "
                 "the reading room, where nobody has lit a fire for decades.")} | (story_changes or {})
    claims = [
        {"text": "Ada Thorne designed the pump house, built in 1871.", "kind": "date",
         "values": [{"value": "1871"}, {"value": "Ada Thorne"}],
         "evidence": [{"snapshot": record, "quote": "built in 1871 by the engineer Ada Thorne"}]},
        {"text": "It became a library in 1952.", "kind": "event", "values": [{"value": "1952"}],
         "evidence": [{"snapshot": record, "quote": "until 1952, when it was turned into a library"}]},
        {"text": "Readers sit under the old boiler beams.", "kind": "attribute", "values": [],
         "evidence": [{"snapshot": paper, "quote": "readers still sit under the old boiler beams"}]},
    ]
    for n, change in (claim_changes or {}).items():
        for proof in change.get("evidence", []):
            proof["snapshot"] = proof["snapshot"] or record
        claims[n].update(change)
    with database.connect("admin") as conn:
        place = sample.place(conn, writer)
        revision = conn.execute(
            "SELECT psst.create_revision(%s, NULL, NULL, 'story', %s, NULL, NULL, NULL, 'en', %s, %s, %s, 'written') "
            "AS r", (writer, place, json.dumps(body), json.dumps(claims), sample.RULEBOOK)).fetchone()["r"]
    return revision


def tool_check_and_settle(database, revision):
    system, system_token = database.start_run("system")
    with database.connect("system") as conn:
        result = runner.run(conn, system_token, revision)
    with database.connect("admin") as conn:
        outcome = conn.execute("SELECT psst.settle(%s, NULL, %s) AS r", (system, revision)).fetchone()["r"]
        state = conn.execute("SELECT i.state FROM psst.items i JOIN psst.revisions r ON r.item_id = i.id "
                             "WHERE r.id = %s", (revision,)).fetchone()["state"]
    return result, outcome, state


def test_a_sound_story_passes_the_tool_check_and_waits_for_claim_checks(database, service):
    result, outcome, state = tool_check_and_settle(database, submit(database, service))
    assert result.ok, result.report.refusals
    assert outcome == {"outcome": "wait"} and state == "checking"


def test_a_wrong_year_is_sent_back_by_tools_alone(database, service):
    revision = submit(database, service, story_changes={
        "short": "The library on Mill Lane was built in 1872 to pump the town's water."})
    result, outcome, state = tool_check_and_settle(database, revision)
    assert outcome["outcome"] == "revise" and state == "draft"
    assert any("'1872' isn't among the claims' values" in r for r in result.report.refusals)


def test_a_passage_the_source_never_said_is_sent_back_by_tools_alone(database, service):
    revision = submit(database, service, claim_changes={1: {"evidence": [
        {"snapshot": None, "quote": "until 1952, when it was turned into a lending library"}]}})
    result, outcome, state = tool_check_and_settle(database, revision)
    assert outcome["outcome"] == "revise" and state == "draft"
    assert any("the quote isn't in snapshot" in r for r in result.report.refusals)
