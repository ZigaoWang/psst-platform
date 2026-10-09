"""The acceptance check (design.md, section 11.2): staging downloaded back over HTTPS exactly as the app would,
and checked before anything is promoted."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

import jsonschema

from psst.core import http

from .build import BuildError, read_pack, schema

MAX_SHRINK = 0.02


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": http.USER_AGENT, "Cache-Control": "no-cache"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return bytes(response.read())


def download(base_url: str, channel: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]] | None:
    """A channel's manifest, common pack, and city packs, each checked against its hash. None if it is empty."""
    root = f"{base_url.rstrip('/')}/content/{channel}/v2"
    try:
        manifest = json.loads(_get(f"{root}/manifest.json"))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise

    def pack(entry: dict[str, Any]) -> dict[str, Any]:
        return read_pack(_get(f"{root}/{entry['file']}"), entry)

    return manifest, pack(manifest["common"]), {c["cityId"]: pack(c) for c in manifest["cities"]}


def served(url: str) -> bool:
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": http.USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return bool(response.status == 200)
    except (urllib.error.URLError, TimeoutError):
        return False


def check(base_url: str, version: str, allow_shrink: str | None = None) -> list[str]:
    """Every problem with staging; an empty list means it can be promoted."""
    problems: list[str] = []
    try:
        staged = download(base_url, "staging")
    except (urllib.error.URLError, BuildError, ValueError) as error:
        return [f"staging can't be read: {error}"]
    if staged is None:
        return ["staging is empty"]
    manifest, common, cities = staged
    if manifest["contentVersion"] != version:
        return [f"staging holds {manifest['contentVersion']}, not {version}"]
    for document, name in [(manifest, "manifest"), (common, "common")] + [(c, "city") for c in cities.values()]:
        for invalid in jsonschema.Draft202012Validator(schema(name)).iter_errors(document):
            problems.append(f"{name}: {invalid.message}")
    areas = {a["id"] for a in common["areas"]}
    tags = {t["id"] for t in common["tags"]}
    place_ids: set[str] = set()
    for city_id, city in cities.items():
        for place in city["places"]:
            place_ids.add(place["id"])
            for key in ("districtId", "neighborhoodId"):
                if place.get(key) and place[key] not in areas:
                    problems.append(f"{place['id']}: {key} {place[key]} isn't in the common pack")
            for fact in place["facts"]:
                problems += [f"{fact['id']}: tag {t} isn't in the common pack" for t in fact.get("tags", [])
                             if t not in tags]
        for trail in city.get("trails", []):
            problems += [f"{trail['id']}: stop {s['placeId']} isn't in the pack" for s in trail["stops"]
                         if s["placeId"] not in {p["id"] for p in city["places"]}]
        if city_id not in {c["id"] for c in common["cities"]}:
            problems.append(f"city pack {city_id} isn't listed in the common pack")
    problems += [f"old id {old} points to {new}, which isn't published" for old, new in common["legacyIds"].items()
                 if new not in place_ids]
    production = download(base_url, "production")
    live_images = {i["full"]["file"] for c in (production[2].values() if production else [])
                   for p in c["places"] for i in p.get("images", [])}
    for city in cities.values():
        for place in city["places"]:
            for image in place.get("images", []):
                for rendition in ("full", "thumb"):
                    name = image[rendition]["file"]
                    if name not in live_images and not served(f"{base_url.rstrip('/')}/images/{name}"):
                        problems.append(f"{image['id']}: {name} isn't served")
    if production and not allow_shrink:
        before, after = production[0].get("counts", {}), manifest.get("counts", {})
        for key in ("places", "facts"):
            if before.get(key) and after.get(key, 0) < before[key] * (1 - MAX_SHRINK):
                problems.append(f"{key} would drop from {before[key]} to {after.get(key, 0)}; publish with an "
                                "explanation to allow it")
    return problems
