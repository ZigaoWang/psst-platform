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
from psst.cli import tasks as task_cli
from psst.core import db, http
from psst.evidence import fetch as reading
from psst.evidence import urls
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
    most = min(MAX_WRITES, executor.max_places)
    user = json.dumps({"data": {"leads": compact, "places_nearby": nearby, "max_writes": most},
                       "result_schema": TRIAGE_SCHEMA}, ensure_ascii=False, default=str)
    leads = {lead["lead"]: lead for lead in brief["leads"]}

    storyless = {p["id"] for p in brief["places_nearby"] if not p["stories"]}

    def accept(answer: dict[str, Any]) -> dict[str, Any]:
        found = results.problems(TRIAGE_SCHEMA, answer)
        if not found:
            settle_storyless(answer["decisions"], storyless, leads, most)
            decided = {d["lead"] for d in answer["decisions"]}
            found += [f"decide lead {lead} ({leads[lead]['name']})" for lead in leads if lead not in decided]
            writes = sum(d["action"] == "write" for d in answer["decisions"])
            for d in reversed(answer["decisions"]):  # past the pass's number, the last chosen wait for the next
                if writes > most and d["action"] == "write" and not leads.get(d["lead"], {}).get("well_known"):
                    d.update(action="later", reason="chosen to write; over this pass's number of places")
                    writes -= 1
            if writes > most:
                found.append(f"{writes} leads to write; choose at most {most}, the best, and mark the rest later")
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


def settle_storyless(decisions: list[dict[str, Any]], storyless: set[str], leads: dict[str, Any], most: int) -> None:
    """A lead answered known for a place that has no stories yet is written for that place, as the prompt asks;
    beyond the pass's number of places it waits for the next pass."""
    room = most - sum(d["action"] == "write" for d in decisions)
    for d in decisions:
        if d["action"] != "known" or d.get("existing") not in storyless:
            continue
        if room > 0:
            d.update(action="write", form=d.get("form") or "story", tier=d.get("tier") or "map",
                     angle=d.get("angle") or d.get("reason") or "")
            room -= 1
        elif not leads.get(d["lead"], {}).get("well_known"):
            d.update(action="later", reason="a place with no stories yet, written in the next pass")


PASSAGE_CHARS = 2500   # of each long page, the paragraphs that name the place, before any model sees it
RECORD_CHARS = 5000    # a record page, or any short page, kept whole up to this
FOLLOWED_LINKS = 3     # of the lead page's references, read as well: records first, then press, then others


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
    # An article's references lead to what it rests on: records and scholarship first, then the press, then any
    # other site (a local history society, say), so the story has independent sources beyond the encyclopedia.
    rank = {"official_record": 0, "archive": 0, "scholarly": 0, "press": 1}
    read = {r["url"] for r in requests}
    links = [link["url"] for page in pages for link in page.get("links", [])
             if link["url"] not in read and urls.host_kind(link["url"]) != "reference"
             and not urls.problem(link["url"])]
    followed = sorted(dict.fromkeys(links), key=lambda u: rank.get(urls.host_kind(u) or "", 2))[:FOLLOWED_LINKS]
    pages += read_all(executor, [{"url": u, "title": lead["name"], "publisher": urllib.parse.urlsplit(u).netloc,
                                  "kind": urls.host_kind(u) or "community", "language": "en"} for u in followed])
    terms = " ".join([lead["name"], lead.get("what") or ""])
    # A record page is short and all about the place, so it is kept whole; a long page is cut to the paragraphs that
    # name the place, since its description may never repeat the name.
    return [{"snapshot": page["snapshot"], "kind": page["kind"], "url": page["url"],
             "text": page["text"][:RECORD_CHARS] if page["kind"] in strong or len(page["text"]) <= RECORD_CHARS
             else reading.passages(page["text"], terms, PASSAGE_CHARS)} for page in pages]


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
MIN_FACTS = 2  # a map story can rest on two facts, such as when something was made and for whom


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

    on_record = any(page["kind"] == "official_record" for page in gathered)

    def accept(answer: dict[str, Any]) -> dict[str, Any]:
        if answer.get("skip") and on_record and not kept.get("asked"):
            # A record is enough for a guide, and a place without a story still gets one: a skip over a record is
            # asked for the facts once before it stands.
            kept["asked"] = True
            raise task_cli.NotSubmitted(["the official record is enough, and a place without a story still gets a "
                                         "guide: pick the facts the record gives"])
        if answer.get("skip"):
            return {"skip": str(answer["skip"])[:300]}
        found = results.problems(EVIDENCE_SCHEMA, answer)
        if not found and not answer.get("place") and decision.get("existing"):
            answer["place"] = {"existing": decision["existing"], "ordinary": False}  # the place is known already
        if not found and not answer.get("place"):
            found = ["name the place: a new one with name, kind, size, ordinary, and wikidata or osm; or existing"]
        if found:
            raise task_cli.NotSubmitted(found)
        stats, repairs = quotes.repair(ctx.conn, answer, ctx.read)
        ctx.conn.execute("SELECT psst.record_quote_repairs(%s, %s, NULL, %s, %s, %s, '[]')",
                         (executor.token, task["id"], executor.model, spend.trace[-1], Jsonb(stats)))
        for fact in answer.get("facts") or []:
            fact["values"] = values_in(fact)  # the exact numbers and names its quotes state, never the model's own
        # A fact resting only on a reference work, or saying more than its quotes, can't stand in a story: it is
        # dropped, not sent back.
        answer["facts"] = [f for f in answer.get("facts") or [] if not reference_only(ctx.conn, f) and not unquoted(f)]
        found = verify(ctx.conn, answer["facts"], "guide")
        if found:
            raise task_cli.NotSubmitted(found)
        # Whether the facts can carry a story is the source rules' call, made here in code; whether they hold one
        # is the writer's.
        kept.update(repairs=repairs, story_allowed=not verify(ctx.conn, answer["facts"], "story"))
        return answer
    try:
        answer = dict(executor.converse("evidence", system, user, task, version(prompt), accept, ctx, spend))
    finally:
        ctx.conn.close()
    kept.pop("asked", None)
    return answer | kept


def values_in(fact: dict[str, Any]) -> list[dict[str, str]]:
    """A fact's values, taken from the words of its quotes: every number and every capitalized name, as written
    there, so each value is in its passage by construction and the prose can use only these forms. A record's
    shorthand is read as the prose will say it, with the shorthand kept as the form in the source: C19 is the
    19th century, and 1907-8 ends in 1908."""
    found: dict[str, str | None] = {}
    for evidence in fact.get("evidence", []):
        quote = evidence.get("quote", "")
        for m in CENTURY.finditer(quote):
            found.setdefault(ordinal(int(m.group(1))), m.group(0))
        for m in YEAR_RANGE.finditer(quote):
            start, end = m.group(1), m.group(2)
            found.setdefault(start, None)
            found.setdefault(start[:4 - len(end)] + end, m.group(0))
        plain = CENTURY.sub(" ", YEAR_RANGE.sub(lambda m: m.group(1) + " ", quote))  # no fragments of shorthand
        for value in VALUE_NUMBER.findall(plain) + NAME.findall(plain):
            if value not in COMMON:
                found.setdefault(value, None)
    return [{"value": v} | ({"source_form": form} if form else {}) for v, form in list(found.items())[:16]]


CENTURY = re.compile(r"\bC(\d{1,2})\b")  # a heritage record's shorthand for a century
YEAR_RANGE = re.compile(r"\b(1\d{3}|20\d{2})\s*-\s*(\d{1,2})\b(?!\d)")  # 1907-8, 1840-45


def ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def unquoted(fact: dict[str, Any]) -> bool:
    """Whether the fact's own words state a number its quotes don't: the fact says more than its source."""
    stated = {v["value"] for v in fact.get("values", [])}
    return any(n not in stated and not any(n in s for s in stated) for n in VALUE_NUMBER.findall(fact.get("text", "")))


def lengths() -> str:
    """The rulebook's length limits for what the writer writes, so the prompt never states them apart from it."""
    spec = rules.load()
    lines = []
    for kind, fields in (("story", ("headline", "short", "long", "look")), ("guide", ("identifier", "about"))):
        properties = spec.type(kind)["schema"]["properties"]
        lines += [f"- {kind} {f}: {properties[f]['minLength']} to {properties[f]['maxLength']}" for f in fields]
    return "\n".join(lines)


def single_source(facts: dict[str, dict[str, Any]]) -> bool:
    """Whether the facts rest on one source: several snapshots of the same page are one source."""
    snapshots = sorted({e["snapshot"] for f in facts.values() for e in f["evidence"]})
    with db.connect("worker") as conn:
        row = conn.execute("SELECT count(DISTINCT source_id) AS n FROM psst.snapshots WHERE id = ANY(%s)",
                           (snapshots,)).fetchone()
    return row is not None and row["n"] <= 1


def reference_only(conn: Any, fact: dict[str, Any]) -> bool:
    snapshots = [e.get("snapshot") for e in fact.get("evidence", [])]
    rows = conn.execute("""SELECT s.url, s.kind FROM psst.snapshots n JOIN psst.sources s ON s.id = n.source_id
                           WHERE n.id = ANY(%s)""", (snapshots,)).fetchall()
    kinds = rules.load().sources["kinds"]
    return bool(rows) and all(kinds.get(urls.host_kind(r["url"]) or r["kind"], {}).get("role") == "reference"
                              for r in rows)


def verify(conn: Any, facts: list[dict[str, Any]], item: str = "story") -> list[str]:
    """What is wrong with a set of facts before anything is written from them, for a story or, for a guide-only
    place, a guide."""
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
        for v in fact.get("values", []):
            if quoted and not any(contains(q, v.get("source_form") or v["value"]) for q in quoted):
                found.append(f"fact {fact.get('id')}: '{v['value']}' isn't in its quoted passages; quote the words "
                             "that state it")
    need = rulebook.sources["rules"][item]
    strong = [k for k in sources.values()
              if rulebook.sources["kinds"].get(k, {}).get("role") in rulebook.sources["strong_roles"]]
    if len(facts) < MIN_FACTS:
        found.append(f"a place needs at least {MIN_FACTS} facts; find more, or answer skip with the reason")
    on_record = need.get("map_story_on_record") and list(sources.values()) == ["official_record"]
    if len(sources) < need["min_sources"] and not on_record:  # a map story may rest on its record alone
        found.append(f"the facts rest on {len(sources)} source; a story needs {need['min_sources']} independent ones, "
                     "or the official record alone; or set story to false for a guide-only place")
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
    system = (prompt + "\n\n## Lengths, in characters\n\n" + lengths() + "\n\n## The golden bar\n\n"
              + str(document["data"].get("golden_bar") or ""))
    facts = {f["id"]: f for f in gathered["facts"]}
    one_source = single_source(facts)
    tier = "map" if one_source else decision.get("tier")  # featured keeps two independent sources (decision 35)
    guide_only = not gathered.get("story_allowed")  # the sources can't carry a story: a guide-only place
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
                                "tier": tier, "form": decision.get("form"), "guide_only": guide_only,
                                "facts": shown}}, ensure_ascii=False, default=str)
    ctx = tools.Context(conn=db.open_connection(db.conninfo("worker"), autocommit=True), token=executor.token,
                        place_id=decision.get("existing"))

    def accept(answer: dict[str, Any]) -> Any:
        if guide_only or not isinstance(answer.get("stories"), list):
            answer["stories"] = [] if guide_only else answer.get("stories")
        for story in answer.get("stories") or []:
            if isinstance(story, dict) and isinstance(story.get("body"), dict):
                # What triage planned stands when the writer leaves it out; tags are added at publishing.
                story["body"].setdefault("tier", tier or "map")
                if one_source:
                    story["body"]["tier"] = "map"
                story["body"].setdefault("form", decision.get("form") or "story")
                story["body"].setdefault("tags", [])
                story["body"].setdefault("veracity", "fact")
                story["body"].setdefault("category", "history")
        if isinstance(answer.get("guide"), dict) and isinstance(answer["guide"].get("body"), dict):
            answer["guide"]["body"].setdefault("key_facts", [])  # left empty here, as the prompt asks
        for kind, part in [*(("story", s) for s in answer.get("stories") or []), ("guide", answer.get("guide"))]:
            if isinstance(part, dict) and isinstance(part.get("body"), dict):  # fields the rulebook has no place for
                allowed = rules.load().type(kind)["schema"]["properties"]
                part["body"] = {k: v for k, v in part["body"].items() if k in allowed}
        place = assemble(gathered["place"], answer, facts)
        us_spelling(place)
        found = unsupported(place, facts, [lead["name"], (gathered["place"] or {}).get("name") or "",
                                           *task_cli.cell_areas(document["data"])])
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
          "Their", "I", "We", "You", "Your", "After", "Before", "By", "For", "With", "Over", "Under", "Above", "Below",
          # periods and styles describe a date or a look the facts give, and the country is never in doubt
          "Victorian", "Edwardian", "Georgian", "Regency", "Tudor", "Jacobean", "Elizabethan", "Gothic", "Baroque",
          "Classical", "Italianate", "Romanesque", "Renaissance", "Revival", "Art", "Deco", "Modernist",
          "England", "English", "Britain", "British"}


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
        d["existing"] = d.get("existing") or lead.get("existing")  # the place a lead already became, if any
        try:
            gathered = evidence(writer, task, document, d, lead, Spend())
            if gathered.get("skip"):
                return {"lead": d["lead"], "status": "skipped",
                        "reason": f"the evidence isn't there: {gathered['skip']}"[:300]}
            known = gathered.get("place") or {}
            for key in ("wikidata", "osm"):  # the lead's own identifiers, when the evidence step left them out
                if "existing" not in known and lead.get(key) and not known.get(key):
                    known[key] = lead[key]
            if d["existing"]:  # a place the platform has keeps its identity, whatever the evidence step named
                gathered["place"] = {"existing": d["existing"],
                                     "ordinary": bool((gathered.get("place") or {}).get("ordinary"))}
            placed = write(prose_writer(writer), task, document, d, lead, gathered, Spend())
        except (GaveUp, ValueError, TypeError, KeyError, OSError, psycopg.Error) as reason:
            # One place that fails, for any reason, is given back; the rest of the cell goes on.
            return {"lead": d["lead"], "status": "skipped" if lead.get("well_known") else "later",
                    "reason": f"couldn't be written to the bar: {reason}"[:300]}
        return {"lead": d["lead"], "status": "added", "existing": placed["place"]}

    with ThreadPoolExecutor(max_workers=parallel_places()) as pool:
        written = list(pool.map(place, range(len(chosen)), chosen))
    accounted += written
    # A pass ends here: leads left open or later stay with the cell, and the cell is queued again for its next pass.
    # Leads the place submissions already settled need no entry; the rest are accounted for here.
    final = {"places": [], "leads": [a for a in accounted if a["status"] != "added"],
             "notes": (plan.get("notes") or "Triaged and written by the harness.")[:600]}
    failed = sum(w["reason"].startswith("couldn't be written") for w in written if w["status"] != "added")
    return dict(task_cli.submit(document, final)) | {"chosen": len(chosen), "failed": failed}


def parallel_places() -> int:
    with db.connect("worker") as conn:
        row = conn.execute("SELECT psst.setting('harness.parallel_places') #>> '{}' AS n").fetchone()
    return max(1, int(row["n"])) if row and row["n"] else 8


def us_spelling(place: dict[str, Any]) -> None:
    """The words the rulebook lists as British take their US form in the prose (storeys becomes stories): a
    mechanical change that never alters a fact, made in code rather than paid for as a fix round."""
    british = rules.load().writing["british_spellings"]
    pattern = re.compile(r"\b(" + "|".join(map(re.escape, sorted(british, key=len, reverse=True))) + r")\b")
    for part in [*place.get("stories", []), place.get("guide") or {}]:
        body = part.get("body") or {}
        for key, value in body.items():
            if isinstance(value, str):
                body[key] = pattern.sub(lambda m: british[m.group(1)], value)

