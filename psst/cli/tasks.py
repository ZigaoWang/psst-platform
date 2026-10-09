"""`psst task`: lease the next task as a file, submit a result, or give a task back."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import jsonschema
from psycopg.types.json import Jsonb

from psst.checks import runner
from psst.core import config, db
from psst.evidence import encyclopedia
from psst.tasks import files

from . import fetching
from .runs import token

WORK = config.ROOT / "work" / "tasks"
WRITING = {"write_story": "story", "write_guide": "guide", "write_trail": "trail"}


def register(groups: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    group = groups.add_parser("task", help="lease, submit, or give back tasks")
    commands = group.add_subparsers(dest="command", required=True, metavar="<task command>")
    lease = commands.add_parser("next", help="lease the next task and write its task file")
    lease.add_argument("--type", action="append", required=True, dest="types", help="a task type (repeatable)")
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


def _lead(place: dict[str, Any]) -> dict[str, Any] | None:
    def read(request: dict[str, Any]) -> dict[str, Any]:
        return fetching.request({"token": token(), **request})
    try:
        return encyclopedia.lead(place, read)
    except ConnectionError:
        return None


def lease_next(args: argparse.Namespace) -> int:
    with db.connect("worker") as conn:
        city = None
        if args.city:
            row = conn.execute("SELECT id FROM psst.cities WHERE slug = %s", (args.city,)).fetchone()
            if row is None:
                raise config.ConfigError(f"no city with the slug {args.city!r}")
            city = row["id"]
        task = conn.execute("SELECT * FROM psst.lease_task(%s, %s, %s)", (token(), args.types, city)).fetchone()
        if task is None:
            print("no task waiting")
            return 3
        document = files.build(conn, task, _lead)
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
    if kind in ("escalate", "audit"):
        found += [f"claim {v['claim']}: decide; 'unclear' isn't an option here"
                  for v in result.get("verdicts", []) if v["verdict"] == "unclear"]
    item_type = WRITING.get(kind) or (document["data"].get("type") if kind == "revise" else None)
    if item_type and item_type != "translation":
        place = (document["data"].get("place") or {}).get("id")
        with db.connect("worker") as conn:
            check = runner.preflight(conn, item_type, place, result)
        found += check.report.refusals
    return found


def submit_result(args: argparse.Namespace) -> int:
    document = json.loads(args.task_file.read_text())
    result = json.loads(args.result_file.read_text())
    found = problems(document, result)
    if found:
        print("Not submitted. Fix these and submit again:\n" + "\n".join(f"- {p}" for p in found))
        return 1
    result = result | {"rulebook": document["rulebook"]}
    with db.connect("worker") as conn:
        outcome = conn.execute("SELECT psst.submit_task(%s, %s, %s, %s) AS r",
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
