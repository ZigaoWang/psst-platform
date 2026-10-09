"""The tool checks (design.md, section 7.2): everything about a revision that code can decide, run before any
model sees it. Pure functions over the revision, the snapshots it cites, and a little context, so the writer's
CLI and the system worker run exactly the same code.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

import jsonschema

from psst import rules
from psst.core.text import contains, find_quote, fold, words
from psst.evidence import urls
from psst.rules import Rulebook, writing
from psst.rules.report import Report


@dataclass
class Evidence:
    snapshot: str
    quote: str
    id: int | None = None


@dataclass
class Claim:
    n: int
    text: str
    kind: str
    values: list[dict[str, str]]
    evidence: list[Evidence]
    role: str = "fact"


@dataclass
class Snapshot:
    id: str
    source: str
    url: str
    kind: str
    text: str


@dataclass
class Stop:
    lat: float
    lon: float
    published: bool


@dataclass
class Context:
    """What the checks need to know beyond the revision itself."""
    names: list[str] = field(default_factory=list)          # the place's names and its areas' names
    tags: set[str] = field(default_factory=set)              # tag ids that exist
    stops: dict[str, Stop] = field(default_factory=dict)     # trail stops by place id
    photo_pairs: set[str] = field(default_factory=set)       # current photo items of the same place
    source_type: str | None = None                           # for a translation: the type it translates
    source_body: dict[str, Any] | None = None                # for a translation: the body it translates


@dataclass
class Result:
    report: Report
    matches: list[dict[str, int | None]]                     # {evidence, start, end} for every evidence row

    @property
    def ok(self) -> bool:
        return self.report.ok


def check(item_type: str, body: dict[str, Any], claims: list[Claim], snapshots: dict[str, Snapshot],
          context: Context | None = None, rulebook: Rulebook | None = None) -> Result:
    rulebook = rulebook or rules.load()
    context = context or Context()
    report = Report()
    if item_type == "translation":
        _translation(report, body, context, rulebook)
        return Result(report, [])
    spec = rulebook.type(item_type)
    errors = sorted(jsonschema.Draft202012Validator(spec["schema"]).iter_errors(body), key=lambda e: list(e.path))
    for error in errors:
        report.refuse("body" + "".join(f"[{p!r}]" for p in error.path), error.message)
    if errors:
        return Result(report, [])

    prose = _prose(item_type, body, spec)
    for where, text in prose.items():
        writing.check_prose(report, where, text, rulebook)
    getattr(_Shapes, item_type)(report, body, spec, context, rulebook)

    matches, quotes_by_claim = _match_quotes(report, claims, snapshots)
    if item_type != "photo":
        _trace(report, prose, claims, quotes_by_claim, context)
        _own_words(report, prose, claims, snapshots, rulebook)
        _paraphrase(report, prose, claims, snapshots, rulebook)
        _repeats(report, prose)
    if item_type == "story":
        _look(report, body)
    _sources(report, item_type, body, claims, quotes_by_claim, snapshots, rulebook)
    return Result(report, matches)


def _prose(item_type: str, body: dict[str, Any], spec: dict[str, Any]) -> dict[str, str]:
    prose = {f: body[f] for f in spec["prose_fields"] if isinstance(body.get(f), str)}
    if item_type == "trail":
        for index, stop in enumerate(body["stops"]):
            prose[f"stops[{index}].note"] = stop["note"]
    return prose


# Passages ---------------------------------------------------------------------------------------------------

def _match_quotes(report: Report, claims: list[Claim], snapshots: dict[str, Snapshot]
                  ) -> tuple[list[dict[str, int | None]], dict[int, list[tuple[Snapshot, str]]]]:
    """Find every quote in its snapshot. Returns the match for each evidence row and, per claim, the matched
    passages with their snapshots."""
    matches: list[dict[str, int | None]] = []
    found: dict[int, list[tuple[Snapshot, str]]] = {}
    for claim in claims:
        if not claim.evidence:
            report.refuse(f"claim {claim.n}", "has no evidence")
        for proof in claim.evidence:
            snapshot = snapshots.get(proof.snapshot)
            span = find_quote(snapshot.text, proof.quote) if snapshot else None
            if snapshot is None:
                report.refuse(f"claim {claim.n}", f"cites snapshot {proof.snapshot}, which doesn't exist")
            elif span is None:
                report.refuse(f"claim {claim.n}", f"the quote isn't in snapshot {proof.snapshot}: "
                                                  f"\"{proof.quote[:80]}\"")
            else:
                found.setdefault(claim.n, []).append((snapshot, snapshot.text[span[0]:span[1]]))
            if proof.id is not None:
                matches.append({"evidence": proof.id, "start": span[0] if span else None,
                                "end": span[1] if span else None})
    return matches, found


# Details trace ----------------------------------------------------------------------------------------------

NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?(?:s|st|nd|rd|th)?(?![\w])")


def numbers(text: str) -> list[str]:
    """The years and numbers written in digits, in order. Names and other details are a matter of language, so
    the whole-item check (a model) traces those instead (design.md, section 7.4)."""
    return [m.group(0).replace(",", "") for m in NUMBER.finditer(text)]


def _trace(report: Report, prose: dict[str, str], claims: list[Claim],
           quotes: dict[int, list[tuple[Snapshot, str]]], context: Context) -> None:
    known = [v["value"].replace(",", "") for c in claims for v in c.values] + context.names
    for where, text in prose.items():
        for number in numbers(text):
            if not any(number in k for k in known):
                report.refuse(where, f"'{number}' isn't among the claims' values; add the claim it belongs to")
    pages = {snapshot.id: snapshot.text for found in quotes.values() for snapshot, _ in found}
    cited = set(words(" ".join(pages.values()) + " " + " ".join(context.names)))
    for where, text in prose.items():
        missing = sorted({n for n in proper_names(text) if not set(words(n)) <= cited})
        if missing:
            report.refuse(where, f"{', '.join(repr(n) for n in missing)} isn't in any cited passage; "
                                 "cite where it comes from or leave it out")
    for claim in claims:
        passages = [p for _, p in quotes.get(claim.n, [])]
        for value in claim.values:
            form = value.get("source_form") or value["value"]
            if passages and not any(contains(p, form) or contains(p.replace(",", ""), form.replace(",", ""))
                                    for p in passages):
                report.refuse(f"claim {claim.n}", f"'{form}' isn't in any of its passages")


CAPITAL_WORD = re.compile(r"(?<![\w'’-])[A-Z][\w'’]*")
SENTENCE_START = re.compile(r"(?:^|[.!?:;]\s+|[\"“(]\s*)$")


def proper_names(text: str) -> list[str]:
    """Each capitalized word, except one that only starts a sentence (a sentence's first word counts when the next
    word is capitalized too, as in a name)."""
    found = list(CAPITAL_WORD.finditer(text))
    names = []
    for index, match in enumerate(found):
        following = found[index + 1] if index + 1 < len(found) else None
        starts = SENTENCE_START.search(text[:match.start()]) is not None
        joined = following is not None and text[match.end():following.start()] == " "
        if len(match.group(0)) > 1 and (not starts or joined):
            names.append(match.group(0))
    return names


# Own words --------------------------------------------------------------------------------------------------

QUOTED = re.compile(r"\"[^\"]*\"")


def _own_words(report: Report, prose: dict[str, str], claims: list[Claim], snapshots: dict[str, Snapshot],
               rulebook: Rulebook) -> None:
    size = int(rulebook.writing["max_shared_words"]) + 1
    cited = {p.snapshot for c in claims for p in c.evidence if p.snapshot in snapshots}
    runs: dict[tuple[str, ...], str] = {}
    for snapshot_id in cited:
        source_words = words(snapshots[snapshot_id].text)
        for i in range(len(source_words) - size + 1):
            runs.setdefault(tuple(source_words[i:i + size]), snapshot_id)
    for where, text in prose.items():
        own = words(QUOTED.sub(" | ", fold(text)[0]))
        for i in range(len(own) - size + 1):
            shared = tuple(own[i:i + size])
            if shared in runs:
                report.refuse(where, f"copies \"{' '.join(shared)}\" from snapshot {runs[shared]}; "
                                     "write it in your own words or quote it")
                break


SENTENCE = re.compile(r"[^.!?]+[.!?]?")


def _content(text: str) -> set[str]:
    """Words of four letters or more, without names: a shared name is a fact, not a copied sentence."""
    names = {w.casefold() for w in CAPITAL_WORD.findall(text)}
    return {w for w in words(text) if len(w) >= 4 and w.isalpha() and w not in names}


def _paraphrase(report: Report, prose: dict[str, str], claims: list[Claim], snapshots: dict[str, Snapshot],
                rulebook: Rulebook) -> None:
    """No sentence of the prose repeats most of the words of one source sentence, even reworded."""
    share = float(rulebook.writing["max_sentence_overlap"])
    least = int(rulebook.writing["min_overlap_words"])
    cited = {p.snapshot for c in claims for p in c.evidence if p.snapshot in snapshots}
    index: dict[str, set[int]] = {}
    sentences: list[tuple[set[str], str]] = []
    for snapshot_id in sorted(cited):
        for match in SENTENCE.finditer(snapshots[snapshot_id].text):
            found = _content(match.group(0))
            if len(found) >= least:
                sentences.append((found, snapshot_id))
                for word in found:
                    index.setdefault(word, set()).add(len(sentences) - 1)
    for where, text in prose.items():
        for match in SENTENCE.finditer(QUOTED.sub(" ", text)):
            own = _content(match.group(0))
            if len(own) < least:
                continue
            counts: dict[int, int] = {}
            for word in own:
                for sentence in index.get(word, ()):
                    counts[sentence] = counts.get(sentence, 0) + 1
            best = max(counts.items(), key=lambda kv: kv[1] / len(sentences[kv[0]][0]), default=None)
            if best and best[1] >= share * len(own) and best[1] >= 0.5 * len(sentences[best[0]][0]):
                report.refuse(where, f"\"{match.group(0).strip()}\" repeats a sentence of snapshot "
                                     f"{sentences[best[0]][1]} in other words; tell it your own way")


def _repeats(report: Report, prose: dict[str, str]) -> None:
    """Say it once: no sentence repeats another anywhere in the item, word for word or nearly (most of its words in
    both directions), the short and the long included."""
    sentences = [(where, m.group(0).strip(), set(words(m.group(0))))
                 for where, text in prose.items() for m in SENTENCE.finditer(text)]
    sentences = [s for s in sentences if len(s[2]) >= 6]
    for i, (where, _, own) in enumerate(sentences):
        for other_where, other_text, other in sentences[i + 1:]:
            shared = len(own & other)
            if shared >= 0.8 * len(own) and shared >= 0.8 * len(other):
                report.refuse(other_where, f"\"{other_text}\" says again what {where} already says; say it once")


def _look(report: Report, body: dict[str, Any]) -> None:
    """The look points at something the story is about: it shares a word of five letters or more with the story."""
    def long_words(text: str) -> set[str]:
        return {w for w in words(text) if len(w) >= 5 and w.isalpha()}
    look = long_words(body.get("look") or "")
    if look and not look & long_words(" ".join(body[f] for f in ("headline", "short", "long"))):
        report.refuse("look", "names nothing the story is about; point at the thing the story describes")


# Source rules -----------------------------------------------------------------------------------------------

def _role(snapshot: Snapshot, rulebook: Rulebook) -> str:
    return str(rulebook.sources["kinds"][urls.host_kind(snapshot.url) or snapshot.kind]["role"])


def _sources(report: Report, item_type: str, body: dict[str, Any], claims: list[Claim],
             quotes: dict[int, list[tuple[Snapshot, str]]], snapshots: dict[str, Snapshot], rulebook: Rulebook) -> None:
    need = rulebook.sources["rules"][item_type]
    strong = set(rulebook.sources["strong_roles"])
    used = {s.source: s for passages in quotes.values() for s, _ in passages}
    if len(used) < need["min_sources"]:
        report.refuse("sources", f"needs at least {need['min_sources']} independent sources; has {len(used)}")
    strong_sources = [s for s in used.values() if _role(s, rulebook) in strong]
    if len(strong_sources) < need["min_strong_sources"]:
        report.refuse("sources", "needs a primary record or scholarly source, not only press, community, or "
                                 "reference works")
    for claim in claims:
        passages = quotes.get(claim.n, [])
        roles = {_role(s, rulebook) for s, _ in passages}
        if need["non_reference_per_claim"] and passages and roles <= {"reference"}:
            report.refuse(f"claim {claim.n}", "rests only on reference works; find the record they draw on")
    if item_type == "guide":
        _key_facts(report, body, claims, quotes, rulebook)
    if item_type != "story":
        return
    myths = [c for c in claims if c.role == "myth"]
    if body.get("myth"):
        if not myths:
            report.refuse("myth", "needs a claim with the role 'myth' citing a source that tells the popular version")
        corrections = [c for c in claims if c.role == "fact"
                       and any(_role(s, rulebook) in strong for s, _ in quotes.get(c.n, []))]
        if not corrections:
            report.refuse("myth", "the correction needs a claim backed by a primary record or scholarly source")
    elif myths:
        report.refuse("claims", "claims with the role 'myth' belong to a story with a 'myth' field")
    if body.get("veracity") == "fact":
        # Whatever its kind, a claim resting on one press or community source is an anecdote, and an anecdote with one
        # source is a legend (content.md, section 4.1).
        for claim in claims:
            if claim.role != "fact":
                continue
            passages = quotes.get(claim.n, [])
            if not any(_role(s, rulebook) in strong for s, _ in passages) and len({s.source for s, _ in passages}) < 2:
                report.refuse(f"claim {claim.n}", "rests on one press or community source, which makes it a legend: "
                                                  "corroborate it with a record or a second source, or mark the story "
                                                  "'legend'")


def _key_facts(report: Report, body: dict[str, Any], claims: list[Claim],
               quotes: dict[int, list[tuple[Snapshot, str]]], rulebook: Rulebook) -> None:
    """Each key fact names the claim that backs it, with the same value. A value Wikidata's sanity checks flagged
    needs a passage from another source too (design.md, section 7.6)."""
    by_n = {c.n: c for c in claims}
    for index, fact in enumerate(body["key_facts"]):
        claim = by_n.get(fact["claim"])
        where = f"key_facts[{index}]"
        if claim is None:
            report.refuse(where, f"names claim {fact['claim']}, which doesn't exist")
            continue
        if not any(contains(v["value"], fact["value"]) or contains(fact["value"], v["value"]) for v in claim.values):
            report.refuse(where, f"'{fact['value']}' isn't among claim {claim.n}'s values")
        passages = quotes.get(claim.n, [])
        flagged = any("[flagged" in _line(snapshot.text, passage) for snapshot, passage in passages)
        if flagged and all(_role(snapshot, rulebook) == "reference" for snapshot, _ in passages):
            report.refuse(where, "Wikidata's value is flagged as implausible; back it with another source or drop it")


def _line(text: str, passage: str) -> str:
    at = text.find(passage)
    if at < 0:
        return ""
    return text[text.rfind("\n", 0, at) + 1:(text.find("\n", at) + 1 or len(text) + 1) - 1]


# Type shapes ------------------------------------------------------------------------------------------------

YEAR = re.compile(r"\b(\d{3,4})s?\b")


class _Shapes:
    @staticmethod
    def story(report: Report, body: dict[str, Any], spec: dict[str, Any], context: Context,
              rulebook: Rulebook) -> None:
        for mark in spec["headline_refuses"]:
            if mark in body["headline"]:
                report.refuse("headline", f"contains '{mark}'")
        if body["veracity"] == "legend":
            text = (body["short"] + " " + body["long"]).lower()
            if not any(marker in text for marker in spec["legend_markers"]):
                report.refuse("long", "a legend says it's a story people tell (\"the story goes\", \"locals say\")")
        for tag in body["tags"]:
            if context.tags and tag not in context.tags:
                report.refuse("tags", f"{tag} doesn't exist")

    @staticmethod
    def guide(report: Report, body: dict[str, Any], spec: dict[str, Any], context: Context,
              rulebook: Rulebook) -> None:
        identifier, about = body["identifier"], body["about"]
        writing.check_neutral(report, "identifier", identifier, rulebook)
        writing.check_neutral(report, "about", about, rulebook)
        if not re.match(spec["identifier_shape"], identifier):
            report.refuse("identifier", "isn't in the shape '[style or material] <what it is>, <year>[, by <maker>]'")
        for refusal in spec["identifier_refuses"]:
            if re.search(refusal["pattern"], identifier):
                report.refuse("identifier", refusal["reason"])
        sentences = writing.count_sentences(about)
        limits = spec["about_sentences"]
        if not limits["min"] <= sentences <= limits["max"]:
            report.refuse("about", f"has {sentences} sentences; the About has {limits['min']} to {limits['max']}")
        if not about.endswith((".", '."', ".”", ")")):
            report.refuse("about", "ends with a period")
        dated = [kf["value"] for kf in body["key_facts"] if kf["property"] in ("P571", "P1619")]
        year = YEAR.search(identifier)
        if year and dated and not any(year.group(1) in value for value in dated):
            report.refuse("identifier", f"gives {year.group(1)}, but the key facts date it {', '.join(dated)}")
        pairs = [(kf["property"], kf["value"]) for kf in body["key_facts"]]
        if len(pairs) != len(set(pairs)):
            report.refuse("key_facts", "lists the same value twice")

    @staticmethod
    def photo(report: Report, body: dict[str, Any], spec: dict[str, Any], context: Context,
              rulebook: Rulebook) -> None:
        if body["kind"] == "historic" and "year" not in body:
            report.refuse("year", "a historic photo needs the year it was taken")
        if body["kind"] == "photo" and "pair" in body:
            report.refuse("pair", "only a historic photo is paired with a current one")
        if "pair" in body and body["pair"] not in context.photo_pairs:
            report.refuse("pair", "must be a current photo of the same place")
        alt = body["alt"].lower()
        for opening in spec["alt_refuses"]:
            if alt.startswith(opening):
                report.refuse("alt", f"starts with '{opening}'; screen readers already say it's an image")
        license_name = body["credit"]["license"].lower()
        if not any(license_name.startswith(free) for free in spec["free_licenses"]):
            report.refuse("credit.license", f"'{body['credit']['license']}' isn't a free license")
        if re.search(r"\b(nc|nd)\b", license_name):
            report.refuse("credit.license", "non-commercial and no-derivatives licenses aren't allowed")

    @staticmethod
    def trail(report: Report, body: dict[str, Any], spec: dict[str, Any], context: Context,
              rulebook: Rulebook) -> None:
        places = [stop["place"] for stop in body["stops"]]
        if len(places) != len(set(places)):
            report.refuse("stops", "visits a place twice")
        total = 0.0
        previous: Stop | None = None
        for index, place in enumerate(places):
            stop = context.stops.get(place)
            if stop is None or not stop.published:
                report.refuse(f"stops[{index}]", f"{place} has no published stories")
                previous = None
                continue
            if previous:
                leg = _meters(previous, stop)
                total += leg
                if leg > spec["max_leg_meters"]:
                    report.refuse(f"stops[{index}]", f"is {leg:.0f} m from the stop before; at most "
                                                     f"{spec['max_leg_meters']} m")
            previous = stop
        if total > spec["max_total_meters"]:
            report.refuse("stops", f"the walk is {total:.0f} m; at most {spec['max_total_meters']} m")
        for tag in body["tags"]:
            if context.tags and tag not in context.tags:
                report.refuse("tags", f"{tag} doesn't exist")


def _meters(a: Stop, b: Stop) -> float:
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat, dlon = lat2 - lat1, math.radians(b.lon - a.lon)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


# Translations -----------------------------------------------------------------------------------------------

DIGITS = re.compile(r"\d+(?:[.,]\d+)*")


def _translation(report: Report, body: dict[str, Any], context: Context, rulebook: Rulebook) -> None:
    spec = rulebook.type("translation")
    if context.source_type is None or context.source_body is None:
        report.refuse("translation", "the revision it translates is missing")
        return
    source = context.source_body
    fields = [f for f in spec["fields"][context.source_type] if f != "stop_notes" and source.get(f)]
    language = body.get("language", "zh-Hans")
    expected = set(fields) | {"language"} | ({"stop_notes"} if context.source_type == "trail" else set())
    for name in sorted(set(body) - expected):
        report.refuse(name, "isn't a field of the text it translates")
    pairs: list[tuple[str, str, str]] = []
    for name in fields:
        text = body.get(name)
        if not isinstance(text, str) or not text.strip():
            report.refuse(name, "is missing")
            continue
        pairs.append((name, source[name], text))
    if context.source_type == "trail":
        notes = body.get("stop_notes")
        stops = source.get("stops", [])
        if not isinstance(notes, list) or len(notes) != len(stops):
            report.refuse("stop_notes", f"needs one note per stop ({len(stops)})")
        else:
            for i, (stop, note) in enumerate(zip(stops, notes, strict=True)):
                pairs.append((f"stop_notes[{i}]", stop["note"], note))
    for where, english, translated in pairs:
        for character, what in spec["refused_characters"].get(language, {}).items():
            if character in translated:
                report.refuse(where, f"contains {what}")
        if sorted(n.replace(",", "") for n in DIGITS.findall(english)) != \
           sorted(n.replace(",", "") for n in DIGITS.findall(translated)):
            report.refuse(where, "its numbers differ from the English")
        if len(translated) > len(english) * spec["max_length_ratio"]:
            report.refuse(where, "is much longer than the English")
