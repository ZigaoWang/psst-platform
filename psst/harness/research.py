"""A research cell in the harness (decision 28): triage every lead in one call, gather each chosen lead's own page
in code, write one place per call with tools, submit each place as soon as it passes, then account for every lead.
A stop loses at most the place in hand."""

from __future__ import annotations

import json
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast

import psycopg
from psycopg.types.json import Jsonb

from psst import rules
from psst.checks.tools import Claim, Evidence, Snapshot, own_words
from psst.cli import tasks as task_cli
from psst.core import db, http
from psst.evidence import fetch as reading
from psst.evidence import urls
from psst.rules.report import Report
from psst.tasks import prompts, results

from . import quotes, tools
from .executor import Executor, GaveUp, Spend, version

MAX_WRITES = 12  # places one pass writes, best first

TRIAGE_SCHEMA = {
    "type": "object", "required": ["decisions"],
    "properties": {"notes": {"type": "string"}, "decisions": {"type": "array", "items": {
        "type": "object", "required": ["lead", "action"],
        "properties": {"lead": {"type": "string"}, "action": {"enum": ["write", "known", "skip", "later"]},
                       "existing": {"type": "string"}, "reason": {"type": "string"},
                       "form": {"enum": ["story", "street_name", "plaque"]},
                       "tier": {"enum": ["featured", "map"]}, "angle": {"type": "string"}}}}}}


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
    system = prompt  # compact on purpose (decision 34): one line per lead, no examples
    compact = [{k: lead[k] for k in ("lead", "name", "what", "record", "well_known") if lead.get(k)}
               for lead in brief["leads"]]
    nearby = [{"id": p["id"], "name": p["name"], "stories": p["stories"]} for p in brief["places_nearby"]]
    user = json.dumps({"data": {"leads": compact, "places_nearby": nearby, "max_writes": MAX_WRITES},
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
        return dict(executor.converse("triage", system, user, task, version(prompt), accept, ctx, spend))
    finally:
        ctx.conn.close()


PASSAGE_CHARS = 2500   # of each page, the paragraphs that name the place, before any model sees it
FOLLOWED_LINKS = 2     # links from the lead's page to official, archive, or scholarly hosts read as well


def gather(executor: Executor, lead: dict[str, Any]) -> list[dict[str, Any]]:
    """Everything a place's evidence comes from, read in code (decision 34): its own page, the official records its
    Wikidata item points to, and up to two links from its page to official, archive, or scholarly hosts, all read
    together and reused when read before; each cut to the paragraphs that name the place."""
    requests = []
    if lead.get("url"):
        wiki = "wikipedia.org" in lead["url"]
        requests.append({"url": lead["url"], "title": lead["name"],
                         "publisher": "Wikipedia" if wiki else lead.get("origin", "unknown"),
                         "kind": "reference" if wiki else "community",
                         "language": "zh" if "zh." in lead["url"] else "en"})
    requests += records(lead.get("wikidata"))
    pages = read_all(executor, requests)
    strong = {"official_record", "archive", "scholarly"}
    followed = [link["url"] for page in pages for link in page.get("links", [])
                if urls.host_kind(link["url"]) in strong and link["url"] not in {r["url"] for r in requests}]
    pages += read_all(executor, [{"url": u, "title": lead["name"], "publisher": urllib.parse.urlsplit(u).netloc,
                                  "kind": urls.host_kind(u), "language": "en"}
                                 for u in list(dict.fromkeys(followed))[:FOLLOWED_LINKS]])
    terms = " ".join([lead["name"], lead.get("what") or ""])
    return [{"snapshot": page["snapshot"], "kind": page["kind"], "url": page["url"],
             "text": reading.passages(page["text"], terms, PASSAGE_CHARS)} for page in pages]


def read_all(executor: Executor, requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def fetch(request: dict[str, Any]) -> dict[str, Any]:
        ctx = tools.Context(conn=db.open_connection(db.conninfo("worker"), autocommit=True), token=executor.token)
        try:
            return tools.call(ctx, "fetch_source", request | {"full": True})
        finally:
            ctx.conn.close()
    if not requests:
        return []
    with ThreadPoolExecutor(max_workers=len(requests)) as pool:  # a place's sources are read together
        pages = list(pool.map(fetch, requests))
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
    system = prompt  # one call over passages code has read; no tools, no browsing
    gathered = gather(executor, lead)
    if not gathered:
        return {"skip": "none of its pages could be read"}
    user = json.dumps({"data": {"lead": {k: lead.get(k) for k in ("name", "what", "wikidata", "osm", "record")},
                                "angle": decision.get("angle"), "existing": decision.get("existing"),
                                "passages": gathered},
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
        answer = dict(executor.converse("evidence", system, user, task, version(prompt), accept, ctx, spend))
    finally:
        ctx.conn.close()
    return answer | kept


def values_in(fact: dict[str, Any]) -> list[dict[str, str]]:
    """A fact's values, taken from the words of its quotes: every number and every capitalized name, as written
    there, so each value is in its passage by construction and the prose can use only these forms."""
    found: list[str] = []
    for evidence in fact.get("evidence", []):
        quote = evidence.get("quote", "")
        for value in VALUE_NUMBER.findall(quote) + NAME.findall(quote):
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
    rulebook = rules.load()
    for fact in facts:
        quoted = []
        roles = set()
        for e in fact.get("evidence", []):
            snap = texts.get(e.get("snapshot"))
            if snap is None:
                found.append(f"fact {fact.get('id')}: no snapshot {e.get('snapshot')}; quote only pages you read")
            elif not find_quote(snap["text"], e.get("quote", "")):
                found.append(f"fact {fact.get('id')}: the quote isn't in snapshot {e['snapshot']}; copy it exactly")
            else:
                quoted.append(e["quote"])
                kind = urls.host_kind(snap["url"]) or snap["kind"]
                sources[snap["source_id"]] = kind
                roles.add(rulebook.sources["kinds"].get(kind, {}).get("role"))
        if roles == {"reference"}:
            found.append(f"fact {fact.get('id')}: rests only on reference works; quote the record they draw on, or "
                         "drop the fact")
        for v in fact.get("values", []):
            if quoted and not any(contains(q, v.get("source_form") or v["value"]) for q in quoted):
                found.append(f"fact {fact.get('id')}: '{v['value']}' isn't in its quoted passages; quote the words "
                             "that state it")
    # A fact is a note in the evidence step's own words; one that keeps a run of its source's words would carry that
    # copying into the story.
    report = Report()
    snapshots = {sid: Snapshot(sid, r["source_id"], r["url"], r["kind"], r["text"]) for sid, r in texts.items()}
    claims = [Claim(n, f.get("text", ""), f.get("kind", "attribute"), [],
                    [Evidence(e.get("snapshot", ""), e.get("quote", "")) for e in f.get("evidence", [])])
              for n, f in enumerate(facts, 1)]
    own_words(report, {f"fact {f.get('id')}": f.get("text", "") for f in facts}, claims, snapshots, rulebook)
    found += [r.replace("write it in your own words or quote it", "put the fact in your own words")
              for r in report.refusals]
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
    # Slim on purpose (decision 34): the golden bar shows the voice; the full golden set and rules stay out.
    system = prompt + "\n\n## The golden bar\n\n" + str(document["data"].get("golden_bar") or "")
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
        placed = dict(executor.converse("write", system, user, task, version(prompt), accept, ctx, spend))
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
VALUE_NUMBER = re.compile(r"\d[\d,.]*\d(?:st|nd|rd|th)?|\d(?:st|nd|rd|th)?")  # "19th" stays whole as a value
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


def prose_writer(evidence_writer: Executor) -> Executor:
    """The model for the writing step: routing.research_writer when set (writing needs craft, not tools, and its
    context is small), otherwise the model that gathered the evidence."""
    with db.connect("worker") as conn:
        row = conn.execute("SELECT psst.setting('routing.research_writer') #>> '{}' AS m").fetchone()
    model = row["m"] if row else None
    return Executor(evidence_writer.token, model) if model else evidence_writer


def research_cell(executor: Executor, task: dict[str, Any], document: dict[str, Any], spend: Spend) -> Any:
    """Triage, then write the chosen places in parallel (harness.parallel_places at once), each submitted as soon as
    it passes, then account for every lead."""
    leads = {lead["lead"]: lead for lead in document["data"]["leads"]}
    # A rotation triages with its first model and hands each place to the next writer in turn.
    writers = [Executor(executor.token, m) for m in executor.members] if executor.mode == "rotate" else [executor]
    plan = triage(writers[0], task, document, spend)
    accounted: list[dict[str, Any]] = []
    chosen = [d for d in plan["decisions"] if d["action"] == "write" and d["lead"] in leads]
    capped = len(chosen) > executor.max_places
    chosen = chosen[:executor.max_places]
    for d in plan["decisions"]:
        if d["lead"] not in leads or d["action"] == "write":
            continue
        if d["action"] == "known":
            accounted.append({"lead": d["lead"], "status": "known", "existing": d["existing"]})
        else:
            accounted.append({"lead": d["lead"], "status": "skipped" if d["action"] == "skip" else "later",
                              "reason": d["reason"][:300]})

    def place(turn: int, d: dict[str, Any]) -> dict[str, Any]:
        lead, writer = leads[d["lead"]], writers[turn % len(writers)]
        try:
            gathered = evidence(writer, task, document, d, lead, Spend())
            if gathered.get("skip"):
                return {"lead": d["lead"], "status": "skipped",
                        "reason": f"the evidence isn't there: {gathered['skip']}"[:300]}
            placed = write(prose_writer(writer), task, document, d, lead, gathered, Spend())
        except (GaveUp, ValueError, TypeError, KeyError, psycopg.Error) as reason:
            # One place that fails, for any reason, is given back; the rest of the cell goes on.
            return {"lead": d["lead"], "status": "skipped" if lead.get("well_known") else "later",
                    "reason": f"couldn't be written to the bar: {reason}"[:300]}
        return {"lead": d["lead"], "status": "added", "existing": placed["place"]}

    with ThreadPoolExecutor(max_workers=parallel_places()) as pool:
        accounted += list(pool.map(place, range(len(chosen)), chosen))
    if capped:
        # The run wrote as many places as it was asked to: the places are stored, and the cell goes back to the
        # queue so the next run continues it.
        executor.give_back(document, f"wrote {len(chosen)} places as asked; the rest of the cell continues next run")
        return {"places_written": len(chosen), "continues": True}
    # Leads the place submissions already settled need no entry; the rest are accounted for here.
    final = {"places": [], "leads": [a for a in accounted if a["status"] != "added"],
             "notes": (plan.get("notes") or "Triaged and written by the harness.")[:600]}
    return task_cli.submit(document, final)


def parallel_places() -> int:
    with db.connect("worker") as conn:
        row = conn.execute("SELECT psst.setting('harness.parallel_places') #>> '{}' AS n").fetchone()
    return max(1, int(row["n"])) if row and row["n"] else 8
