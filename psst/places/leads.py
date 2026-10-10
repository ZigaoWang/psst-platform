"""Leads for a research cell: articles in English and the local Wikipedia, mapped features in OpenStreetMap,
and places from the previous system's list (a coverage checklist only). Each lead carries its fame, the number
of Wikipedia editions that cover it."""

from __future__ import annotations

import time
import urllib.error
import urllib.parse
from typing import Any

import h3
import psycopg

from psst import rules
from psst.core import http

from . import cells

Connection = psycopg.Connection[dict[str, Any]]
OSM_QUERY = """[out:json][timeout:120][bbox:{s},{w},{n},{e}];
(
  nwr[historic]; nwr[heritage]; nwr[memorial]; nwr[tourism~"attraction|museum|artwork|viewpoint|gallery"];
  nwr[railway=station]; nwr[public_transport=station]; nwr[amenity=ferry_terminal]; nwr[amenity=pub];
  nwr[amenity~"bar|cafe|restaurant|theatre|cinema|place_of_worship|marketplace"][wikidata];
  nwr[building][wikidata]; nwr[man_made][wikidata]; nwr[shop][wikidata]; nwr[bridge][name];
);
out center tags;"""
FEATURE_KEYS = ("historic", "tourism", "railway", "public_transport", "amenity", "building", "man_made", "shop",
                "memorial", "bridge")


def fame(qids: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for qid, entity in http.wikidata_entities(sorted(set(qids)), props="sitelinks").items():
        counts[qid] = sum(1 for site in entity.get("sitelinks", {}) if site.endswith("wiki")
                          and site not in ("commonswiki", "specieswiki", "metawiki", "wikidatawiki"))
    return counts


def classes(qids: list[str]) -> dict[str, set[str]]:
    """What each item is an instance of (P31), through the query service in batches."""
    found: dict[str, set[str]] = {}
    for start in range(0, len(qids), 200):
        values = " ".join(f"wd:{q}" for q in qids[start:start + 200])
        query = f"SELECT ?item ?class WHERE {{ VALUES ?item {{ {values} }} ?item wdt:P31 ?class . }}"
        payload = http.get_json("https://query.wikidata.org/sparql?format=json&query=" + urllib.parse.quote(query))
        for row in payload["results"]["bindings"]:
            found.setdefault(row["item"]["value"].rsplit("/", 1)[-1], set()).add(
                row["class"]["value"].rsplit("/", 1)[-1])
    return found


def sweep(conn: Connection, cell: str, country: str | None) -> tuple[list[dict[str, Any]], list[str]]:
    south, west, north, east = cells.bounds(cell)
    lat, lon = h3.cell_to_latlng(cell)
    found: dict[str, dict[str, Any]] = {}
    problems: list[str] = []

    def add(key: str, entry: dict[str, Any]) -> None:
        if cells.cell_for(entry.pop("lat"), entry.pop("lon")) != cell:
            return
        merged = found.setdefault(key, {"key": key})
        for k, v in entry.items():
            if v and not merged.get(k):
                merged[k] = v

    local = rules.load().places["local_wikipedia"].get(country or "", "en")
    for lang in dict.fromkeys(["en", local]):
        url = (f"https://{lang}.wikipedia.org/w/api.php?action=query&format=json&generator=geosearch"
               f"&ggscoord={lat}|{lon}&ggsradius=2000&ggslimit=500&prop=coordinates|pageprops"
               f"&ppprop=wikibase_item&colimit=500")
        try:
            pages = http.get_json(url, attempts=3).get("query", {}).get("pages", {}).values()
        except (ConnectionError, urllib.error.HTTPError) as error:
            problems.append(f"{lang}.wikipedia search failed: {error}")
            continue
        for page in pages:
            point = (page.get("coordinates") or [{}])[0]
            if "lat" in point:
                qid = page.get("pageprops", {}).get("wikibase_item")
                add(qid or f"{lang}:{page['title']}", {
                    "origin": "wikipedia", "name": page["title"], "lat": point["lat"], "lon": point["lon"],
                    "wikidata": qid,
                    "url": f"https://{lang}.wikipedia.org/wiki/" + urllib.parse.quote(page["title"].replace(" ", "_"))})
        time.sleep(0.3)
    try:
        elements = http.overpass(OSM_QUERY.format(s=south, w=west, n=north, e=east)).get("elements", [])
    except ConnectionError as error:
        problems.append(f"the OpenStreetMap search failed: {error}")
        elements = []
    for element in elements:
        tags = element.get("tags", {})
        name = tags.get("name:en") or tags.get("name")
        point = element if "lat" in element else element.get("center")
        if name and point:
            what = next((f"{k}={tags[k]}" for k in FEATURE_KEYS if k in tags), "")
            add(tags.get("wikidata") or f"name:{name}", {
                "origin": "osm", "name": name, "lat": point["lat"], "lon": point["lon"],
                "osm": f"{element['type']}/{element['id']}", "wikidata": tags.get("wikidata"), "what": what})
    for prop, how in rules.load().sources.get("record_properties", {}).items():
        try:
            records = record_items(prop, south, west, north, east)
        except (ConnectionError, urllib.error.HTTPError, KeyError, ValueError) as error:
            problems.append(f"the {how['publisher']} records search failed: {error}")
            continue
        for item in records:
            add(item["wikidata"], {"origin": "record", "name": item["name"], "lat": item["lat"], "lon": item["lon"],
                                   "wikidata": item["wikidata"], "url": how["url"].format(item["record"]),
                                   "what": how["title"].format(item["record"])})
        time.sleep(0.3)
    for row in conn.execute("""
            SELECT l.id, l.name, l.wikidata_id, l.osm_ref, ST_Y(l.geom) AS lat, ST_X(l.geom) AS lon
            FROM psst.legacy_places l, psst.research_cells c
            WHERE c.cell = %s AND ST_Intersects(l.geom, c.geom)""", (cell,)):
        add(row["wikidata_id"] or row["osm_ref"] or f"legacy:{row['id']}", {
            "origin": "legacy", "name": row["name"], "lat": row["lat"], "lon": row["lon"],
            "wikidata": row["wikidata_id"], "osm": row["osm_ref"], "legacy": row["id"]})
    leads = list(found.values())
    try:
        counts = fame([lead["wikidata"] for lead in leads if lead.get("wikidata")])
    except (ConnectionError, urllib.error.HTTPError) as error:
        problems.append(f"fame couldn't be read: {error}")
        counts = {}
    abstract: dict[str, str] = rules.load().places["abstract_lead_classes"]
    try:
        kinds = classes(sorted({lead["wikidata"] for lead in leads if lead.get("wikidata")}))
    except (ConnectionError, urllib.error.HTTPError) as error:
        problems.append(f"classes couldn't be read: {error}")
        kinds = {}
    for lead in leads:
        lead["fame"] = counts.get(lead.get("wikidata") or "")
        lead.setdefault("origin", "wikidata")
        found_classes = kinds.get(lead.get("wikidata") or "", set())
        if found_classes and found_classes <= set(abstract) and lead["origin"] != "legacy":
            lead["skip"] = "not a place to stand in front of: " + abstract[sorted(found_classes)[0]]
    return leads, problems


def record_items(prop: str, south: float, west: float, north: float, east: float) -> list[dict[str, Any]]:
    """Every Wikidata item in a box that carries an official record's id (a heritage list entry, say), with its
    name, point, and record id: the listed buildings, kiosks, bollards, and walls a city center is made of."""
    query = f"""SELECT ?item ?itemLabel ?coord ?record WHERE {{
      SERVICE wikibase:box {{ ?item wdt:P625 ?coord .
        bd:serviceParam wikibase:cornerSouthWest "Point({west} {south})"^^geo:wktLiteral .
        bd:serviceParam wikibase:cornerNorthEast "Point({east} {north})"^^geo:wktLiteral . }}
      ?item wdt:{prop} ?record .
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,zh". }} }}"""
    payload = http.get_json("https://query.wikidata.org/sparql?format=json&query=" + urllib.parse.quote(query),
                            attempts=3)
    items = []
    for row in payload["results"]["bindings"]:
        lon, lat = (float(x) for x in row["coord"]["value"].removeprefix("Point(").rstrip(")").split())
        qid = row["item"]["value"].rsplit("/", 1)[-1]
        name = row.get("itemLabel", {}).get("value", qid)
        if name != qid:
            items.append({"wikidata": qid, "name": name, "lat": lat, "lon": lon, "record": row["record"]["value"]})
    return items

