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
from .executor import Executor, Spend, version

# "10 and 12, Northampton Park", "104-120, Shakespeare Walk N16", "1-39, Clissold Road N16"
HOUSES = re.compile(r"^\s*(?:Nos?\.?\s*)?(\d+[A-Za-z]?(?:\s*(?:-|–|,|&|and|And)\s*\d+[A-Za-z]?)*)\s*,?\s+"
                    r"(?P<street>[A-Za-z][A-Za-z' .-]+?)(?:\s+[A-Z]{1,2}\d{1,2}[A-Z]?)?\s*$")
GROUP_MAX = 12  # entries read in one call; a longer street is split by its numbers
RECORD_TEXT = 3000  # of each record page, the part that describes the place

RECORD_GUIDE_SCHEMA: dict[str, Any] = {
    "type": "object", "required": ["angle", "specific", "place", "facts", "guide"],
    "properties": {"angle": {"type": "boolean"}, "specific": {"type": "array", "items": {"type": "string"}},
                   "place": {"type": "object", "required": ["name", "kind", "size", "ordinary"]},
                   "facts": research.EVIDENCE_SCHEMA["properties"]["facts"],
                   "guide": {"type": "object", "required": ["body", "facts"]}},
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
    """Writes one group's guide in one call and submits it. Returns {"added": [lead ids], "story": [lead ids that go
    on to the story route], "skipped": reason}."""
    pages = research.read_all(executor, [r for lead in group for r in research.records(lead.get("wikidata"))[:1]])
    if not pages:
        return {"skipped": "its record couldn't be read"}
    passages = [{"snapshot": p["snapshot"], "url": p["url"], "kind": p["kind"], "text": p["text"][:RECORD_TEXT]}
                for p in pages]
    prompt = prompts.load("record_guide").text
    system = prompt + "\n\n## Lengths, in characters\n\n" + research.lengths()
    user = json.dumps({"data": {"leads": [{"lead": lead["lead"], "name": lead["name"]} for lead in group],
                                "passages": passages}, "result_schema": RECORD_GUIDE_SCHEMA},
                      ensure_ascii=False, default=str)
    ids = {lead["lead"] for lead in group}
    anchor = group[0]
    ctx = tools.Context(conn=db.open_connection(db.conninfo("worker"), autocommit=True), token=executor.token)
    ctx.read.update(p["snapshot"] for p in pages)
    outcome: dict[str, Any] = {}

    def accept(answer: dict[str, Any]) -> dict[str, Any]:
        found = results.problems(RECORD_GUIDE_SCHEMA, answer)
        if found:
            raise task_cli.NotSubmitted(found)
        specific = [i for i in answer["specific"] if i in ids and len(group) > 1]
        if len(group) == 1 and answer["angle"]:
            outcome.update(story=[anchor["lead"]])  # a record with an angle goes the story route
            return outcome
        for fact in answer["facts"]:
            fact["values"] = research.values_in(fact)
        facts = {f["id"]: f for f in answer["facts"]
                 if not research.reference_only(ctx.conn, f) and not research.unquoted(f, anchor["name"])}
        problems = research.verify(ctx.conn, list(facts.values()), "guide")
        if problems:
            raise task_cli.NotSubmitted(problems)
        guide = answer["guide"]
        if isinstance(guide.get("facts"), list):  # a fact dropped above leaves the guide; the checks hold its prose
            guide["facts"] = [i for i in guide["facts"] if i in facts]
        if isinstance(guide.get("body"), dict):
            allowed = rules.load().type("guide")["schema"]["properties"]
            guide["body"] = {k: v for k, v in guide["body"].items() if k in allowed}
            guide["body"].setdefault("key_facts", [])
        identity = {k: answer["place"][k] for k in ("name", "kind", "size", "ordinary") if k in answer["place"]}
        identity |= {k: anchor[k] for k in ("wikidata", "osm") if anchor.get(k)}  # the first house places it
        place = research.assemble(identity, {"stories": [], "guide": guide}, facts)
        research.us_spelling(place)
        known = [lead["name"] for lead in group] + [identity.get("name", ""), *task_cli.cell_areas(document["data"])]
        cuts.attach_quotes(ctx.conn, place["guide"]["body"], place["guide"]["claims"], known)
        covered = [i for i in ids if i not in specific]
        placed = task_cli.submit_one_place(document, {"place": place, "leads": covered})
        outcome.update(added=covered, story=specific, place=placed.get("place"))
        return outcome

    try:
        return dict(executor.converse("record_guide", system, user, task, version(prompt), accept, ctx, spend))
    finally:
        ctx.conn.close()
