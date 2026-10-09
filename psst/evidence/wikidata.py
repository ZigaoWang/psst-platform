"""A Wikidata item as evidence: its key-fact values read the way a guide shows them, saved as plain lines so a
key fact quotes its line like any other passage. A value the sanity checks find implausible carries the reason
on its line, and a key fact quoting a flagged line needs a second passage from another source.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from psst import rules
from psst.core import http

ENTITY_URL = re.compile(r"^https://(?:www\.)?wikidata\.org/wiki/(Q[1-9][0-9]*)$")
MAX_VALUES = 3
CIRCA = "Q5727902"
HUMAN = "Q5"
# What a style should be (or be a kind of): an architectural style, an art movement or style, or a style.
STYLE_CLASSES = {"Q32880", "Q968159", "Q1792644", "Q1292119", "Q2198855"}
# Wikidata's units for lengths and areas, as (metric unit, factor).
UNITS = {
    "Q11573": ("m", 1.0), "Q828224": ("km", 1.0), "Q174728": ("m", 0.01), "Q3710": ("m", 0.3048),
    "Q482798": ("m", 0.9144), "Q253276": ("km", 1.609344), "Q174789": ("m", 0.001),
    "Q25343": ("m²", 1.0), "Q35852": ("ha", 1.0), "Q712226": ("km²", 1.0), "Q81292": ("ha", 0.40468564),
    "Q857027": ("m²", 0.09290304), "Q232291": ("km²", 2.58998811),
}
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]


def claims(entity: dict[str, Any], prop: str) -> list[dict[str, Any]]:
    """Preferred claims if any, else normal ones; never deprecated, unknown, or ended (a former operator)."""
    found = [c for c in entity.get("claims", {}).get(prop, [])
             if c.get("rank") != "deprecated" and c.get("mainsnak", {}).get("snaktype") == "value"
             and not c.get("qualifiers", {}).get("P582")]
    preferred = [c for c in found if c.get("rank") == "preferred"]
    return preferred or found


def year_of(value: dict[str, Any]) -> int | None:
    match = re.match(r"^([+-])(\d+)-", value.get("time", ""))
    if not match:
        return None
    return -int(match.group(2)) if match.group(1) == "-" else int(match.group(2))


def format_time(value: dict[str, Any], circa: bool = False) -> str | None:
    """A time as people write it, at the precision Wikidata gives ("May 12, 1843", "1840s", "17th century")."""
    match = re.match(r"^([+-])(\d+)-(\d\d)-(\d\d)", value.get("time", ""))
    if not match:
        return None
    sign, year, month, day = match.group(1), int(match.group(2)), int(match.group(3)), int(match.group(4))
    precision = value.get("precision", 9)
    era = " BC" if sign == "-" else ""
    if precision >= 11 and month and day:
        text = f"{MONTHS[month - 1]} {day}, {year}{era}"
    elif precision == 10 and month:
        text = f"{MONTHS[month - 1]} {year}{era}"
    elif precision == 9:
        text = f"{year}{era}"
    elif precision == 8:
        text = f"{year // 10 * 10}s{era}"
    elif precision == 7:
        century = (year - 1) // 100 + 1
        suffix = "th" if 10 <= century % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(century % 10, "th")
        text = f"{century}{suffix} century{era}"
    else:
        return None
    return f"about {text}" if circa and precision >= 9 else text


def _quantity(value: dict[str, Any], kind: str) -> tuple[str, float] | None:
    try:
        amount = float(value["amount"])
    except (KeyError, ValueError):
        return None
    unit = value.get("unit", "1").rsplit("/", 1)[-1]
    if kind == "count":
        return (f"{amount:,.0f}", amount) if unit == "1" and amount == int(amount) else None
    if unit not in UNITS:
        return None
    symbol, factor = UNITS[unit]
    if (kind == "length") != (symbol in ("m", "km")):
        return None
    amount *= factor
    shown = f"{amount:,.0f}" if abs(amount) >= 100 else f"{amount:.1f}".rstrip("0").rstrip(".")
    return f"{shown} {symbol}", amount


def label(entity: dict[str, Any] | None) -> str | None:
    labels = (entity or {}).get("labels", {})
    for code in ("en", "en-us", "en-gb", "mul"):
        if code in labels:
            return str(labels[code]["value"])
    return None


def _classes(entity: dict[str, Any], prop: str = "P31") -> set[str]:
    return {c["mainsnak"].get("datavalue", {}).get("value", {}).get("id")
            for c in entity.get("claims", {}).get(prop, [])} - {None}


def key_facts(entity: dict[str, Any], values: dict[str, Any], kind: str = "building", size: str = "medium",
              today: date | None = None) -> list[dict[str, Any]]:
    """The item's key-fact values, each sanity checked; a value that can't be shown plainly is left out."""
    spec = rules.load().type("guide")
    this_year = (today or date.today()).year
    found: list[dict[str, Any]] = []
    for definition in spec["key_facts"]:
        prop, value_kind = definition["property"], definition["kind"]
        kept: list[dict[str, Any]] = []
        for claim in claims(entity, prop)[:MAX_VALUES]:
            value = claim["mainsnak"]["datavalue"]["value"]
            fact: dict[str, Any] | None = None
            if value_kind in ("person", "item") and isinstance(value, dict) and value.get("id"):
                name = label(values.get(value["id"]))
                if name:
                    if prop == "P149":
                        name = re.sub(r" architecture$", "", name)
                    fact = {"value": name[0].upper() + name[1:], "value_id": value["id"]}
            elif value_kind == "date" and isinstance(value, dict):
                circa = any(q.get("datavalue", {}).get("value", {}).get("id") == CIRCA
                            for q in claim.get("qualifiers", {}).get("P1480", []))
                text = format_time(value, circa)
                if text:
                    fact = {"value": text, "year": year_of(value)}
            elif value_kind in ("length", "area", "count") and isinstance(value, dict):
                quantity = _quantity(value, value_kind)
                if quantity:
                    fact = {"value": quantity[0], "amount": quantity[1]}
            if fact and fact["value"] not in [k["value"] for k in kept]:
                kept.append({"property": prop, "label": definition["label"], "flags": [], **fact})
        if value_kind in ("date", "length", "area", "count") and len(kept) > 1:
            kept[0]["flags"].append("Wikidata gives several values: " + ", ".join(k["value"] for k in kept))
            kept = kept[:1]
        found.extend(kept)
    _sanity_check(found, values, kind, size, this_year)
    return found


def _sanity_check(found: list[dict[str, Any]], values: dict[str, Any], kind: str, size: str, this_year: int) -> None:
    built = next((f["year"] for f in found if f["property"] == "P571" and f.get("year") is not None), None)
    opened = next((f["year"] for f in found if f["property"] == "P1619" and f.get("year") is not None), None)
    kinds = {d["property"]: d["kind"] for d in rules.load().type("guide")["key_facts"]}
    for fact in found:
        flags = fact["flags"]
        year = fact.get("year")
        if year is not None and year > this_year:
            flags.append(f"{year} is in the future")
        elif year is not None and year < -3000:
            flags.append(f"{fact['value']} is older than almost anything standing")
        if fact["property"] == "P1619" and built is not None and opened is not None and opened < built:
            flags.append(f"opened in {opened}, before it was built in {built}")
        amount = fact.get("amount")
        if amount is not None:
            limits = {"P2048": (0, 830), "P2043": (0, 60_000 if fact["value"].endswith(" m") else 60),
                      "P2044": (-500, 9000), "P1101": (0, 170), "P1083": (0, 200_000)}
            low, high = limits.get(fact["property"], (0, float("inf")))
            if fact["property"] == "P2046":
                high = 2_000_000 if fact["value"].endswith(" m²") else 20_000 if fact["value"].endswith(" ha") else 200
            if not low < amount <= high:
                flags.append(f"{fact['value']} is implausible for one place")
            elif fact["property"] == "P2048" and (size == "small" or kind == "memorial") and amount > 60:
                flags.append(f"{fact['value']} is very tall for a {size} {kind}")
        target = values.get(fact.get("value_id") or "", {})
        if fact["property"] == "P149" and not STYLE_CLASSES & (_classes(target) | _classes(target, "P279")):
            flags.append(f"{fact['value']} isn't recorded on Wikidata as a style")
        if kinds[fact["property"]] == "person" and built is not None and HUMAN in _classes(target):
            born = [year_of(c["mainsnak"]["datavalue"]["value"]) for c in claims(target, "P569")]
            died = [year_of(c["mainsnak"]["datavalue"]["value"]) for c in claims(target, "P570")]
            if born and born[0] is not None and born[0] > built:
                flags.append(f"born in {born[0]}, after it was built in {built}")
            elif died and died[0] is not None and died[0] < built - 25:
                flags.append(f"died in {died[0]}, {built - died[0]} years before it was built in {built}")


def fetch(qid: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """The item, and the items its values point at (labels, plus life dates and classes where checks need them)."""
    entity = http.wikidata_entities([qid], props="labels|claims|sitelinks").get(qid)
    if not entity:
        raise LookupError(f"{qid} isn't on Wikidata")
    targets = {c["mainsnak"]["datavalue"]["value"]["id"]
               for d in rules.load().type("guide")["key_facts"] if d["kind"] in ("person", "item")
               for c in claims(entity, d["property"])[:MAX_VALUES]
               if isinstance(c["mainsnak"]["datavalue"]["value"], dict)
               and c["mainsnak"]["datavalue"]["value"].get("id")}
    targets |= {c["mainsnak"]["datavalue"]["value"]["id"] for c in claims(entity, "P31")[:3]}
    return entity, http.wikidata_entities(sorted(targets), props="labels|claims") if targets else {}


def render(qid: str, entity: dict[str, Any], values: dict[str, Any], kind: str = "building",
           size: str = "medium") -> str:
    """The text a Wikidata snapshot holds: the item's label and what it is, then one line per key-fact value."""
    lines = [f"Wikidata item {qid}: {label(entity) or qid}"]
    what = [label(values.get(c["mainsnak"]["datavalue"]["value"]["id"])) for c in claims(entity, "P31")[:3]]
    if any(what):
        lines.append("instance of: " + ", ".join(w for w in what if w))
    for fact in key_facts(entity, values, kind, size):
        line = f"{fact['label']} ({fact['property']}): {fact['value']}"
        if fact["flags"]:
            line += " [flagged: " + "; ".join(fact["flags"]) + "]"
        lines.append(line)
    return "\n".join(lines)
