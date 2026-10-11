"""Repairs and revisions made in code, with no model (decisions 38 and 39). A review that asks only for a guide's
listing details to be cut is done by removing the About's sentences that give them. A name the prose uses that a
cited page states but no claim quotes gets the sentence that states it as a claim of its own; a name only in a page's
label lines (its location, county, or ward) or in no saved page is left for a revision without it. Each result goes
through the same tool checks as any revision."""

from __future__ import annotations

import re
from typing import Any

from psst import rules
from psst.checks.tools import POSSESSIVE, prose_names
from psst.core.text import words
from psst.rules import writing

ASKS_FOR_LISTING_CUT = re.compile(r"\bcut\b.*\b(listing|listed|grade|heritage status)\b", re.I | re.S)
LISTING = re.compile(r"\b(grade i{1,2}\*?|listed|listing|historic england|national heritage list)\b", re.I)
SENTENCE = re.compile(r"(?<=[.!?])\s+")
LABEL_LINE = re.compile(r"^\s*[A-Z][\w /()&-]{0,40}:\s")  # "Location: Holborn, Westminster" names no fact
UNQUOTED_NAME = re.compile(r"isn't in the claims' quotes")
QUOTE_CHARS = 400


def attach_quotes(conn: Any, body: dict[str, Any], claims: list[dict[str, Any]], known: list[str]) -> list[str]:
    """Adds to `claims`, for each name the prose uses that no claim quotes, a claim quoting the sentence of a cited page
    that states it. Returns the names no cited page states outside its label lines."""
    from psst.harness.research import values_in
    quoted = {POSSESSIVE.sub("", w) for w in words(" ".join(
        [e["quote"] for c in claims for e in c["evidence"]] + known))}
    prose = " ".join(v for v in body.values() if isinstance(v, str))
    missing = list(dict.fromkeys(n for n in prose_names(prose, rules.load()) if not set(words(n)) <= quoted))
    if not missing:
        return []
    snapshots = sorted({e["snapshot"] for c in claims for e in c["evidence"]})
    pages = conn.execute("SELECT id, text FROM psst.snapshots WHERE id = ANY(%s) ORDER BY id", (snapshots,)).fetchall()
    unresolved = []
    for name in missing:
        sentence = next(((page["id"], s.strip()) for page in pages for line in page["text"].splitlines()
                         if line.strip() and not LABEL_LINE.match(line)
                         for s in SENTENCE.split(line) if re.search(rf"\b{re.escape(name)}\b", s)
                         and 8 <= len(s.strip()) <= QUOTE_CHARS), None)
        if sentence is None:
            unresolved.append(name)
            continue
        snapshot, quote = sentence
        claims.append({"text": quote, "kind": "attribute",
                       "values": values_in({"evidence": [{"quote": quote}]}),
                       "evidence": [{"snapshot": snapshot, "quote": quote}]})
        quoted |= {POSSESSIVE.sub("", w) for w in words(quote)}
    return unresolved


def code_revision(conn: Any, document: dict[str, Any]) -> dict[str, Any] | None:
    """The revision code can make for a revise task, or None when a model is needed: every problem is a listing cut
    in a guide's About or a name to quote, and each is done."""
    data = document["data"]
    problems = data.get("problems") or []
    cut = [p for p in problems if ASKS_FOR_LISTING_CUT.search(p)]
    names = [p for p in problems if UNQUOTED_NAME.search(p)]
    if not problems or len(cut) + len(names) != len(problems) or data.get("type") not in ("story", "guide"):
        return None
    body = dict(data["body"])
    if cut:
        about = listing_cut(data)
        if about is None:
            return None
        body["about"] = about
    claims = [{"text": c["text"], "kind": c["kind"], "values": c["values"],
               "evidence": [{"snapshot": p["snapshot"], "quote": p["quote"]} for p in c["passages"]]}
              | ({"role": c["role"]} if c.get("role") else {}) for c in data["claims"]]
    known = [str((data.get("place") or {}).get("name") or "")]
    if attach_quotes(conn, body, claims, known):
        return None
    done = (["cut the About's sentences giving the listing"] if cut else []) + \
        (["quoted the sentences that state the names it uses"] if names else [])
    return {"body": body, "claims": claims, "reason": f"Made in code: {' and '.join(done)}."}


def listing_cut(data: dict[str, Any]) -> str | None:
    """A guide's About without its sentences giving the listing, or None when that can't be done by cutting."""
    body = data["body"]
    if data.get("type") != "guide" or LISTING.search(body.get("identifier", "")):
        return None  # an identifier is rewritten, not cut
    sentences = SENTENCE.split(body.get("about", "").strip())
    kept = [s for s in sentences if not LISTING.search(s)]
    about = " ".join(kept)
    spec = rules.load().type("guide")
    if len(kept) == len(sentences) or len(about) < spec["schema"]["properties"]["about"]["minLength"] \
            or writing.count_sentences(about) < spec["about_sentences"]["min"]:  # counted as the check counts
        return None
    return about
