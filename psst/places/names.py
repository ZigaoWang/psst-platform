"""Names in other languages from Wikidata labels and OpenStreetMap name tags. Never machine translated.

`local` is the name on the signs, in the country's sign language, when it differs from the English name. `alt`
holds established names in other languages.
"""

from __future__ import annotations

import re
import urllib.error
from typing import Any

from psst import rules
from psst.core import http

HAN = re.compile(r"[㐀-鿿]")


def osm_tags(refs: list[str]) -> dict[str, dict[str, str]]:
    """Tags for OSM elements, through the main API (faster than Overpass when only tags are needed)."""
    found: dict[str, dict[str, str]] = {}
    by_type: dict[str, list[str]] = {}
    for ref in refs:
        kind, number = ref.split("/")
        by_type.setdefault(kind, []).append(number)
    for kind, numbers in by_type.items():
        for start in range(0, len(numbers), 100):
            chunk = numbers[start:start + 100]
            try:
                url = f"https://api.openstreetmap.org/api/0.6/{kind}s.json?{kind}s=" + ",".join(chunk)
                payload = http.get_json(url, attempts=3)
            except (ConnectionError, urllib.error.HTTPError):
                continue
            for element in payload.get("elements", []):
                found[f"{element['type']}/{element['id']}"] = element.get("tags", {})
    return found


def collect(place: dict[str, Any], labels: dict[str, Any], tags: dict[str, str]) -> list[dict[str, str]]:
    """Name rows for one place, given its display name, existing local name, country, Wikidata labels, and OSM
    tags."""
    spec = rules.load().places
    names: dict[str, tuple[str, str]] = {}
    for lang, codes in spec["name_languages"].items():
        for code in codes:
            if code in labels:
                names[lang] = (labels[code]["value"], "wikidata")
                break
    for lang, keys in spec["osm_name_keys"].items():
        for key in keys:
            if key in tags and lang not in names:
                names[lang] = (tags[key], "osm")
                break
    for key, value in tags.items():
        match = re.fullmatch(r"name:([a-z]{2})", key)
        if match and match.group(1) in spec["name_languages"] and match.group(1) not in names:
            names[match.group(1)] = (value, "osm")
    same = lambda a, b: a.casefold().strip() == b.casefold().strip()  # noqa: E731
    rows: list[dict[str, str]] = []
    sign = spec["sign_language"].get(place.get("country") or "")
    if not place.get("local") and sign and sign != "en":
        candidate = names.get(sign)
        # OSM's plain name counts only when its script proves its language (Chinese characters, no Latin).
        plain = tags.get("name", "")
        if not candidate and HAN.search(plain) and not re.search(r"[A-Za-z]", plain):
            candidate = (plain, "osm")
        if candidate and not same(candidate[0], place["display"]):
            rows.append({"role": "local", "lang": sign, "name": candidate[0], "source": candidate[1]})
    for lang, (name, source) in names.items():
        if not (lang == "en" and same(name, place["display"])):
            rows.append({"role": "alt", "lang": lang, "name": name, "source": source})
    return rows
