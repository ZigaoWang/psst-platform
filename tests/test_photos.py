"""Photos: a worker chooses a candidate by its key, the system worker reads its record from Commons and makes our
copies, and the photo is checked and published. Commons is replaced by fixed answers; the image is generated."""

from __future__ import annotations

import io
import json

import psycopg
import pytest
from PIL import Image

from psst.photos import commons, importing
from psst.services.system_worker import SystemWorker
from tests import sample
from tests.flow import HAIKU, Worker, audit_everything, production_city, run_publish, write_and_check

KEY = "commons:File:Old Pump House front.jpg"


def record(license_name="CC BY-SA 4.0"):
    return {"key": KEY, "title": "File:Old Pump House front.jpg", "url": "https://upload.example.org/full.jpg",
            "preview": "https://upload.example.org/2400.jpg", "width": 4000, "height": 3000,
            "source_url": "https://commons.wikimedia.org/wiki/File:Old_Pump_House_front.jpg",
            "license": license_name, "license_url": "https://creativecommons.org/licenses/by-sa/4.0",
            "author": "A. Photographer", "author_url": None, "date": "2024-05-01", "description": None,
            "free": commons.is_free(license_name)}


@pytest.fixture
def commons_stub(monkeypatch, tmp_path):
    picture = io.BytesIO()
    Image.new("RGB", (3000, 2000), (120, 90, 60)).save(picture, "JPEG")
    monkeypatch.setattr(importing, "download", lambda url: picture.getvalue())
    monkeypatch.setenv("PSST_IMAGES_DIR", str(tmp_path / "public" / "images"))
    (tmp_path / "public" / "images").mkdir(parents=True)
    state = {"license": "CC BY-SA 4.0"}
    monkeypatch.setattr(commons, "info", lambda titles, preview_width=640: {
        titles[0]: record(state["license"])})
    return state


def choose(database, city):
    with database.connect("admin") as conn:
        conn.execute("SELECT psst.enqueue(%s, 'find_photos', 'find_photos:test', '{}', %s, %s, NULL, NULL)",
                     (city["admin"], sample.CITY_ID, city["place"]))
    worker = Worker(database, HAIKU)
    task = worker.lease("find_photos")
    with database.connect("worker") as conn:
        conn.execute("SELECT psst.submit_photos(%s, %s, %s, 'test')", (worker.token, task["id"], json.dumps({
            "choices": [{"key": KEY, "alt": "A brick pump house with a tall chimney beside a narrow lane.",
                         "focus": [0.5, 0.4], "kind": "photo"}], "notes": "The front, in daylight."})))
    return worker


def system(database, token):
    return SystemWorker(lambda: psycopg.connect(database.url("system"), row_factory=psycopg.rows.dict_row), token)


def test_a_chosen_photo_is_copied_credited_from_commons_and_checked(database, city, commons_stub):
    chooser = choose(database, city)
    runner = system(database, Worker(database, kind="system").token)
    assert runner.step()  # the import
    with database.connect("admin") as conn:
        body = conn.execute("SELECT r.body FROM psst.revisions r JOIN psst.items i ON i.id = r.item_id "
                            "WHERE i.type = 'photo'").fetchone()["body"]
        writer = conn.execute("SELECT created_by_run FROM psst.revisions").fetchone()["created_by_run"]
    assert body["credit"]["author"] == "A. Photographer" and body["full"]["width"] == 1920
    assert writer == chooser.run
    assert runner.step()  # the tool check
    assert chooser.lease("check_photo") is None  # the run that chose it never checks it
    assert Worker(database, HAIKU).lease("check_photo") is not None


def test_a_photo_without_a_free_license_is_refused(database, city, commons_stub):
    commons_stub["license"] = "CC BY-NC 4.0"
    choose(database, city)
    runner = system(database, Worker(database, kind="system").token)
    assert runner.step()
    with database.connect("admin") as conn:
        task = conn.execute("SELECT state, problem FROM psst.tasks WHERE type = 'import_photo'").fetchone()
    assert task["state"] == "queued" and "isn't free" in task["problem"]


def test_published_places_carry_their_photos(database, city, commons_stub, site):
    # Both fixtures use the test's temporary directory, so photos land in the public directory the site serves.
    write_and_check(database, city, kind="story")
    write_and_check(database, city, kind="guide")
    choose(database, city)
    runner = system(database, Worker(database, kind="system").token)
    runner.step()
    runner.step()
    checker = Worker(database, HAIKU)
    checker.submit(checker.lease("check_photo"), {"verdict": "pass", "note": "the brick front and chimney match",
                                                  "untraced": [], "answers": ["yes"] * 5})
    audit_everything(database)
    assert run_publish(database, site).promoted
    image = production_city(site)[1]["places"][0]["images"][0]
    assert image["credit"]["license"] == "CC BY-SA 4.0" and image["full"]["file"].endswith(".jpg")


def test_the_console_queues_photo_searches_for_places_with_stories(database, city):
    write_and_check(database, city, kind="story")
    with database.connect("admin") as conn:
        conn.execute("SELECT psst.console_add_account('editor', 'a long test password')")
    with database.connect("console") as conn:
        session = conn.execute("SELECT psst.console_sign_in('editor', 'a long test password') AS t").fetchone()["t"]
        assert conn.execute("SELECT psst.console_queue_photos(%s, %s, 10) AS n",
                            (session, sample.CITY_ID)).fetchone()["n"] == 1
        assert conn.execute("SELECT psst.console_queue_photos(%s, %s, 10) AS n",
                            (session, sample.CITY_ID)).fetchone()["n"] == 0
