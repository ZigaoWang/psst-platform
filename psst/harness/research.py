"""A research cell in the harness (decision 28): triage every lead in one call, gather each chosen lead's own page
in code, write one place per call with tools, submit each place as soon as it passes, then account for every lead.
A stop loses at most the place in hand."""

from __future__ import annotations

import json
import re
from typing import Any, cast

import psycopg
from psycopg.types.json import Jsonb

from psst import rules
from psst.cli import tasks as task_cli
from psst.core import db, http
from psst.evidence import urls
from psst.tasks import prompts, results

from . import quotes, tools
from .executor import PREAMBLE, Executor, GaveUp, Spend, version

MAX_WRITES = 12  # places one pass writes, best first

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


def mark_records(leads: list[dict[str, Any]]) -> None:
    """Note on each lead whether its Wikidata item points to an official record, in one batched lookup, so triage
    can prefer the leads a story can rest on."""
    qids = sorted({lead["wikidata"] for lead in leads if lead.get("wikidata")})
    try:
        entities = http.wikidata_entities(qids, props="claims") if qids else {}
    except (OSError, ValueError):
        return
    for lead in leads:
        found = records(lead.get("wikidata"), entities)
        if found:
            lead["record"] = found[0]["title"]


def triage(executor: Executor, task: dict[str, Any], document: dict[str, Any], spend: Spend) -> dict[str, Any]:
    brief = document["data"]
    mark_records(brief["leads"])
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


def records(qid: str | None, entities: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """The official records a Wikidata item names, as fetch requests (rules/sources.yaml, record_properties)."""
    if not qid:
        return []
    spec = rules.load().sources.get("record_properties", {})
    if entities is None:
        try:
            entities = http.wikidata_entities([qid], props="claims")
        except (OSError, ValueError):
            return []
    entity = entities.get(qid) or {}
    found = []
    for prop, how in spec.items():
        for claim in entity.get("claims", {}).get(prop, [])[:2]:
            value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
            if isinstance(value, str):
                found.append({"url": how["url"].format(value), "title": how["title"].format(value),
                              "publisher": how["publisher"], "kind": how["kind"], "language": how["language"]})
    return found


CLAIM_PROPERTIES: dict[str, Any] = cast(dict[str, Any], results.CLAIMS["items"])["properties"]
EVIDENCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"skip": {"type": "string", "minLength": 5},
                   "place": results.place_identity(),
                   "facts": {"type": "array", "items": {
                       "type": "object", "required": ["id", "text", "kind", "values", "evidence"],
                       "properties": {"id": {"type": "string"}} | CLAIM_PROPERTIES}}},
}
MIN_FACTS = 3


def evidence(executor: Executor, task: dict[str, Any], document: dict[str, Any], decision: dict[str, Any],
             lead: dict[str, Any], spend: Spend) -> dict[str, Any]:
    """Step one (decision 32): the facts for one place, each bound to the exact words of a source, checked in code
    before anything is written: every quote in its snapshot, every value in its quote, and enough independent and
    primary sources for a story. Returns {"skip": reason} when the evidence for a real story isn't there."""
    prompt = prompts.load("evidence").text
    system = PREAMBLE + "\n\n" + prompt
    brief = document["data"]
    gathered = gather(executor, lead)
    user = json.dumps({"data": {"lead": lead, "angle": decision.get("angle"), "form": decision.get("form"),
                                "tier": decision.get("tier"), "existing": decision.get("existing"),
                                "cell": {"bounds": brief["bounds"], "neighborhoods": brief["neighborhoods"]},
                                "gathered": gathered},
                       "result_schema": EVIDENCE_SCHEMA}, ensure_ascii=False, default=str)
    ctx = tools.Context(conn=db.open_connection(db.conninfo("worker"), autocommit=True), token=executor.token,
                        place_id=decision.get("existing"))
    ctx.read.update(page["snapshot"] for page in gathered)
    kept: dict[str, Any] = {}

    def accept(answer: dict[str, Any]) -> dict[str, Any]:
        if answer.get("skip"):
            return {"skip": str(answer["skip"])[:300]}
        found = results.problems(EVIDENCE_SCHEMA, answer)
        if not found and not answer.get("place"):
            found = ["name the place: a new one with name, kind, size, ordinary, and wikidata or osm; or existing"]
        if found:
            raise task_cli.NotSubmitted(found)
        stats, repairs = quotes.repair(ctx.conn, answer, ctx.read)
        ctx.conn.execute("SELECT psst.record_quote_repairs(%s, %s, NULL, %s, %s, %s, '[]')",
                         (executor.token, task["id"], executor.model, spend.trace[-1], Jsonb(stats)))
        for fact in answer.get("facts") or []:
            fact["values"] = values_in(fact)  # the exact numbers and names its quotes state, never the model's own
        found = verify(ctx.conn, answer.get("facts") or [])
        if found:
            raise task_cli.NotSubmitted(found)
        kept.update(repairs=repairs)
        return answer
    try:
        answer = dict(executor.converse("evidence", system, user, task, version(PREAMBLE + prompt), accept, ctx,
                                        spend))
    finally:
        ctx.conn.close()
    return answer | kept


def values_in(fact: dict[str, Any]) -> list[dict[str, str]]:
    """A fact's values, taken from the words of its quotes: every number and every capitalized name, as written
    there, so each value is in its passage by construction and the prose can use only these forms."""
    found: list[str] = []
    for evidence in fact.get("evidence", []):
        quote = evidence.get("quote", "")
        for value in NUMBER.findall(quote) + NAME.findall(quote):
            if value not in found and value not in COMMON:
                found.append(value)
    return [{"value": v} for v in found[:12]]


def verify(conn: Any, facts: list[dict[str, Any]]) -> list[str]:
    """What is wrong with a set of facts before anything is written from them."""
    from psst.core.text import contains, find_quote
    found: list[str] = []
    texts = {r["id"]: r for r in conn.execute("""
        SELECT n.id, n.text, n.source_id, s.url, s.kind FROM psst.snapshots n JOIN psst.sources s ON s.id = n.source_id
        WHERE n.id = ANY(%s)""", ([e.get("snapshot") for f in facts for e in f.get("evidence", [])],))}
    sources: dict[str, str] = {}
    for fact in facts:
        quoted = []
        for e in fact.get("evidence", []):
            snap = texts.get(e.get("snapshot"))
            if snap is None:
                found.append(f"fact {fact.get('id')}: no snapshot {e.get('snapshot')}; quote only pages you read")
            elif not find_quote(snap["text"], e.get("quote", "")):
                found.append(f"fact {fact.get('id')}: the quote isn't in snapshot {e['snapshot']}; copy it exactly")
            else:
                quoted.append(e["quote"])
                sources[snap["source_id"]] = urls.host_kind(snap["url"]) or snap["kind"]
        for v in fact.get("values", []):
            if quoted and not any(contains(q, v.get("source_form") or v["value"]) for q in quoted):
                found.append(f"fact {fact.get('id')}: '{v['value']}' isn't in its quoted passages; quote the words "
                             "that state it")
    rulebook = rules.load()
    need = rulebook.sources["rules"]["story"]
    strong = [k for k in sources.values()
              if rulebook.sources["kinds"].get(k, {}).get("role") in rulebook.sources["strong_roles"]]
    if len(facts) < MIN_FACTS:
        found.append(f"a story needs at least {MIN_FACTS} facts; find more, or answer skip with the reason")
    if len(sources) < need["min_sources"]:
        found.append(f"the facts rest on {len(sources)} source; a story needs {need['min_sources']} independent ones")
    if len(strong) < need["min_strong_sources"]:
        found.append("no primary record or scholarly source among the facts; find one, or answer skip with the reason")
    return found


def write(executor: Executor, task: dict[str, Any], document: dict[str, Any], decision: dict[str, Any],
          lead: dict[str, Any], gathered: dict[str, Any], spend: Spend) -> dict[str, Any]:
    """Step two (decision 32): the stories and guide from the verified facts only, with no tools. Code builds the
    claims from the facts each part names, refuses any year, number, or name that isn't in them, and then submits
    the place through the same checks as any submission."""
    prompt = prompts.load("write_place").text
    system = PREAMBLE + "\n\n" + prompt + "\n\n## Shared data\n\n" + shared_data(document)
    facts = {f["id"]: f for f in gathered["facts"]}
    # The writer sees each fact in plain words with its values, not the quoted source, so it tells the story in its
    # own words; the claims it rests on still carry the exact quotes.
    with db.connect("worker") as conn:
        origin = {r["id"]: r for r in conn.execute("""
            SELECT n.id, s.publisher, s.kind FROM psst.snapshots n JOIN psst.sources s ON s.id = n.source_id
            WHERE n.id = ANY(%s)""", ([e["snapshot"] for f in facts.values() for e in f["evidence"]],))}
    shown = [{k: f[k] for k in ("id", "text", "kind", "values") if k in f}
             | {"sources": sorted({f"{origin[e['snapshot']]['publisher']} ({origin[e['snapshot']]['kind']})"
                                   for e in f["evidence"] if e["snapshot"] in origin})}
             for f in facts.values()]
    user = json.dumps({"data": {"place": gathered["place"], "lead": lead["name"], "angle": decision.get("angle"),
                                "tier": decision.get("tier"), "form": decision.get("form"),
                                "facts": shown}}, ensure_ascii=False, default=str)
    ctx = tools.Context(conn=db.open_connection(db.conninfo("worker"), autocommit=True), token=executor.token,
                        place_id=decision.get("existing"))

    def accept(answer: dict[str, Any]) -> Any:
        for story in answer.get("stories") or []:
            if isinstance(story, dict) and isinstance(story.get("body"), dict):
                # What triage planned stands when the writer leaves it out; tags are added at publishing.
                story["body"].setdefault("tier", decision.get("tier") or "map")
                story["body"].setdefault("form", decision.get("form") or "story")
                story["body"].setdefault("tags", [])
        place = assemble(gathered["place"], answer, facts)
        found = unsupported(place, facts, [lead["name"], *document["data"]["neighborhoods"]])
        if found:
            raise task_cli.NotSubmitted(found)
        return task_cli.submit_one_place(document, {"place": place, "leads": [lead["lead"]]})
    try:
        placed = dict(executor.converse("write", system, user, task, version(PREAMBLE + prompt), accept, ctx,
                                        spend))
        ctx.conn.execute("SELECT psst.record_quote_repairs(%s, %s, %s, %s, NULL, NULL, %s)",
                         (executor.token, task["id"], placed["place"], executor.model,
                          Jsonb(gathered.get("repairs", []))))
        ctx.conn.execute("SELECT psst.tie_harness_calls(%s, %s, %s)", (executor.token, spend.trace, placed["place"]))
        return placed
    finally:
        ctx.conn.close()


def assemble(place: dict[str, Any], answer: dict[str, Any], facts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """The place as a submission: each story and the guide with the claims of the facts they name."""
    def claims(ids: list[str]) -> list[dict[str, Any]]:
        if not isinstance(ids, list) or any(i not in facts for i in ids):
            raise task_cli.NotSubmitted([f"name facts by their ids ({', '.join(facts)}); got {ids}"])
        return [{k: facts[i][k] for k in ("text", "kind", "values", "evidence") if k in facts[i]} for i in ids]
    def with_needed(body: dict[str, Any], ids: list[str]) -> list[str]:
        """The facts named, plus any other verified fact that states a number or name the prose uses."""
        if not isinstance(ids, list):
            return ids
        prose = " ".join(v for v in body.values() if isinstance(v, str))
        wanted = set(NUMBER.findall(prose)) | set(NAME.findall(prose))
        named = " ".join(json.dumps(facts[i], ensure_ascii=False) for i in ids if i in facts)
        for value in sorted(wanted):
            if value in named:
                continue
            for fid, fact in facts.items():
                if fid not in ids and value in json.dumps(fact, ensure_ascii=False):
                    ids = [*ids, fid]
                    named += " " + json.dumps(fact, ensure_ascii=False)
                    break
        return ids

    built = dict(place)
    try:
        built["stories"] = [{"body": s["body"], "claims": claims(with_needed(s["body"], s["facts"]))}
                            for s in answer["stories"]]
        if answer.get("guide") and "existing" not in place:
            guide = answer["guide"]
            built["guide"] = {"body": guide["body"], "claims": claims(with_needed(guide["body"], guide["facts"]))}
    except (KeyError, TypeError, AttributeError):
        raise task_cli.NotSubmitted(["answer {stories: [{body, facts}], guide: {body, facts}}"]) from None
    return built


NUMBER = re.compile(r"\d[\d,.]*\d|\d")
NAME = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*")


def unsupported(place: dict[str, Any], facts: dict[str, dict[str, Any]], known: list[str]) -> list[str]:
    """Every year, number, and proper name in the prose must come from the verified facts it names (decision 32)."""
    found: list[str] = []
    parts = [("story", s) for s in place.get("stories", [])] + ([("guide", place["guide"])] if "guide" in place else [])
    for label, part in parts:
        support = " ".join(json.dumps(c, ensure_ascii=False) for c in part["claims"]) + " " + " ".join(known)
        support_digits = re.sub(r"[^0-9]", " ", support)
        fields = [v for v in part["body"].values() if isinstance(v, str)]
        for number in {re.sub(r"[,.]", "", n) for n in NUMBER.findall(" ".join(fields))}:
            if number not in support_digits.split() and number not in re.sub(r"[,.]", "", support):
                found.append(f"{label}: {number} isn't in the facts it names; use only the facts' numbers")
        names = set()
        for field in fields:
            for sentence in re.split(r"(?<=[.!?:;])\s+", field):
                rest = sentence.split(None, 1)[1] if len(sentence.split()) > 1 else ""  # not a sentence's first word
                names |= set(NAME.findall(rest))
        for name in names:
            if name.casefold() not in support.casefold() and name not in COMMON:
                found.append(f"{label}: '{name}' isn't in the facts it names; use only the facts' names")
    return found


# Capitalized words that aren't names a fact must state.
COMMON = {"The", "A", "An", "It", "Its", "In", "On", "At", "From", "Look", "Stand", "Walk", "Find", "This", "That",
          "These", "Those", "Today", "Now", "When", "Where", "Here", "There", "He", "She", "They", "His", "Her",
          "Their", "I", "We", "You", "Your", "After", "Before", "By", "For", "With", "Over", "Under", "Above", "Below"}


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
                gathered = evidence(writer, task, document, d, lead, Spend())
                if gathered.get("skip"):
                    accounted.append({"lead": d["lead"], "status": "skipped",
                                      "reason": f"the evidence isn't there: {gathered['skip']}"[:300]})
                    continue
                placed = write(writer, task, document, d, lead, gathered, Spend())
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
