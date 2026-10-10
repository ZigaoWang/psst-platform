"""Holding a cheap model to exact quotes (decision 28). Models often retype a passage with a word or two changed, or
cite a snapshot under a mistyped id. Before an answer is checked, each quote is matched against the snapshot it cites,
or, when that id doesn't exist, against the snapshots read for this item. A passage whose words match the quote's at a
similarity of 0.95 or more (at most about one word in twenty different) becomes the snapshot's exact text; anything
further off is an invented quote, left for the checks to refuse. Every repair is logged on its place and shown to the
reviewer and auditor beside the claim, who judge it against the real passage (decision 30)."""

from __future__ import annotations

import difflib
import re
from typing import Any

import psycopg

from psst.core.text import find_quote

Connection = psycopg.Connection[dict[str, Any]]

WORD = re.compile(r"\w+(?:'\w+)?")
MIN_RATIO = 0.95


def nearest(text: str, quote: str) -> tuple[str, float] | None:
    """The span of `text` whose words best match the quote's, with the similarity, if it reaches MIN_RATIO."""
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
        return text[best_span[0]:best_span[1]], round(best, 3)
    return None


def repair(conn: Connection, answer: dict[str, Any], read: set[str]) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Fix near quotes and mistyped snapshot ids in place in every claim of the answer. Returns the counts (quotes,
    exact, repaired, invented, unknown_snapshot) and each repair."""
    texts: dict[str, str | None] = {}

    def text(snapshot: str) -> str | None:
        if snapshot not in texts:
            row = conn.execute("SELECT text FROM psst.snapshots WHERE id = %s", (snapshot,)).fetchone()
            texts[snapshot] = row["text"] if row else None
        return texts[snapshot]

    stats = {"quotes": 0, "exact": 0, "repaired": 0, "invented": 0, "unknown_snapshot": 0}
    repairs: list[dict[str, Any]] = []
    for evidence in _evidence(answer):
        quote, cited = evidence.get("quote"), evidence.get("snapshot")
        if not isinstance(quote, str) or not isinstance(cited, str):
            continue
        stats["quotes"] += 1
        known = text(cited) is not None
        stats["unknown_snapshot"] += not known
        outcome = "invented"
        for snapshot in [cited] if known else sorted(read):
            source = text(snapshot)
            if source is None:
                continue
            if find_quote(source, quote):
                outcome = "exact" if snapshot == cited else "repaired"
                if snapshot != cited:
                    repairs.append({"snapshot": snapshot, "written": f"[{cited}] {quote}", "exact": quote,
                                    "similarity": 1.0})
                    evidence["snapshot"] = snapshot
                break
            match = nearest(source, quote)
            if match:
                exact, similarity = match
                repairs.append({"snapshot": snapshot, "written": quote, "exact": exact, "similarity": similarity})
                evidence["snapshot"], evidence["quote"] = snapshot, exact
                outcome = "repaired"
                break
        stats[outcome] += 1
    return stats, repairs


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
