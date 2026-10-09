"""Candidates and their records from Wikimedia Commons, which hosts the place's Wikidata image, its category, and
millions of geotagged photos (Geograph's archive among them). Credits and licenses always come from the file's own
metadata on Commons, never from a person."""

from __future__ import annotations

import html
import re
import urllib.error
import urllib.parse
from typing import Any

from psst import rules
from psst.core import http

API = "https://commons.wikimedia.org/w/api.php?format=json&maxlag=5&"


def _query(params: dict[str, str]) -> dict[str, Any]:
    return dict(http.get_json(API + urllib.parse.urlencode(params), attempts=4))


def _plain(value: str | None) -> str:
    """Commons metadata is HTML; credits are shown as plain text."""
    text = re.sub(r"<[^>]+>", "", html.unescape(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def is_free(license_name: str) -> bool:
    lowered = license_name.lower()
    if re.search(r"\b(nc|nd)\b", lowered) or "non-commercial" in lowered or "noncommercial" in lowered:
        return False
    return any(lowered.startswith(free) for free in rules.load().type("photo")["free_licenses"])


def info(titles: list[str], preview_width: int = 640) -> dict[str, dict[str, Any]]:
    """The record of each file ("File:..."): its address, size, preview, license, author, and date taken."""
    found: dict[str, dict[str, Any]] = {}
    for start in range(0, len(titles), 40):
        payload = _query({"action": "query", "prop": "imageinfo", "titles": "|".join(titles[start:start + 40]),
                          "iiprop": "url|size|mime|extmetadata", "iiurlwidth": str(preview_width)})
        for page in payload.get("query", {}).get("pages", {}).values():
            image = (page.get("imageinfo") or [{}])[0]
            meta = image.get("extmetadata", {})

            def value(key: str, meta: dict[str, Any] = meta) -> str | None:
                return meta.get(key, {}).get("value")

            license_name = _plain(value("LicenseShortName")) or _plain(value("UsageTerms"))
            if not image.get("url") or image.get("mime") not in ("image/jpeg", "image/png", "image/tiff"):
                continue
            author = _plain(value("Artist")) or _plain(value("Credit"))
            author_link = re.search(r'href="(https://[^"]+)"', value("Artist") or "")
            found[page["title"]] = {
                "key": f"commons:{page['title']}", "title": page["title"], "url": image["url"],
                "preview": image.get("thumburl"), "width": image.get("width"), "height": image.get("height"),
                "source_url": image.get("descriptionurl"), "license": license_name,
                "license_url": value("LicenseUrl"), "author": author[:200] or None,
                "author_url": author_link.group(1) if author_link else None,
                "date": _plain(value("DateTimeOriginal")) or None,
                "description": _plain(value("ImageDescription"))[:400] or None, "free": is_free(license_name),
            }
    return found


def candidates(lat: float, lon: float, wikidata_id: str | None) -> list[dict[str, Any]]:
    """Free files that may show the place: its Wikidata image, files in its Commons category, and photos taken
    nearby, in that order, without repeats."""
    spec = rules.load().type("photo")
    titles: list[str] = []
    if wikidata_id:
        entity = http.wikidata_entities([wikidata_id], props="claims").get(wikidata_id, {})
        for prop in ("P18", "P373"):
            for claim in entity.get("claims", {}).get(prop, [])[:2]:
                value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
                if not isinstance(value, str):
                    continue
                if prop == "P18":
                    titles.append(f"File:{value}")
                else:
                    try:
                        members = _query({"action": "query", "list": "categorymembers", "cmtype": "file",
                                          "cmtitle": f"Category:{value}", "cmlimit": "20"})
                        titles += [m["title"] for m in members.get("query", {}).get("categorymembers", [])]
                    except (ConnectionError, urllib.error.HTTPError):
                        pass
    try:
        nearby = _query({"action": "query", "list": "geosearch", "gsnamespace": "6", "gslimit": "30",
                         "gscoord": f"{lat}|{lon}", "gsradius": str(spec["nearby_meters"])})
        titles += [g["title"] for g in nearby.get("query", {}).get("geosearch", [])]
    except (ConnectionError, urllib.error.HTTPError):
        pass
    unique = list(dict.fromkeys(titles))
    records = info(unique) if unique else {}
    return [records[t] for t in unique if t in records and records[t]["free"]][:spec["max_candidates"]]
