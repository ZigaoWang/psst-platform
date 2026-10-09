"""`psst task`: lease the next task as a file, submit a result, or give a task back."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import jsonschema
from psycopg.types.json import Jsonb

from psst import rules
from psst.checks import runner
from psst.core import config, db
from psst.evidence import encyclopedia, wikidata
from psst.photos import commons, importing
from psst.tasks import files

from . import fetching
from .runs import token

WORK = config.ROOT / "work" / "tasks"
WRITING = {"write_trail": "trail"}


def register(groups: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    group = groups.add_parser("task", help="lease, submit, or give back tasks")
    commands = group.add_subparsers(dest="command", required=True, metavar="<task command>")
    lease = commands.add_parser("next", help="lease the next task and write its task file")
    lease.add_argument("--type", action="append", dest="types",
                       help="only this task type (repeatable); by default every type routed to the run's model")
    lease.add_argument("--city", help="only tasks in this city (its slug, such as london)")
    lease.add_argument("--out", type=Path, default=WORK, help="where to write the task file")
    lease.set_defaults(run=lease_next)
    submit = commands.add_parser("submit", help="check a result and submit it")
    submit.add_argument("task_file", type=Path)
    submit.add_argument("result_file", type=Path)
    submit.set_defaults(run=submit_result)
    give_back = commands.add_parser("return", help="give a task back with the reason")
    give_back.add_argument("task_file", type=Path)
    give_back.add_argument("--problem", required=True)
    give_back.set_defaults(run=return_task)
    queue = commands.add_parser("queue", help="count waiting and leased tasks, and items by state, for a city")
    queue.add_argument("--city", required=True, help="the city's slug, such as london")
    queue.set_defaults(run=show_queue)


def _lead(place: dict[str, Any]) -> dict[str, Any] | None:
    def read(request: dict[str, Any]) -> dict[str, Any]:
        return fetching.request({"token": token(), **request})
    try:
        return encyclopedia.lead(place, read)
    except ConnectionError:
        return None


def _key_facts(place: dict[str, Any]) -> dict[str, Any] | None:
    """The key facts the place's Wikidata item gives, to fetch and quote (the fetch service saves the same lines)."""
    if not place.get("wikidata_id"):
        return None
    try:
        item, values = wikidata.fetch(place["wikidata_id"])
    except (LookupError, ConnectionError):
        return None
    return {"url": f"https://www.wikidata.org/wiki/{place['wikidata_id']}",
            "lines": wikidata.render(place["wikidata_id"], item, values, place["kind"], place["size"]).splitlines()}


def _photo_candidates(place: dict[str, Any]) -> list[dict[str, Any]]:
    """Free photos from Commons that may show the place, each with a local preview to look at."""
    folder = WORK.parent / "images" / place["task"]
    folder.mkdir(parents=True, exist_ok=True)
    found = commons.candidates(place["lat"], place["lon"], place.get("wikidata_id"))
    for index, candidate in enumerate(found):
        if candidate.get("preview"):
            try:
                path = folder / f"{index:02d}.jpg"
                path.write_bytes(importing.download(candidate["preview"]))
                candidate["preview_file"] = str(path)
            except (OSError, ValueError):
                candidate["preview_file"] = None
    return found


def _photo_file(body: dict[str, Any]) -> str | None:
    """A local copy of the photo under check, as readers will see it."""
    base = config.get("PSST_PUBLIC_URL")
    if not base:
        return None
    path = WORK.parent / "images" / body["thumb"]["file"]
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_bytes(importing.download(f"{base.rstrip('/')}/images/{body['full']['file']}"))
    except (OSError, ValueError):
        return None
    return str(path)


def show_queue(args: argparse.Namespace) -> int:
    """What is waiting in a city, so whoever starts runs knows which roles are needed."""
    with db.connect("worker") as conn:
        city = conn.execute("SELECT id FROM psst.cities WHERE slug = %s", (args.city,)).fetchone()
        if city is None:
            raise config.ConfigError(f"no city with the slug {args.city!r}")
        tasks = conn.execute("""
            WITH routed AS (
                SELECT t.type, t.state, y.runner,
                       CASE WHEN y.runner = 'worker' THEN psst.task_model(t.type, t.input) END AS model
                FROM psst.tasks t JOIN psst.task_types y ON y.name = t.type
                WHERE t.city_id = %s AND t.state IN ('queued', 'leased', 'failed'))
            SELECT type, model, count(*) FILTER (WHERE state = 'queued') AS queued,
                   count(*) FILTER (WHERE state = 'leased') AS leased,
                   count(*) FILTER (WHERE state = 'failed') AS waiting_for_editor,
                   runner = 'worker' AND NOT EXISTS (
                       SELECT 1 FROM psst.runs r WHERE r.kind = 'worker' AND r.ended_at IS NULL
                         AND r.model = routed.model) AS no_open_run
            FROM routed GROUP BY type, model, runner ORDER BY type, model""", (city["id"],)).fetchall()
        items = conn.execute("""
            SELECT type, state, count(*) AS n FROM psst.items WHERE city_id = %s
            GROUP BY type, state ORDER BY type, state""", (city["id"],)).fetchall()
    counts = ("queued", "leased", "waiting_for_editor", "model")
    waiting = sorted(f"{r['type']} ({r['model']})" for r in tasks if r["queued"] and r["no_open_run"])
    print(json.dumps({"tasks": {r["type"] + (f" ({r['model']})" if r["model"] else ""): {k: r[k] for k in counts}
                                for r in tasks},
                      "items": {f"{r['type']} {r['state']}": r["n"] for r in items},
                      "no_open_run_for": waiting}, indent=2))
    return 0


def lease_next(args: argparse.Namespace) -> int:
    with db.connect("worker") as conn:
        city = None
        if args.city:
            row = conn.execute("SELECT id FROM psst.cities WHERE slug = %s", (args.city,)).fetchone()
            if row is None:
                raise config.ConfigError(f"no city with the slug {args.city!r}")
            city = row["id"]
        types = args.types or [r["name"] for r in conn.execute(
            "SELECT name FROM psst.task_types WHERE runner = 'worker' AND active ORDER BY name")]
        task = conn.execute("SELECT * FROM psst.lease_task(%s, %s, %s)", (token(), types, city)).fetchone()
        if task is None:
            print("no task waiting")
            return 3
        document = files.build(conn, task, files.Lookups(_lead, _key_facts, _photo_candidates, _photo_file))
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"{task['id']}.json"
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2, default=str))
    print(path)
    return 0


def problems(document: dict[str, Any], result: dict[str, Any]) -> list[str]:
    """Everything wrong with a result that can be found before submitting it."""
    found = [f"{'/'.join(map(str, e.path)) or 'result'}: {e.message}"
             for e in jsonschema.Draft202012Validator(document["result_schema"]).iter_errors(result)]
    if found:
        return found
    kind = document["type"]
    if kind == "audit":
        found += [f"claim {v['claim']}: decide; 'unclear' isn't an option here"
                  for v in result.get("verdicts", []) if v["verdict"] == "unclear"]
    if kind == "research_cell":
        found += research_problems(document["data"], result)
        with db.connect("worker") as conn:
            for index, place in enumerate(result["places"]):
                written = [("story", n, s) for n, s in enumerate(place["stories"], 1)]
                written += [("guide", 1, place["guide"])] if place.get("guide") else []
                for written_type, n, item in written:
                    check = runner.preflight(conn, written_type, place.get("existing"), item)
                    found += [f"place {index} {written_type} {n}: {r}" for r in check.report.refusals]
    if kind == "review":
        found += review_problems(document["data"], result)
    if kind == "find_photos":
        room = rules.load().type("photo")["max_per_place"] - len(document["data"]["existing_photos"])
        if len(result["choices"]) > room:
            found.append(f"the place has room for {max(room, 0)} more photos")
    item_type = WRITING.get(kind) or (document["data"].get("type") if kind == "revise" else None)
    if item_type and item_type != "translation":
        place = (document["data"].get("place") or {}).get("id")
        with db.connect("worker") as conn:
            check = runner.preflight(conn, item_type, place, result)
        found += check.report.refusals
    return found


def review_problems(data: dict[str, Any], result: dict[str, Any]) -> list[str]:
    """Every item marked exactly once."""
    items = {i["revision"]: i for i in data["items"]}
    decided = [d["revision"] for d in result["decisions"]]
    found = [f"decide {r} ({items[r]['place']['name'] if items[r]['place'] else r})"
             for r in items if r not in decided]
    found += [f"{r} isn't in this review" for r in decided if r not in items]
    found += [f"{r} is decided twice" for r in set(decided) if decided.count(r) > 1]
    return found


def research_problems(brief: dict[str, Any], result: dict[str, Any]) -> list[str]:
    """What the database can't judge from a research result alone: every lead accounted for, the best-known leads
    covered in the first pass, and enough ordinary places (content.md, section 1.3)."""
    found: list[str] = []
    places = result["places"]
    given = {lead["lead"]: lead for lead in result["leads"]}
    for lead in brief["leads"]:
        decision = given.get(lead["lead"])
        if decision is None:
            found.append(f"lead {lead['lead']} ({lead['name']}) isn't accounted for")
        elif decision["status"] == "later" and lead["well_known"]:
            found.append(f"lead {lead['lead']} ({lead['name']}) is well known; cover it in this pass")
    for lead_id, decision in given.items():
        status = decision["status"]
        if status in ("skipped", "later") and not decision.get("reason"):
            found.append(f"lead {lead_id}: say why it is {status}")
        if status == "added" and not (isinstance(decision.get("place"), int) and decision["place"] < len(places)):
            found.append(f"lead {lead_id}: 'place' is the index of the place it became")
        if status == "known" and not decision.get("existing"):
            found.append(f"lead {lead_id}: 'existing' is the place it already is")
    share = rules.load().places["min_ordinary_share"]
    if len(places) >= 4 and sum(p["ordinary"] for p in places) < share * len(places):
        found.append(f"fewer than {share:.0%} of the places are ordinary places; look for them")
    return found


def submit_result(args: argparse.Namespace) -> int:
    document = json.loads(args.task_file.read_text())
    result = json.loads(args.result_file.read_text())
    found = problems(document, result)
    if found:
        print("Not submitted. Fix these and submit again:\n" + "\n".join(f"- {p}" for p in found))
        return 1
    function = {"research_cell": "submit_research", "find_photos": "submit_photos"}.get(document["type"],
                                                                                       "submit_task")
    if function != "submit_photos":
        result = result | {"rulebook": document["rulebook"], "bar": document.get("bar_version")}
    with db.connect("worker") as conn:
        outcome = conn.execute(f"SELECT psst.{function}(%s, %s, %s, %s) AS r",
                               (token(), document["task"], Jsonb(result), document["prompt_version"])).fetchone()
    assert outcome
    print(json.dumps(outcome["r"], ensure_ascii=False))
    return 0


def return_task(args: argparse.Namespace) -> int:
    document = json.loads(args.task_file.read_text())
    with db.connect("worker") as conn:
        row = conn.execute("SELECT psst.return_task(%s, %s, %s) AS state",
                           (token(), document["task"], args.problem)).fetchone()
    assert row
    print(f"task {document['task']} is {row['state']}")
    return 0
