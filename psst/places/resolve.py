"""Resolving new places (a system task): the coordinate from Wikidata or OpenStreetMap, a check that it isn't
already a place under another name, names in other languages, and the areas it falls in."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from psst import rules
from psst.core import http

from . import cells, coords, names

Connection = psycopg.Connection[dict[str, Any]]


def resolve(conn: Connection, token: str, place_ids: list[str]) -> dict[str, int]:
    spec = rules.load().places
    pending = [dict(r) for r in conn.execute("""
        SELECT p.id, p.wikidata_id AS wikidata, p.osm_ref AS osm,
               (SELECT name FROM psst.place_names WHERE place_id = p.id AND role = 'display') AS display,
               (SELECT name FROM psst.place_names WHERE place_id = p.id AND role = 'local') AS local
        FROM psst.places p WHERE p.id = ANY(%s) AND p.state = 'pending'""", (place_ids,))]
    positions = coords.resolve(pending)
    tagged = names.osm_tags([p["osm"] for p in pending if p["osm"]])
    qids = sorted({p["wikidata"] or tagged.get(p["osm"] or "", {}).get("wikidata", "") for p in pending} - {""})
    labels = {qid: e.get("labels", {}) for qid, e in http.wikidata_entities(qids, props="labels").items()} \
        if qids else {}
    outcome = {"active": 0, "refused": 0}
    resolved: list[str] = []
    for place in pending:
        position = positions.get(place["id"])
        if not isinstance(position, coords.Position):
            result: dict[str, Any] = {"refused": position or "no coordinate"}
        else:
            duplicate = conn.execute("""
                SELECT p.id, n.name FROM psst.places p JOIN psst.place_names n ON n.place_id = p.id
                WHERE p.state = 'active' AND p.id <> %(id)s
                  AND ST_DWithin(p.geom::geography, ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography, %(m)s)
                  AND similarity(lower(n.name), lower(%(name)s)) > %(s)s
                LIMIT 1""", {"id": place["id"], "lat": position.lat, "lon": position.lon, "name": place["display"],
                             "m": spec["duplicate_meters"], "s": spec["duplicate_name_similarity"]}).fetchone()
            if duplicate:
                result = {"refused": f"the same place as {duplicate['id']} ({duplicate['name']})"}
            else:
                country = conn.execute("""
                    SELECT a.country_code FROM psst.area_parts ap JOIN psst.areas a ON a.id = ap.area_id
                    WHERE a.level = 'country' AND ST_Intersects(ap.geom, ST_SetSRID(ST_MakePoint(%s, %s), 4326))
                    LIMIT 1""", (position.lon, position.lat)).fetchone()
                tags = tagged.get(place["osm"] or "", {})
                qid = place["wikidata"] or tags.get("wikidata")
                rows = names.collect({"display": place["display"], "local": place["local"],
                                      "country": country["country_code"] if country else None},
                                     labels.get(qid or "", {}), tags)
                result = {"lat": position.lat, "lon": position.lon, "source": position.source, "ref": position.ref,
                          "cell": cells.cell_for(position.lat, position.lon), "names": rows,
                          "wikidata": None if place["wikidata"] else tags.get("wikidata")}
        state = conn.execute("SELECT psst.resolve_place(%s, %s, %s) AS s",
                             (token, place["id"], Jsonb(result))).fetchone()
        assert state
        outcome[state["s"]] = outcome.get(state["s"], 0) + 1
        if state["s"] == "active":
            resolved.append(place["id"])
    if resolved:
        assign_areas(conn, token, resolved)
    return outcome


def assign_areas(conn: Connection, token: str, place_ids: list[str]) -> None:
    areas = rules.load().places["areas"]
    conn.execute("SELECT psst.assign_areas(%s, %s, %s)",
                 (token, place_ids, Jsonb({"excluded_areas": [int(a) for a in areas["excluded_areas"]],
                                           "preferred_source": areas["preferred_source"],
                                           "nearest_neighborhood_meters": areas["nearest_neighborhood_meters"]})))


def relink(conn: Connection, token: str, task: dict[str, Any]) -> dict[str, Any]:
    """Links a place to the Wikidata item an editor named: its coordinate (from the new item, or the OSM element
    when the item has none) and its names in other languages, then sends its guide back for revision."""
    qid = task["input"]["wikidata"]
    place = conn.execute("""
        SELECT p.osm_ref AS osm, p.country_code,
               (SELECT name FROM psst.place_names WHERE place_id = p.id AND role = 'display') AS display,
               (SELECT name FROM psst.place_names WHERE place_id = p.id AND role = 'local') AS local
        FROM psst.places p WHERE p.id = %s""", (task["place_id"],)).fetchone()
    assert place
    position = coords.resolve([{"id": task["place_id"], "wikidata": qid, "osm": place["osm"]}]).get(task["place_id"])
    if not isinstance(position, coords.Position):
        raise ValueError(f"{qid} gives no usable coordinate: {position or 'none'}")
    labels = http.wikidata_entities([qid], props="labels").get(qid, {}).get("labels", {})
    tags = names.osm_tags([place["osm"]]).get(place["osm"], {}) if place["osm"] else {}
    rows = names.collect({"display": place["display"], "local": place["local"], "country": place["country_code"]},
                         labels, tags)
    result = {"lat": position.lat, "lon": position.lon, "source": position.source, "ref": position.ref,
              "cell": cells.cell_for(position.lat, position.lon), "names": rows}
    sent = conn.execute("SELECT psst.relink_place(%s, %s, %s) AS n", (token, task["id"], Jsonb(result))).fetchone()
    assert sent
    assign_areas(conn, token, [task["place_id"]])
    return {"wikidata": qid, "coordinate": position.source, "guides_sent_back": sent["n"]}
