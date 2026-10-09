"""Coordinates from Wikidata (P625) and OpenStreetMap, looked up by the tools, never typed. Always WGS-84."""

from __future__ import annotations

import time
import urllib.error
import urllib.parse
from dataclasses import dataclass

from psst import rules
from psst.core import http


@dataclass(frozen=True)
class Position:
    lat: float
    lon: float
    source: str       # "wikidata" or "osm"
    ref: str          # "Q123" or "way/456"


def wikidata(qids: list[str]) -> dict[str, list[tuple[float, float, float | None]]]:
    """Every P625 value per item: (lat, lon, precision). Items without a coordinate map to []."""
    found: dict[str, list[tuple[float, float, float | None]]] = {}
    for start in range(0, len(qids), 50):
        batch = qids[start:start + 50]
        try:
            entities = http.wikidata_entities(batch, props="claims")
            for qid in batch:
                claims = entities.get(qid, {}).get("claims", {}).get("P625", [])
                values = [c.get("mainsnak", {}).get("datavalue", {}).get("value") for c in claims]
                found[qid] = [(v["latitude"], v["longitude"], v.get("precision")) for v in values if v]
        except (ConnectionError, urllib.error.HTTPError):
            found.update(_wikidata_sparql(batch))  # the query service is a separate rate-limit pool
    return found


def _wikidata_sparql(batch: list[str]) -> dict[str, list[tuple[float, float, float | None]]]:
    values = " ".join(f"wd:{qid}" for qid in batch)
    query = f"""SELECT ?item ?lat ?lon ?precision WHERE {{
      VALUES ?item {{ {values} }}
      OPTIONAL {{ ?item p:P625/psv:P625 ?node . ?node wikibase:geoLatitude ?lat ; wikibase:geoLongitude ?lon .
                 OPTIONAL {{ ?node wikibase:geoPrecision ?precision }} }} }}"""
    payload = http.get_json("https://query.wikidata.org/sparql?format=json&query=" + urllib.parse.quote(query))
    found: dict[str, list[tuple[float, float, float | None]]] = {qid: [] for qid in batch}
    for row in payload["results"]["bindings"]:
        qid = row["item"]["value"].rsplit("/", 1)[-1]
        if "lat" in row:
            precision = float(row["precision"]["value"]) if "precision" in row else None
            found.setdefault(qid, []).append((float(row["lat"]["value"]), float(row["lon"]["value"]), precision))
    return found


def osm(refs: list[str]) -> dict[str, tuple[float, float]]:
    """A node's position, or the center of a way's or relation's bounding box."""
    found: dict[str, tuple[float, float]] = {}
    for start in range(0, len(refs), 100):
        batch = refs[start:start + 100]
        parts = "".join(f"{ref.split('/')[0]}({ref.split('/')[1]});" for ref in batch)
        try:
            payload = http.overpass(f"[out:json][timeout:90];({parts});out center;")
        except ConnectionError:
            for ref in batch:
                coord = _osm_api_center(ref)
                if coord:
                    found[ref] = coord
            continue
        for element in payload.get("elements", []):
            point = element if "lat" in element else element.get("center")
            if point:
                found[f"{element['type']}/{element['id']}"] = (point["lat"], point["lon"])
        time.sleep(1)
    return found


def osm_by_wikidata(qids: list[str]) -> dict[str, list[tuple[str, float, float]]]:
    """OpenStreetMap elements tagged with each Wikidata item."""
    found: dict[str, list[tuple[str, float, float]]] = {}
    for start in range(0, len(qids), 50):
        batch = qids[start:start + 50]
        try:
            payload = http.overpass(f'[out:json][timeout:90];nwr["wikidata"~"^({"|".join(batch)})$"];out center;')
        except ConnectionError:
            continue
        for element in payload.get("elements", []):
            qid = element.get("tags", {}).get("wikidata")
            point = element if "lat" in element else element.get("center")
            if qid in batch and point:
                found.setdefault(qid, []).append((f"{element['type']}/{element['id']}", point["lat"], point["lon"]))
    return found


def _osm_api_center(ref: str) -> tuple[float, float] | None:
    kind, number = ref.split("/")
    suffix = ".json" if kind == "node" else "/full.json"
    try:
        payload = http.get_json(f"https://api.openstreetmap.org/api/0.6/{kind}/{number}{suffix}", attempts=3)
    except (ConnectionError, urllib.error.HTTPError):
        return None
    nodes = [e for e in payload.get("elements", []) if e.get("type") == "node" and "lat" in e]
    if not nodes:
        return None
    if kind == "node":
        return nodes[0]["lat"], nodes[0]["lon"]
    lats, lons = [n["lat"] for n in nodes], [n["lon"] for n in nodes]
    return (min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2


def resolve(places: list[dict[str, str | None]]) -> dict[str, Position | str]:
    """For each place (id, wikidata, osm): its position, or the reason there isn't one. Wikidata first (CC0)
    when it has exactly one coordinate precise enough; otherwise the OSM element, given or tagged with the item."""
    limit = float(rules.load().places["max_wikidata_precision"])
    qids = sorted({str(p["wikidata"]) for p in places if p.get("wikidata")})
    refs = sorted({str(p["osm"]) for p in places if p.get("osm")})
    from_wikidata = wikidata(qids) if qids else {}
    from_osm = osm(refs) if refs else {}
    unusable = sorted({str(p["wikidata"]) for p in places if p.get("wikidata") and not p.get("osm")
                       and (len(from_wikidata.get(str(p["wikidata"])) or []) != 1
                            or (from_wikidata[str(p["wikidata"])][0][2] or 0) > limit)})
    tagged = osm_by_wikidata(unusable) if unusable else {}
    result: dict[str, Position | str] = {}
    for place in places:
        qid, ref, reason = place.get("wikidata"), place.get("osm"), None
        if qid:
            values = from_wikidata.get(qid)
            if values is None:
                reason = f"{qid} isn't on Wikidata"
            elif not values:
                reason = f"{qid} has no coordinate on Wikidata"
            elif len(values) > 1:
                reason = f"{qid} has {len(values)} coordinates on Wikidata"
            elif values[0][2] is not None and values[0][2] > limit:
                reason = f"{qid}'s coordinate is only precise to {values[0][2]} degrees"
            else:
                result[str(place["id"])] = Position(values[0][0], values[0][1], "wikidata", qid)
                continue
        if ref:
            coord = from_osm.get(ref)
            result[str(place["id"])] = Position(coord[0], coord[1], "osm", ref) if coord else \
                f"{ref} isn't on OpenStreetMap" + (f"; also {reason}" if reason else "")
        elif qid and len(tagged.get(qid, [])) == 1:
            found_ref, lat, lon = tagged[qid][0]
            result[str(place["id"])] = Position(lat, lon, "osm", found_ref)
        elif qid and tagged.get(qid):
            result[str(place["id"])] = f"{reason}; several OpenStreetMap elements carry {qid}"
        else:
            result[str(place["id"])] = f"{reason}; give the OpenStreetMap element"
    return result
