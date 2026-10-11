"""Revisions made in code, with no model: a review that asks only for a guide's listing details to be cut (its grade,
listing date, or entry) is done by removing the About's sentences that give them, when what is left still makes an
About. The result goes through the same checks and review as any revision."""

from __future__ import annotations

import re
from typing import Any

from psst import rules

ASKS_FOR_LISTING_CUT = re.compile(r"\bcut\b.*\b(listing|listed|grade|heritage status)\b", re.I | re.S)
LISTING = re.compile(r"\b(grade i{1,2}\*?|listed|listing|historic england|national heritage list)\b", re.I)
SENTENCE = re.compile(r"(?<=[.!?])\s+")


def listing_cut(document: dict[str, Any]) -> dict[str, Any] | None:
    """The revision for a guide whose only problems ask to cut its listing details, or None when a model is needed."""
    data = document["data"]
    problems = data.get("problems") or []
    if data.get("type") != "guide" or not problems or not all(ASKS_FOR_LISTING_CUT.search(p) for p in problems):
        return None
    body = dict(data["body"])
    if LISTING.search(body.get("identifier", "")):
        return None  # an identifier is rewritten, not cut
    sentences = SENTENCE.split(body.get("about", "").strip())
    kept = [s for s in sentences if not LISTING.search(s)]
    about = " ".join(kept)
    if len(kept) == len(sentences) or len(kept) < 2 or len(about) < rules.load().type("guide")["schema"][
            "properties"]["about"]["minLength"]:
        return None
    claims = [{"text": c["text"], "kind": c["kind"], "values": c["values"],
               "evidence": [{"snapshot": p["snapshot"], "quote": p["quote"]} for p in c["passages"]]}
              | ({"role": c["role"]} if c.get("role") else {}) for c in data["claims"]]
    return {"body": body | {"about": about}, "claims": claims,
            "reason": "Cut the About's sentences giving the listing, as the review asked."}
