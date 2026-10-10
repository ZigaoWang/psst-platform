"""Constructed negatives for the review gate (decision 31). Each takes one of the editor's good golden stories and
breaks it in one known way, so the right mark is known without the editor: the reviewer must hold it back or name
the fix. Every story also gets its claims (the sentences of the unbroken story), which is how a reviewer can see that
a changed date or an added sentence is not supported. A near paraphrase of a source is left out: judging it needs
the source page, and the tool checks refuse it before any review."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

SENTENCE = re.compile(r"[^.!?]+[.!?]")
NUMBER = re.compile(r"\b(1[0-9]{3}|20[0-2][0-9]|[1-9][0-9]{1,5})\b")


def sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE.findall(text or "") if len(s.split()) >= 4]


def claims_of(story: dict[str, Any]) -> list[str]:
    """What the sources confirm for this story: its own sentences, as claims."""
    seen: list[str] = []
    for s in sentences(story["short"]) + sentences(story["long"]):
        if s not in seen:
            seen.append(s)
    return seen


def _number_mismatch(s: dict[str, Any]) -> dict[str, Any] | None:
    match = NUMBER.search(s["long"])
    if not match:
        return None
    old = int(match.group(0))
    new = old + 7 if 1000 <= old <= 2025 else old * 2
    long = s["long"][:match.start()] + str(new) + s["long"][match.end():]
    return {"long": long, "reason": f"a number changed: the prose says {new} where the claims say {old}"}


def _unsupported_claim(s: dict[str, Any]) -> dict[str, Any] | None:
    years = [int(y) for y in re.findall(r"\b(1[0-9]{3})\b", s["long"])]
    year = (max(years) + 13) if years else 1911
    added = f" In {year} it was sold to a private collector for 4,000 pounds."
    return {"long": s["long"].rstrip() + added, "reason": "an added claim no source supports: a sale in "
            f"{year}"}


def _look_at_nothing(s: dict[str, Any]) -> dict[str, Any] | None:
    return {"look": "Look around and imagine the scene as it once was.",
            "reason": "the look points at nothing a reader can see"}


def _encyclopedia_opening(s: dict[str, Any]) -> dict[str, Any] | None:
    opening = f"{s['place']} is a historic site in London with a long and varied history."
    return {"short": opening + " " + s["short"], "long": opening + " " + s["long"],
            "reason": "an encyclopedia-style opening before the surprise"}


def _speculative_ending(s: dict[str, Any]) -> dict[str, Any] | None:
    return {"long": s["long"].rstrip() + " Perhaps that is why it still stands today, though nobody can say for sure.",
            "reason": "a speculative ending"}


def _slop(s: dict[str, Any]) -> dict[str, Any] | None:
    return {"long": "Nestled in a vibrant neighborhood, this hidden gem is a testament to the area's rich history. "
            + s["long"], "reason": "slop phrases: nestled, vibrant, hidden gem, testament, rich history"}


def _duplicated_sentence(s: dict[str, Any]) -> dict[str, Any] | None:
    found = sentences(s["long"])
    if len(found) < 2:
        return None
    return {"long": s["long"].rstrip() + " " + found[0], "reason": "a duplicated sentence"}


DEFECTS: dict[str, Callable[[dict[str, Any]], dict[str, Any] | None]] = {
    "number_mismatch": _number_mismatch, "unsupported_claim": _unsupported_claim,
    "look_at_nothing": _look_at_nothing, "encyclopedia_opening": _encyclopedia_opening,
    "speculative_ending": _speculative_ending, "slop": _slop, "duplicated_sentence": _duplicated_sentence,
}


def construct(good: list[dict[str, Any]], per_defect: int = 6) -> list[dict[str, Any]]:
    """`per_defect` broken copies for each defect, taking the good stories in turn so each is broken in different
    ways; plus the claims of every good story."""
    rows: list[dict[str, Any]] = [{"claims_for": s["id"], "claims": claims_of(s)} for s in good]
    turn = 0
    for defect, breaks in DEFECTS.items():
        made = 0
        tried = 0
        while made < per_defect and tried < len(good):
            story = good[turn % len(good)]
            turn += 1
            tried += 1
            change = breaks(story)
            if change is None:
                continue
            reason = change.pop("reason")
            rows.append({"from": story["id"], "defect": defect, "reason": f"constructed: {reason}",
                         "headline": story["headline"], "short": story["short"], "long": story["long"],
                         "look": story.get("look")} | change)
            made += 1
    return rows
