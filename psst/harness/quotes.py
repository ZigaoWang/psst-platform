"""Holding a cheap model to exact quotes (decision 28). Models often retype a passage with a word or two changed, or
cite a snapshot under a mistyped id. Before an answer is checked, each quote is matched against the snapshot it cites,
or, when that id doesn't exist, against the snapshots read for this item: a passage that matches at least nine words
in ten becomes the snapshot's exact text. Anything further off is left for the checks to refuse. The checks, the
review, and the audit then judge the claim against the real passage."""

from __future__ import annotations

import difflib
import re
from typing import Any

import psycopg

from psst.core.text import find_quote

Connection = psycopg.Connection[dict[str, Any]]

WORD = re.compile(r"\w+(?:'\w+)?")
MIN_RATIO = 0.9


def nearest(text: str, quote: str) -> str | None:
    """The span of `text` whose words best match the quote's, if it matches at least MIN_RATIO."""
    if find_quote(text, quote):
        return None  # already exact
    wanted = [w.casefold() for w in WORD.findall(quote)]
    if len(wanted) < 4:
        return None
    spans = list(WORD.finditer(text))
    words = [m.group(0).casefold() for m in spans]
    first = set(wanted[:3])
    best, best_span = 0.0, None
    for size in {len(wanted) - 1, len(wanted), len(wanted) + 1}:
        for i in range(0, max(0, len(words) - size) + 1):
            if words[i] not in first and words[i + size - 1] != wanted[-1]:
                continue  # windows that share neither end are far off; skip them cheaply
            ratio = difflib.SequenceMatcher(None, wanted, words[i:i + size], autojunk=False).ratio()
            if ratio > best:
                best, best_span = ratio, (spans[i].start(), spans[i + size - 1].end())
    if best >= MIN_RATIO and best_span:
        return text[best_span[0]:best_span[1]]
    return None


def repair(conn: Connection, answer: dict[str, Any], read: set[str]) -> int:
    """Fix near quotes and mistyped snapshot ids in place in every claim of the answer; returns how many changed."""
    texts: dict[str, str | None] = {}

    def text(snapshot: str) -> str | None:
        if snapshot not in texts:
            row = conn.execute("SELECT text FROM psst.snapshots WHERE id = %s", (snapshot,)).fetchone()
            texts[snapshot] = row["text"] if row else None
        return texts[snapshot]

    changed = 0
    for evidence in _evidence(answer):
        quote, cited = evidence.get("quote"), evidence.get("snapshot")
        if not isinstance(quote, str) or not isinstance(cited, str):
            continue
        candidates = [cited] if text(cited) is not None else sorted(read)
        for snapshot in candidates:
            source = text(snapshot)
            if source is None:
                continue
            if find_quote(source, quote):
                if snapshot != cited:
                    evidence["snapshot"] = snapshot
                    changed += 1
                break
            exact = nearest(source, quote)
            if exact:
                evidence["snapshot"], evidence["quote"] = snapshot, exact
                changed += 1
                break
    return changed


def _evidence(value: Any) -> list[dict[str, Any]]:
    """Every evidence entry ({snapshot, quote}) anywhere in an answer."""
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if "snapshot" in value and "quote" in value:
            found.append(value)
        for v in value.values():
            found += _evidence(v)
    elif isinstance(value, list):
        for v in value:
            found += _evidence(v)
    return found
