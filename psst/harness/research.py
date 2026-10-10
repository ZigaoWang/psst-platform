"""A research cell in the harness (decision 28): triage every lead in one call, gather each chosen lead's own page
in code, write one place per call with tools, submit each place as soon as it passes, then account for every lead.
A stop loses at most the place in hand."""

from __future__ import annotations

import json
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from psst import rules
from psst.cli import tasks as task_cli
from psst.core import db, http
from psst.tasks import prompts, results

from . import quotes, tools
from .executor import PREAMBLE, Executor, GaveUp, Spend, version

MAX_WRITES = 12  # places one pass writes, best first

WRITE_INTRO = """You write ONE place now, from the lead and angle below, not the whole cell: its stories and, for a new
place, its guide. The instructions that follow are for researching a whole cell; apply them to this one place. Reply
with `{"place": <the place, as the instructions describe a place in places>, "leads": [<this lead's id>]}`."""

TRIAGE_SCHEMA = {
    "type": "object", "required": ["decisions"],
    "properties": {"notes": {"type": "string"}, "decisions": {"type": "array", "items": {
        "type": "object", "required": ["lead", "action"],
        "properties": {"lead": {"type": "string"}, "action": {"enum": ["write", "known", "skip", "later"]},
                       "existing": {"type": "string"}, "reason": {"type": "string"},
                       "form": {"enum": ["story", "street_name", "plaque"]},
                       "tier": {"enum": ["featured", "map"]}, "angle": {"type": "string"}}}}}}


def shared_data(document: dict[str, Any]) -> str:
    data = document["data"]
    keys = ("golden_bar", "marked_examples", "reference_stories", "rules")
    return json.dumps({k: data[k] for k in keys if k in data}, ensure_ascii=False, sort_keys=True, default=str)


def triage(executor: Executor, task: dict[str, Any], document: dict[str, Any], spend: Spend) -> dict[str, Any]:
    brief = document["data"]
    prompt = prompts.load("triage").text
    system = PREAMBLE + "\n\n" + prompt + "\n\n## Shared data\n\n" + shared_data(document)
    user = json.dumps({"data": {"leads": brief["leads"], "places_nearby": brief["places_nearby"],
                                "neighborhoods": brief["neighborhoods"], "max_writes": MAX_WRITES},
                       "result_schema": TRIAGE_SCHEMA}, ensure_ascii=False, default=str)
    leads = {lead["lead"]: lead for lead in brief["leads"]}

    def accept(answer: dict[str, Any]) -> dict[str, Any]:
        found = results.problems(TRIAGE_SCHEMA, answer)
        if not found:
            decided = {d["lead"] for d in answer["decisions"]}
            found += [f"decide lead {lead} ({leads[lead]['name']})" for lead in leads if lead not in decided]
            for d in answer["decisions"]:
                if d["action"] in ("skip", "later") and not d.get("reason"):
                    found.append(f"lead {d['lead']}: say why it is {d['action']}")
                if d["action"] == "later" and leads.get(d["lead"], {}).get("well_known"):
                    found.append(f"lead {d['lead']} is well known; write it or skip it with a reason")
                if d["action"] == "known" and not d.get("existing"):
                    found.append(f"lead {d['lead']}: 'existing' is the place it already is")
        if found:
            raise task_cli.NotSubmitted(found)
        return answer

    ctx = tools.Context(conn=db.open_connection(db.conninfo("worker"), autocommit=True), token=executor.token)
    try:
        return dict(executor.converse("triage", system, user, task, version(PREAMBLE + prompt), accept, ctx, spend))
    finally:
        ctx.conn.close()


def gather(executor: Executor, lead: dict[str, Any]) -> list[dict[str, Any]]:
    """What code can read for a lead before the writer starts: its own page and the official records its Wikidata
    item points to (a heritage list entry), so the writer begins from snapshots of the record, not the
    encyclopedia alone."""
    requests = []
    if lead.get("url"):
        wiki = "wikipedia.org" in lead["url"]
        requests.append({"url": lead["url"], "title": lead["name"],
                         "publisher": "Wikipedia" if wiki else lead.get("origin", "unknown"),
                         "kind": "reference" if wiki else "community",
                         "language": "zh" if "zh." in lead["url"] else "en"})
    requests += records(lead.get("wikidata"))
    ctx = tools.Context(conn=db.open_connection(db.conninfo("worker"), autocommit=True), token=executor.token)
    try:
        pages = [tools.call(ctx, "fetch_source", r) for r in requests]
    finally:
        ctx.conn.close()
    return [page for page in pages if not page.get("error")]


def records(qid: str | None) -> list[dict[str, Any]]:
    """The official records a Wikidata item names, as fetch requests (rules/sources.yaml, record_properties)."""
    if not qid:
        return []
    spec = rules.load().sources.get("record_properties", {})
    try:
        entity = http.wikidata_entities([qid], props="claims").get(qid) or {}
    except (OSError, ValueError):
        return []
    found = []
    for prop, how in spec.items():
        for claim in entity.get("claims", {}).get(prop, [])[:2]:
            value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
            if isinstance(value, str):
                found.append({"url": how["url"].format(value), "title": how["title"].format(value),
                              "publisher": how["publisher"], "kind": how["kind"], "language": how["language"]})
    return found


def write(executor: Executor, task: dict[str, Any], document: dict[str, Any], decision: dict[str, Any],
          lead: dict[str, Any], spend: Spend) -> dict[str, Any]:
    prompt = prompts.load("research_cell").text
    system = PREAMBLE + "\n\n" + WRITE_INTRO + "\n\n" + prompt + "\n\n## Shared data\n\n" + shared_data(document)
    brief = document["data"]
    user = json.dumps({"data": {"lead": lead, "angle": decision.get("angle"), "form": decision.get("form"),
                                "tier": decision.get("tier"), "existing": decision.get("existing"),
                                "cell": {"bounds": brief["bounds"], "neighborhoods": brief["neighborhoods"]},
                                "rules": brief["rules"], "gathered": gather(executor, lead)},
                       "result_schema": results.research_place()}, ensure_ascii=False, default=str)
    ctx = tools.Context(conn=db.open_connection(db.conninfo("worker"), autocommit=True), token=executor.token,
                        place_id=decision.get("existing"))
    try:
        gathered = json.loads(user)["data"]["gathered"]
        ctx.read.update(page["snapshot"] for page in gathered)

        repaired: list[dict[str, Any]] = []

        def accept(answer: dict[str, Any]) -> Any:
            stats, repairs = quotes.repair(ctx.conn, answer, ctx.read)
            ctx.conn.execute("SELECT psst.record_quote_repairs(%s, %s, NULL, %s, %s, %s, '[]')",
                             (executor.token, task["id"], executor.model, spend.trace[-1], Jsonb(stats)))
            repaired[:] = repairs
            return task_cli.submit_one_place(document, answer)
        placed = dict(executor.converse("write", system, user, task, version(PREAMBLE + WRITE_INTRO + prompt),
                                        accept, ctx, spend))
        ctx.conn.execute("SELECT psst.record_quote_repairs(%s, %s, %s, %s, NULL, NULL, %s)",
                         (executor.token, task["id"], placed["place"], executor.model, Jsonb(repaired)))
        ctx.conn.execute("SELECT psst.tie_harness_calls(%s, %s, %s)", (executor.token, spend.trace, placed["place"]))
        return placed
    finally:
        ctx.conn.close()


def research_cell(executor: Executor, task: dict[str, Any], document: dict[str, Any], spend: Spend) -> Any:
    leads = {lead["lead"]: lead for lead in document["data"]["leads"]}
    # A rotation triages with its first model and hands each place to the next writer in turn.
    writers = [Executor(executor.token, m) for m in executor.members] if executor.mode == "rotate" else [executor]
    plan = triage(writers[0], task, document, spend)
    accounted: list[dict[str, Any]] = []
    turn = 0
    capped = False
    for d in plan["decisions"]:
        lead = leads.get(d["lead"])
        if lead is None:
            continue
        if d["action"] == "write" and turn >= executor.max_places:
            capped = True
            continue
        if d["action"] == "write":
            writer = writers[turn % len(writers)]
            turn += 1
            try:
                placed = write(writer, task, document, d, lead, Spend())
            except (GaveUp, ValueError, TypeError, KeyError, psycopg.Error) as reason:
                # One place that fails, for any reason, is given back; the rest of the cell goes on.
                status = "skipped" if lead.get("well_known") else "later"
                accounted.append({"lead": d["lead"], "status": status,
                                  "reason": f"couldn't be written to the bar: {reason}"[:300]})
                continue
            accounted.append({"lead": d["lead"], "status": "added", "existing": placed["place"]})
        elif d["action"] == "known":
            accounted.append({"lead": d["lead"], "status": "known", "existing": d["existing"]})
        else:
            accounted.append({"lead": d["lead"], "status": "skipped" if d["action"] == "skip" else "later",
                              "reason": d["reason"][:300]})
    if capped:
        # The run wrote as many places as it was asked to: the places are stored, and the cell goes back to the
        # queue so the next run continues it.
        executor.give_back(document, f"wrote {turn} places as asked; the rest of the cell continues in the next run")
        return {"places_written": turn, "continues": True}
    # Leads the place submissions already settled need no entry; the rest are accounted for here.
    final = {"places": [], "leads": [a for a in accounted if a["status"] != "added"],
             "notes": (plan.get("notes") or "Triaged and written by the harness.")[:600]}
    return task_cli.submit(document, final)
