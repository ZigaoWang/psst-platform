"""Building the output in content format 2 (design.md, section 11.1) from what the `publishable` view says.

The build is deterministic: the same database state gives byte-identical packs with the same hashes, so the app
never downloads an unchanged city again. Nothing is written to the database here.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema
import psycopg

from psst import rules
from psst.core import config
from psst.rules import writing
from psst.rules.report import Report

FORMAT_VERSION = 2
SCHEMAS = config.ROOT / "format" / "v2"
Connection = psycopg.Connection[dict[str, Any]]


class BuildError(RuntimeError):
    pass


@dataclass
class Build:
    directory: Path
    version: str
    manifest: dict[str, Any]
    counts: dict[str, int]
    items: list[dict[str, str]]                  # {item, revision} for everything in the output
    held: list[dict[str, Any]] = field(default_factory=list)


def schema(name: str) -> dict[str, Any]:
    return dict(json.loads((SCHEMAS / f"{name}.schema.json").read_text()))


def write_pack(directory: Path, name: str, document: dict[str, Any]) -> dict[str, Any]:
    raw = json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    data = gzip.compress(raw, compresslevel=9, mtime=0)  # mtime 0 keeps identical content byte-identical
    digest = hashlib.sha256(data).hexdigest()
    relative = f"packs/{name}.{digest[:16]}.json.gz"
    (directory / "packs").mkdir(parents=True, exist_ok=True)
    (directory / relative).write_bytes(data)
    return {"file": relative, "sha256": digest, "bytes": len(data)}


def read_pack(data: bytes, entry: dict[str, Any]) -> dict[str, Any]:
    """A pack's document, after checking its size and hash exactly as the app does."""
    if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
        raise BuildError(f"{entry['file']} doesn't match its hash")
    return dict(json.loads(gzip.decompress(data)))


def _rows(conn: Connection, query: str, params: Any = None) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(query, params)]  # type: ignore[arg-type]  # queries are constants


def _sources_and_claims(conn: Connection, revision_ids: list[str]) -> dict[str, tuple[list[dict], list[dict]]]:
    """Per revision: its sources in order of first use, and its claims with the indexes of their sources."""
    found: dict[str, tuple[list[dict], list[dict]]] = {}
    rows = _rows(conn, """
        SELECT c.revision_id, c.n, c.text, s.id AS source, s.title, s.publisher, s.url
        FROM psst.claims c JOIN psst.evidence e ON e.claim_id = c.id AND e.matched
        JOIN psst.snapshots n ON n.id = e.snapshot_id JOIN psst.sources s ON s.id = n.source_id
        WHERE c.revision_id = ANY(%s) ORDER BY c.revision_id, c.n, e.id""", (revision_ids,))
    order: dict[str, dict[str, int]] = defaultdict(dict)
    claims: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        sources, _ = found.setdefault(row["revision_id"], ([], []))
        index = order[row["revision_id"]].get(row["source"])
        if index is None:
            index = order[row["revision_id"]][row["source"]] = len(sources)
            sources.append({"title": row["title"], "publisher": row["publisher"], "url": row["url"]})
        claim = claims[row["revision_id"]].setdefault(row["n"], {"text": row["text"], "sources": []})
        if index not in claim["sources"]:
            claim["sources"].append(index)
    for revision, by_n in claims.items():
        found[revision][1].extend(by_n[n] for n in sorted(by_n))
    return found


def build(conn: Connection, out_root: Path, now: datetime | None = None) -> Build:
    rulebook = rules.load()
    version = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    items = _rows(conn, """
        SELECT p.item_id, p.type, p.place_id, p.city_id, p.translates, p.language, p.position, p.revision_id,
               r.body, r.translation_of, r.created_at::date AS written_on,
               (SELECT max(t.at)::date FROM psst.transitions t
                WHERE t.item_id = p.item_id AND t.revision_id = p.revision_id
                  AND t.to_state = 'accepted') AS verified_on
        FROM psst.publishable p JOIN psst.revisions r ON r.id = p.revision_id
        ORDER BY p.item_id""")
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        by_type[item["type"]].append(item)

    # A place publishes only with a story and its guide information.
    stories_by_place: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for story in by_type["story"]:
        stories_by_place[story["place_id"]].append(story)
    guides = {g["place_id"]: g for g in by_type["guide"]}
    held = [{"place": p, "reason": "no guide information ready"}
            for p in sorted(stories_by_place) if p not in guides]
    place_ids = sorted(p for p in stories_by_place if p in guides)
    places = {p["id"]: p for p in _rows(conn, """
        SELECT p.id, p.kind, p.size, ST_Y(p.geom) AS lat, ST_X(p.geom) AS lon, p.coord_source, p.coord_ref,
               p.country_code, p.district_id, p.neighborhood_id, coalesce(p.city_id, p.region_id) AS group_id,
               p.wikidata_id,
               (SELECT name FROM psst.place_names WHERE place_id = p.id AND role = 'display') AS name,
               (SELECT jsonb_build_object('lang', lang, 'name', name) FROM psst.place_names
                WHERE place_id = p.id AND role = 'local') AS local_name,
               coalesce((SELECT jsonb_object_agg(lang, name ORDER BY lang) FROM psst.place_names
                         WHERE place_id = p.id AND role = 'alt'), '{}') AS names
        FROM psst.places p WHERE p.id = ANY(%s) AND p.state = 'active'""", (place_ids,))}
    held += [{"place": p, "reason": "the place isn't active"} for p in place_ids if p not in places]
    held += [{"place": p, "reason": "the place has no display name"} for p in sorted(places) if not places[p]["name"]]
    places = {p: place for p, place in places.items() if place["name"]}
    if not places:
        raise BuildError("Nothing can publish yet: no place has both an audited story and guide information.")

    english = [i for i in items if i["type"] in ("story", "guide", "photo") and i["place_id"] in places
               or i["type"] == "trail"]
    photos_by_place: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for photo in by_type["photo"]:
        if photo["place_id"] in places:
            photos_by_place[photo["place_id"]].append(photo)
    published_revisions = {i["item_id"]: i["revision_id"] for i in english}
    translations: dict[str, dict[str, Any]] = defaultdict(dict)
    for t in by_type["translation"]:
        if published_revisions.get(t["translates"]) == t["translation_of"]:
            translations[t["translates"]][t["language"]] = t["body"]
    evidence = _sources_and_claims(conn, [i["revision_id"] for i in english])

    report = Report()
    for item in english:
        spec = rulebook.type(item["type"])
        for name in spec["prose_fields"]:
            if isinstance(item["body"].get(name), str):
                writing.check_prose(report, f"{item['item_id']}.{name}", item["body"][name], rulebook)
    if report.refusals:
        raise BuildError("Content breaks the writing rules:\n  " + "\n  ".join(report.refusals[:30]))

    tag_places: dict[str, set[str]] = defaultdict(set)
    for story in by_type["story"]:
        if story["place_id"] in places:
            for tag in story["body"].get("tags", []):
                tag_places[tag].add(story["place_id"])
    tag_rows = _rows(conn, """
        SELECT t.id, t.canonical_name, t.type, t.wikidata_id,
               coalesce((SELECT jsonb_object_agg(lang, name ORDER BY lang) FROM psst.tag_names WHERE tag_id = t.id),
                        '{}') AS names,
               coalesce((SELECT array_agg(label ORDER BY label) FROM psst.tag_labels
                         WHERE tag_id = t.id AND NOT is_canonical), '{}') AS aliases
        FROM psst.tags t WHERE t.id = ANY(%s) ORDER BY t.id""",
                     ([t for t, ps in tag_places.items() if len(ps) >= rulebook.places["tag_min_places"]],))
    published_tags = {t["id"] for t in tag_rows}

    guide_spec = rulebook.type("guide")
    order = {kf["property"]: i for i, kf in enumerate(guide_spec["key_facts"])}
    labels = {kf["property"]: kf["label"] for kf in guide_spec["key_facts"]}

    def story_entry(story: dict[str, Any]) -> dict[str, Any]:
        body, (sources, claims) = story["body"], evidence.get(story["revision_id"], ([], []))
        entry: dict[str, Any] = {
            "id": story["item_id"], "category": body["category"], "veracity": body["veracity"],
            "headline": body["headline"], "short": body["short"], "long": body["long"] + "\n\n" + body["look"],
            "look": body["look"], "sources": sources, "claims": claims,
            "tags": sorted(t for t in body.get("tags", []) if t in published_tags),
            "researchedOn": str(story["written_on"]), "lastVerified": _date(story["verified_on"]),
        }
        if body.get("myth"):
            entry["myth"] = body["myth"]
        if translations.get(story["item_id"]):
            entry["translations"] = translations[story["item_id"]]
        return entry

    def key_fact_entries(facts: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
        """One line per property, in display order; several values for one property (two materials) share it."""
        grouped: dict[str, list[dict[str, Any]]] = {}
        for fact in facts:
            grouped.setdefault(fact["property"], []).append(fact)
        entries = []
        for prop, values in list(grouped.items())[:guide_spec["max_shown"]]:
            label = guide_spec["built_label"].get(kind, labels[prop]) if prop == "P571" else labels[prop]
            entry: dict[str, Any] = {"property": prop, "label": label, "value": ", ".join(v["value"] for v in values)}
            if len(values) > 1:
                entry["values"] = [{"value": v["value"], "id": v.get("value_id")} for v in values]
            entries.append(entry)
        return entries

    def guide_entry(guide: dict[str, Any], wikidata_id: str | None, kind: str) -> dict[str, Any]:
        body, (sources, claims) = guide["body"], evidence.get(guide["revision_id"], ([], []))
        facts = sorted((kf for kf in body["key_facts"] if kf["property"] in order),
                       key=lambda kf: order[kf["property"]])
        entry: dict[str, Any] = {
            "id": guide["item_id"], "identifier": body["identifier"], "about": body["about"],
            "wikidataId": wikidata_id, "lastVerified": _date(guide["verified_on"]), "sources": sources,
            "claims": claims,
            "keyFacts": key_fact_entries(facts, kind),
        }
        if translations.get(guide["item_id"]):
            entry["translations"] = translations[guide["item_id"]]
        return entry

    def image_entry(photo: dict[str, Any]) -> dict[str, Any]:
        body = photo["body"]
        credit = body["credit"]
        entry: dict[str, Any] = {
            "id": photo["item_id"], "kind": body["kind"], "year": body.get("year"), "alt": body["alt"],
            "focus": body["focus"], "full": body["full"], "thumb": body["thumb"],
            "credit": {"author": credit["author"], "authorUrl": credit.get("author_url"), "license": credit["license"],
                       "licenseUrl": credit.get("license_url"), "sourceUrl": credit["source_url"],
                       "source": credit["source"], "title": credit.get("title")},
        }
        if body.get("pair"):
            entry["pair"] = body["pair"]
        return entry

    by_group: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for place_id in sorted(places):
        place = places[place_id]
        if place["group_id"] is None:
            raise BuildError(f"{place_id} has no city or region; assign its areas first")
        stories = sorted(stories_by_place[place_id], key=lambda s: (s["position"], s["item_id"]))
        entry = {
            "id": place_id, "name": place["name"], "localName": place["local_name"], "names": place["names"],
            "kind": place["kind"], "size": place["size"], "lat": round(place["lat"], 7), "lon": round(place["lon"], 7),
            "location": {"source": place["coord_source"], "ref": place["coord_ref"],
                         "license": "CC0-1.0" if place["coord_source"] == "wikidata" else "ODbL-1.0"},
            "countryCode": place["country_code"],
            "districtId": str(place["district_id"]) if place["district_id"] else None,
            "neighborhoodId": str(place["neighborhood_id"]) if place["neighborhood_id"] else None,
            "facts": [story_entry(s) for s in stories],
            "guide": guide_entry(guides[place_id], place["wikidata_id"], place["kind"]),
        }
        if photos_by_place.get(place_id):
            entry["images"] = [image_entry(p) for p in sorted(photos_by_place[place_id],
                                                              key=lambda p: (p["position"], p["item_id"]))]
        by_group[place["group_id"]].append(entry)

    trails_by_city: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for trail in by_type["trail"]:
        body = trail["body"]
        if not all(stop["place"] in places for stop in body["stops"]):
            held.append({"item": trail["item_id"], "reason": "a stop isn't published"})
            continue
        sources_claims = evidence.get(trail["revision_id"], ([], []))
        entry = {"id": trail["item_id"], "title": body["title"], "intro": body["intro"],
                 "stops": [{"placeId": s["place"], "note": s["note"]} for s in body["stops"]],
                 "tags": sorted(t for t in body["tags"] if t in published_tags), "claims": sources_claims[1]}
        if translations.get(trail["item_id"]):
            entry["translations"] = {lang: {"title": t.get("title"), "intro": t.get("intro"),
                                            "stopNotes": t.get("stop_notes")}
                                     for lang, t in translations[trail["item_id"]].items()}
        trails_by_city[trail["city_id"]].append(entry)

    directory = out_root / version
    directory.mkdir(parents=True, exist_ok=False)
    groups = {g["id"]: g for g in _rows(conn, """
        SELECT a.id, a.name, a.country_code,
               coalesce((SELECT jsonb_object_agg(lang, name ORDER BY lang) FROM psst.area_names
                         WHERE area_id = a.id AND lang <> 'en'), '{}') AS names
        FROM psst.areas a WHERE a.id = ANY(%s)""", (list(by_group),))}
    city_entries: list[dict[str, Any]] = []
    cities: list[dict[str, Any]] = []
    area_ids: set[int] = set()
    city_schema = schema("city")
    for group_id in sorted(by_group):
        group_places = by_group[group_id]
        city_id = str(group_id)
        document: dict[str, Any] = {"formatVersion": FORMAT_VERSION, "cityId": city_id, "places": group_places}
        if trails_by_city.get(group_id):
            document["trails"] = sorted(trails_by_city[group_id], key=lambda t: t["id"])
        jsonschema.validate(document, city_schema)
        city_entries.append({**write_pack(directory, f"city-{city_id}", document), "cityId": city_id})
        lats, lons = [p["lat"] for p in group_places], [p["lon"] for p in group_places]
        group = groups[group_id]
        cities.append({"id": city_id, "name": group["name"], "names": group["names"],
                       "countryCode": group["country_code"] or group_places[0]["countryCode"],
                       "bounds": {"south": min(lats), "west": min(lons), "north": max(lats), "east": max(lons)},
                       "placeCount": len(group_places)})
        for p in group_places:
            area_ids.update(int(a) for a in (p["districtId"], p["neighborhoodId"]) if a)

    city_of_area = {int(a): str(p_group) for p_group, ps in by_group.items() for p in ps
                    for a in (p["districtId"], p["neighborhoodId"]) if a}
    areas = _rows(conn, """
        SELECT a.id, a.level, a.name,
               coalesce((SELECT jsonb_object_agg(lang, name ORDER BY lang) FROM psst.area_names
                         WHERE area_id = a.id AND lang <> 'en'), '{}') AS names
        FROM psst.areas a WHERE a.id = ANY(%s) ORDER BY a.id""", (sorted(area_ids),))
    legacy = {r["legacy_id"]: r["place_id"] for r in _rows(conn, """
        SELECT legacy_id, place_id FROM psst.place_identity WHERE place_id = ANY(%s) ORDER BY legacy_id""",
                                                              (sorted(places),))}
    common = {
        "formatVersion": FORMAT_VERSION, "cities": cities,
        "areas": [{"id": str(a["id"]), "level": a["level"], "name": a["name"], "names": a["names"],
                   "cityId": city_of_area[a["id"]]} for a in areas],
        "tags": [{"id": t["id"], "name": t["canonical_name"], "type": t["type"], "wikidataId": t["wikidata_id"],
                  "names": t["names"], "aliases": list(t["aliases"]), "placeCount": len(tag_places[t["id"]])}
                 for t in tag_rows],
        "legacyIds": legacy,
    }
    jsonschema.validate(common, schema("common"))
    counts = {"places": len(places), "facts": sum(len(p["facts"]) for ps in by_group.values() for p in ps),
              "trails": sum(len(t) for t in trails_by_city.values())}
    manifest = {
        "formatVersion": FORMAT_VERSION, "contentVersion": version,
        "generatedAt": (now or datetime.now(UTC)).isoformat(timespec="seconds"),
        "common": write_pack(directory, "common", common),
        "cities": sorted(city_entries, key=lambda c: c["cityId"]), "counts": counts,
    }
    jsonschema.validate(manifest, schema("manifest"))
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    included = [{"item": i["item_id"], "revision": i["revision_id"]} for i in english if
                i["type"] != "trail" or any(t["id"] == i["item_id"] for ts in trails_by_city.values() for t in ts)]
    included += [{"item": t["item_id"], "revision": t["revision_id"]} for t in by_type["translation"]
                 if t["translates"] in {i["item"] for i in included} and
                 published_revisions.get(t["translates"]) == t["translation_of"]]
    return Build(directory, version, manifest, counts, sorted(included, key=lambda i: i["item"]), held)


def _date(value: Any) -> str | None:
    return str(value) if value else None
