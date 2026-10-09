"""Importing a chosen photo (a system task): its record read from Commons, our copies made and stored, and the
photo revision created for checking."""

from __future__ import annotations

import urllib.request
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from psst import rules
from psst.core import config, http

from . import commons, copies

Connection = psycopg.Connection[dict[str, Any]]
SOURCE_WIDTH = 2400


def images_dir() -> Path:
    return Path(config.require("PSST_IMAGES_DIR"))


def download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": http.USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        data = bytes(response.read(copies.MAX_SOURCE_BYTES + 1))
    if len(data) > copies.MAX_SOURCE_BYTES:
        raise ValueError("the file is too large to copy")
    return data


def import_photo(conn: Connection, token: str, task: dict[str, Any]) -> dict[str, Any]:
    choice = task["input"]
    title = str(choice["key"]).removeprefix("commons:")
    record = commons.info([title], preview_width=SOURCE_WIDTH).get(title)
    if record is None:
        raise ValueError(f"{title} isn't a photo on Commons")
    if not record["free"]:
        raise ValueError(f"{title} has the license {record['license']!r}, which isn't free")
    if not record["author"]:
        raise ValueError(f"{title} has no author on Commons, so it can't be credited")
    spec = rules.load().type("photo")
    source = download(record["preview"] or record["url"])
    full = copies.render(source, spec["renditions"]["full"])
    thumb = copies.render(source, spec["renditions"]["thumb"])
    for rendition in (full, thumb):
        copies.store(rendition, images_dir())
    credit = {"source": "commons", "source_url": record["source_url"], "title": record["title"],
              "author": record["author"], "license": record["license"]}
    if record["author_url"]:
        credit["author_url"] = record["author_url"]
    if record["license_url"] and str(record["license_url"]).startswith("https://"):
        credit["license_url"] = record["license_url"]
    body: dict[str, Any] = {
        "full": {"file": full.file, "width": full.width, "height": full.height},
        "thumb": {"file": thumb.file, "width": thumb.width, "height": thumb.height},
        "kind": choice.get("kind", "photo"), "alt": choice["alt"], "focus": choice.get("focus", [0.5, 0.5]),
        "credit": credit,
    }
    for optional in ("year", "pair"):
        if choice.get(optional) is not None:
            body[optional] = choice[optional]
    row = conn.execute("SELECT psst.create_photo(%s, %s, %s, %s) AS r",
                       (token, task["id"], Jsonb(body), rules.load().version)).fetchone()
    return {"revision": row["r"] if row else None, "file": full.file}
