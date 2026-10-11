"""A writer trial: several models write the same leads of one cell through the same path and the same checks, nothing
is stored, and the routed reviewer marks what each wrote. A place counts as accepted when every item of it passes
review with no cut to make. Each model's writing runs as its own run, so its cost is read from its own calls."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from typing import Any
from unittest.mock import patch

from psst import rules
from psst.cli import tasks as task_cli
from psst.core import db
from psst.tasks import files, prompts, results

from . import research, tools
from .executor import Executor, GaveUp, Spend


@contextmanager
def dry(placed: list[dict[str, Any]]) -> Iterator[None]:
    """Submissions run every check and keep the place here instead of storing it; every model writes everything, with
    no separate routed writer."""
    def submit_one_place(document: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        found = results.problems(results.research_place(), payload)
        if not found:
            with db.connect("worker") as conn:
                found = task_cli.place_problems(conn, "place", payload["place"],
                                                task_cli.cell_areas(document["data"]))
        if found:
            raise task_cli.NotSubmitted(found)
        placed.append(payload)
        return {"place": f"trial {len(placed)}"}

    with ExitStack() as patches:
        patches.enter_context(patch.object(task_cli, "submit_one_place", submit_one_place))
        patches.enter_context(patch.object(task_cli, "submit", lambda document, result: {"leads": result["leads"]}))
        patches.enter_context(patch.object(research, "prose_writer", lambda evidence_writer: evidence_writer))
        yield


def write(token: str, model: str, task: dict[str, Any], document: dict[str, Any]) -> list[dict[str, Any]]:
    placed: list[dict[str, Any]] = []
    with dry(placed):
        research.research_cell(Executor(token, model), task, document, Spend())
    return placed


def review_items(placed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each story and guide as a review shows it, under a made-up revision id that names its place."""
    items = []
    for n, entry in enumerate(placed, 1):
        place = entry["place"]
        written = [("story", s) for s in place.get("stories") or []] + ([("guide", place["guide"])]
                                                                        if place.get("guide") else [])
        for m, (kind, item) in enumerate(written, 1):
            claims = [{"claim": f"cl_{n}_{m}_{k}", "n": k, "text": c["text"], "kind": c["kind"],
                       "values": c["values"], "passages": [{"quote": e["quote"], "snapshot": e["snapshot"]}
                                                           for e in c["evidence"]]}
                      for k, c in enumerate(item["claims"], 1)]
            summary = {"name": place.get("name"), "kind": place.get("kind")}
            items.append({"revision": f"rv_trial{n:03d}{m}", "type": kind, "place": summary, "body": item["body"],
                          "claims": claims, "flags": files.flags(kind, item["body"], claims, summary),
                          "other_stories": [], "encyclopedia_lead": None})
    return items


def review(token: str, model: str, task: dict[str, Any], items: list[dict[str, Any]],
           shared: dict[str, Any]) -> list[dict[str, Any]]:
    """The routed reviewer's marks on the items, in batches the size a review takes."""
    prompt = prompts.load("review")
    size = int(shared["batch"])
    marks: list[dict[str, Any]] = []
    executor = Executor(token, model)
    for start in range(0, len(items), size):
        batch = items[start:start + size]
        document = {"task": task["id"], "type": "review", "prompt": prompt.text,
                    "data": {"items": batch} | shared["data"], "result_schema": results.schema("review")}
        system, user, version = executor.messages_for(document)

        def accept(answer: dict[str, Any], batch: list[dict[str, Any]] = batch) -> dict[str, Any]:
            found = task_cli.review_problems({"items": batch}, answer)
            if found:
                raise task_cli.NotSubmitted(found)
            return answer
        ctx = tools.Context(conn=db.open_connection(db.conninfo("worker"), autocommit=True), token=token)
        try:
            marks += executor.converse("review", system, user, task, version, accept, ctx, Spend())["decisions"]
        except GaveUp as reason:
            marks += [{"revision": i["revision"], "mark": "unmarked", "reason": str(reason)} for i in batch]
        finally:
            ctx.conn.close()
    return marks


def outcome(placed: list[dict[str, Any]], items: list[dict[str, Any]], marks: list[dict[str, Any]]
            ) -> dict[str, Any]:
    by_revision = {m["revision"]: m for m in marks}
    clean = {i["revision"] for i in items if by_revision.get(i["revision"], {}).get("mark") == "good"
             and not by_revision[i["revision"]].get("fix") and not by_revision[i["revision"]].get("unclaimed")}
    accepted = [n for n in range(1, len(placed) + 1)
                if all(i["revision"] in clean for i in items if i["revision"].startswith(f"rv_trial{n:03d}"))]
    return {"places": len(placed), "accepted": len(accepted), "items": len(items), "clean_items": len(clean),
            "stories": sum(i["type"] == "story" for i in items),
            "marks": {k: sum(m.get("mark") == k for m in marks) for k in ("good", "weak", "bad", "unmarked")},
            "with_cuts": sum(bool(m.get("fix")) for m in marks), "accepted_places": accepted}


def shared_review_data(conn: Any, task: dict[str, Any]) -> dict[str, Any]:
    rulebook = rules.load()
    bar = files.golden_bar(conn)
    data = {"marked_examples": files.golden_examples(conn),
            "reference_stories": files.style_references(conn, task["city_id"]),
            "rules": {"story": rulebook.type("story"), "guide": rulebook.type("guide")}}
    if bar:
        data["golden_bar"] = bar["body"]
    batch = conn.execute("SELECT psst.setting('review.max_batch') AS n").fetchone()
    return {"data": data, "batch": batch["n"] if batch else 12}


def samples(placed: list[dict[str, Any]], accepted: list[int], most: int = 3) -> list[dict[str, Any]]:
    """Up to `most` accepted places, a story first when there is one, each with its prose only."""
    chosen = sorted(accepted, key=lambda n: not placed[n - 1]["place"].get("stories"))[:most]
    return [{"name": placed[n - 1]["place"].get("name"),
             "guide": (placed[n - 1]["place"].get("guide") or {}).get("body"),
             "stories": [s["body"] for s in placed[n - 1]["place"].get("stories") or []]} for n in chosen]


def report(rows: dict[str, dict[str, Any]]) -> str:
    return json.dumps(rows, ensure_ascii=False, indent=2, default=str)
