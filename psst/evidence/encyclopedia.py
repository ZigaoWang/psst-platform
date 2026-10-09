"""The opening of a place's encyclopedia article, which the whole-item check compares a story with: a story whose
surprise is already there fails the "so what" test (content.md, section 2)."""

from __future__ import annotations

import urllib.parse
from collections.abc import Callable
from typing import Any

from psst.core import http

Reader = Callable[[dict[str, Any]], dict[str, Any]]
LEAD_CHARS = 2500


def article_url(wikidata_id: str, languages: tuple[str, ...] = ("en", "zh")) -> str | None:
    entity = http.wikidata_entities([wikidata_id], props="sitelinks").get(wikidata_id) or {}
    for language in languages:
        title = entity.get("sitelinks", {}).get(f"{language}wiki", {}).get("title")
        if title:
            return f"https://{language}.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
    return None


def lead(place: dict[str, Any], read: Reader) -> dict[str, Any] | None:
    """The article's opening through `read` (the fetch service), or None when the place has no article."""
    if not place.get("wikidata_id"):
        return None
    url = article_url(place["wikidata_id"])
    if not url:
        return None
    language = "zh-Hans" if url.startswith("https://zh.") else "en"
    page = read({"url": url, "title": urllib.parse.unquote(url.rsplit("/", 1)[1]).replace("_", " "),
                 "publisher": "Wikipedia", "kind": "reference", "language": language})
    return {"url": url, "snapshot": page["snapshot"], "text": page["text"][:LEAD_CHARS]}
