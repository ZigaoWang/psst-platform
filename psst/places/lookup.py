"""Finding the Wikidata item or OpenStreetMap element for a place a researcher found by name, so it can be added
with an identifier the tools can locate."""

from __future__ import annotations

import math
import re
import urllib.error
import urllib.parse
from typing import Any

from psst.core import http

from . import coords


def _meters(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlon = math.radians(b[1] - a[1])
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 12_742_000 * math.asin(math.sqrt(h))


def find(name: str, lat: float, lon: float, radius: int = 1500, language: str = "en") -> list[dict[str, Any]]:
    """Wikidata items and OSM elements named like `name` within `radius` meters of the point, nearest first."""
    found: list[dict[str, Any]] = []
    try:
        search = http.get_json("https://www.wikidata.org/w/api.php?action=wbsearchentities&format=json&limit=20&"
                               + urllib.parse.urlencode({"search": name, "language": language}))
        qids = [hit["id"] for hit in search.get("search", [])]
        labels = {hit["id"]: (hit.get("label"), hit.get("description")) for hit in search.get("search", [])}
        for qid, values in coords.wikidata(qids).items():
            if len(values) == 1:
                distance = _meters((lat, lon), values[0][:2])
                if distance <= radius:
                    found.append({"wikidata": qid, "name": labels[qid][0], "description": labels[qid][1],
                                  "meters": round(distance)})
    except (ConnectionError, urllib.error.HTTPError):
        pass
    pattern = re.escape(name).replace('"', '\\"')
    query = f'[out:json][timeout:60];nwr["name"~"{pattern}",i](around:{radius},{lat},{lon});out center tags 20;'
    try:
        for element in http.overpass(query).get("elements", []):
            point = element if "lat" in element else element.get("center")
            if point:
                tags = element.get("tags", {})
                found.append({"osm": f"{element['type']}/{element['id']}", "name": tags.get("name"),
                              "wikidata": tags.get("wikidata"),
                              "description": next((f"{k}={tags[k]}" for k in ("historic", "building", "amenity",
                                                   "tourism", "railway", "shop") if k in tags), None),
                              "meters": round(_meters((lat, lon), (point["lat"], point["lon"])))})
    except ConnectionError:
        pass
    return sorted(found, key=lambda f: f["meters"])
