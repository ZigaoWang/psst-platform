"""Full coverage of a research cell (decision 40): every lead with an official record gets at least a guide. Listed
houses of one terrace or street become one place with one guide covering their numbers; a single house keeps a place
of its own only when its record says something specific about it. One call reads the records and writes the guide;
a record with an angle goes on to the story route. Facts, tool checks, and review are the same as for any place."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any

from psst import rules
from psst.cli import tasks as task_cli
from psst.core import db
from psst.tasks import prompts, results

from . import cuts, research, tools
from .executor import Executor, GaveUp, Spend, version

# "10 and 12, Northampton Park", "104-120, Shakespeare Walk N16", "1-39, Clissold Road N16"
HOUSES = re.compile(r"^\s*(?:Nos?\.?\s*)?(\d+[A-Za-z]?(?:\s*(?:-|–|,|&|and|And)\s*\d+[A-Za-z]?)*)\s*,?\s+"
                    r"(?P<street>[A-Za-z][A-Za-z' .-]+?)(?:\s+[A-Z]{1,2}\d{1,2}[A-Z]?)?\s*$")
GROUP_MAX = 12  # entries read in one call; a longer street is split by its numbers
RECORD_TEXT = 3000  # of each record page, the part that describes the place

PLACE_SCHEMA: dict[str, Any] = {
    "type": "object", "required": ["leads", "angle", "place", "facts", "guide"],
    "properties": {"leads": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                   "angle": {"type": "boolean"},
                   "place": {"type": "object", "required": ["name", "kind", "size", "ordinary"]},
                   "facts": research.EVIDENCE_SCHEMA["properties"]["facts"],
                   "guide": {"type": "object", "required": ["body"]}},
}
RECORD_GUIDE_SCHEMA: dict[str, Any] = {
    "type": "object", "required": ["places"],
    "properties": {"places": {"type": "array", "items": PLACE_SCHEMA},
                   "skipped": {"type": "array", "items": {"type": "object", "required": ["lead", "reason"]}}},
}

def coverage_cells() -> set[str]:
    with db.connect("worker") as conn:
        row = conn.execute("SELECT psst.setting('harness.coverage_cells') AS c").fetchone()
    return set(row["c"] or []) if row else set()


def street(lead: dict[str, Any]) -> str | None:
    """The street a lead's listed houses stand on, or None for anything else."""
    match = HOUSES.match(lead["name"])
    return match.group("street").strip().casefold() if match else None


def first_number(lead: dict[str, Any]) -> int:
    found = re.match(r"\D*(\d+)", lead["name"])
    return int(found.group(1)) if found else 0


def groups(cell: str, brief_leads: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """The record leads of this pass as groups to write: each house lead with every other open house lead of its street
    in the cell (in runs of GROUP_MAX), and every other record lead alone."""
    records = [lead for lead in brief_leads if lead.get("origin") == "record"]
    streets = {s for s in (street(lead) for lead in records) if s}
    with db.connect("worker") as conn:
        others = [dict(r) for r in conn.execute("""
            SELECT id AS lead, name, origin, wikidata_id AS wikidata, osm_ref AS osm, url, what, fame, status,
                   place_id AS existing
            FROM psst.leads WHERE cell = %s AND origin = 'record' AND status IN ('open', 'later')""", (cell,))]
    by_street: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for lead in [*records, *others]:
        s = street(lead)
        if s in streets:
            by_street[s].setdefault(lead["lead"], lead)
    out = []
    for leads in by_street.values():
        ordered = sorted(leads.values(), key=first_number)
        out += [ordered[i:i + GROUP_MAX] for i in range(0, len(ordered), GROUP_MAX)]
    out += [[lead] for lead in records if not street(lead)]
    return out


def record_guide(executor: Executor, task: dict[str, Any], document: dict[str, Any], group: list[dict[str, Any]],
                 spend: Spend) -> dict[str, Any]:
    """Sorts one group's records into places and writes each place's guide in one call, submitting each place as it
    passes. Returns {"added": [lead ids], "story": [lead ids that go on to the story route], "skipped": {id: reason},
    "failed": {id: reason}}."""
    by_lead = {lead["lead"]: lead for lead in group}
    pages = research.read_all(executor, [r for lead in group for r in research.records(lead.get("wikidata"))[:1]])
    if not pages:
        return {"skipped": {i: "its record couldn't be read" for i in by_lead}}
    passages = [{"snapshot": p["snapshot"], "url": p["url"], "kind": p["kind"],
                 "text": research.record_text(p["text"])[:RECORD_TEXT]} for p in pages]
    prompt = prompts.load("record_guide").text
    system = prompt + "\n\n## Lengths, in characters\n\n" + research.lengths()
    user = json.dumps({"data": {"leads": [{"lead": i, "name": lead["name"]} for i, lead in by_lead.items()],
                                "passages": passages}, "result_schema": RECORD_GUIDE_SCHEMA},
                      ensure_ascii=False, default=str)
    ctx = tools.Context(conn=db.open_connection(db.conninfo("worker"), autocommit=True), token=executor.token)
    ctx.read.update(p["snapshot"] for p in pages)
    outcome: dict[str, Any] = {"added": [], "story": [], "skipped": {}, "failed": {}}

    def accept(answer: dict[str, Any]) -> dict[str, Any]:
        if answer.get("skip") and not answer.get("places"):  # declined in words: every lead waits with the reason
            outcome["skipped"] = {i: f"the record isn't enough for a guide: {answer['skip']}"[:300]
                                  for i in by_lead if i not in set(outcome["added"]) | set(outcome["story"])}
            return outcome
        found = results.problems(RECORD_GUIDE_SCHEMA, answer)
        if found:
            raise task_cli.NotSubmitted(found)
        settled = set(outcome["added"]) | set(outcome["story"])  # places submitted in an earlier round stay done
        outcome["skipped"] = {s["lead"]: str(s["reason"])[:300] for s in answer.get("skipped") or []
                              if s.get("lead") in by_lead}
        problems = []
        for n, entry in enumerate(answer["places"], 1):
            leads = [i for i in dict.fromkeys(entry["leads"]) if i in by_lead and i not in settled]
            if not leads:
                continue
            if len(leads) == 1 and entry["angle"]:
                outcome["story"].append(leads[0])  # a record with an angle goes the story route
                continue
            try:
                place_guide(ctx, document, [by_lead[i] for i in leads], entry)
            except task_cli.NotSubmitted as refused:
                problems += [f"place {n} ({entry['place'].get('name')}): {p}" for p in refused.found]
                continue
            outcome["added"] += leads
        missing = [i for i in by_lead if i not in set(outcome["added"]) | set(outcome["story"])
                   | set(outcome["skipped"])]
        if problems:
            raise task_cli.NotSubmitted(problems + ["answer again with the places not yet accepted"])
        outcome["failed"] = {i: "no place was written for it" for i in missing}
        return outcome

    try:
        return dict(executor.converse("record_guide", system, user, task, version(prompt), accept, ctx, spend))
    except GaveUp as reason:
        left = [i for i in by_lead if i not in set(outcome["added"]) | set(outcome["story"])]
        return outcome | {"failed": {i: f"couldn't be written to the bar: {reason}"[:300] for i in left}}
    finally:
        ctx.conn.close()


def place_guide(ctx: tools.Context, document: dict[str, Any], leads: list[dict[str, Any]],
                entry: dict[str, Any]) -> None:
    """Checks one place's facts and guide and submits it; raises NotSubmitted with what to fix."""
    names = " ".join([*(lead["name"] for lead in leads), entry["place"].get("name", "")])
    for fact in entry["facts"]:
        fact["values"] = research.values_in(fact)
    facts = {f["id"]: f for f in entry["facts"]
             if not research.reference_only(ctx.conn, f) and not research.unquoted(f, names)}
    problems = research.verify(ctx.conn, list(facts.values()), "guide")
    if problems:
        raise task_cli.NotSubmitted(problems)
    guide = entry["guide"]
    if not isinstance(guide.get("facts"), list) or not guide["facts"]:
        guide["facts"] = list(facts)  # a guide that names none rests on its place's facts
    guide["facts"] = [i for i in guide["facts"] if i in facts]  # a fact dropped above leaves the guide
    if isinstance(guide.get("body"), dict):
        allowed = rules.load().type("guide")["schema"]["properties"]
        guide["body"] = {k: v for k, v in guide["body"].items() if k in allowed}
        guide["body"].setdefault("key_facts", [])
    identity = {k: entry["place"][k] for k in ("name", "kind", "size", "ordinary") if k in entry["place"]}
    identity |= {k: leads[0][k] for k in ("wikidata", "osm") if leads[0].get(k)}  # the first house places it
    place = research.assemble(identity, {"stories": [], "guide": guide}, facts)
    research.us_spelling(place)
    known = [lead["name"] for lead in leads] + [identity.get("name", ""), *task_cli.cell_areas(document["data"])]
    cuts.attach_quotes(ctx.conn, place["guide"]["body"], place["guide"]["claims"], known)
    task_cli.submit_one_place(document, {"place": place, "leads": [lead["lead"] for lead in leads]})
