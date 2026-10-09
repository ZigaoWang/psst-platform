"""The writing rules (rules/writing.yaml) applied to one piece of published text."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache

from . import Rulebook, load
from .report import Report

WORD = re.compile(r"[A-Za-z]+")


def _phrase(phrase: str) -> re.Pattern[str]:
    return re.compile(r"(?<![a-z])" + re.escape(phrase.lower()) + r"(?![a-z])")


@dataclass(frozen=True)
class _Patterns:
    banned: list[tuple[str, re.Pattern[str]]]
    soft: list[tuple[str, re.Pattern[str]]]
    guide_phrases: list[tuple[str, re.Pattern[str]]]
    british_suffixes: list[re.Pattern[str]]


@cache
def _compiled(rulebook: Rulebook) -> _Patterns:
    rules = rulebook.writing
    ise = sorted(set(rules["british_ise_stems"]), key=len, reverse=True)
    yse = sorted(set(rules["british_yse_stems"]), key=len, reverse=True)
    return _Patterns(
        banned=[(p, _phrase(p)) for p in rules["banned_phrases"]],
        soft=[(p, _phrase(p)) for p in rules["soft_phrases"]],
        guide_phrases=[(p, _phrase(p)) for p in rules["guide_phrases"]],
        british_suffixes=[
            re.compile(r"\b(" + "|".join(ise) + r")is(" + "|".join(rules["british_ise_endings"]) + r")\b"),
            re.compile(r"\b(" + "|".join(yse) + r")s(" + "|".join(rules["british_yse_endings"]) + r")\b"),
            re.compile(r"\b(" + "|".join(rules["british_our_stems"]) + r")(" + "|".join(rules["british_our_endings"])
                       + r")\b"),
            re.compile(r"\b(" + "|".join(rules["british_re_stems"]) + r")(" + "|".join(rules["british_re_endings"])
                       + r")\b"),
        ],
    )


def check_prose(report: Report, where: str, text: str, rulebook: Rulebook | None = None) -> None:
    """Rules for anything published as Psst's own English text."""
    rulebook = rulebook or load()
    rules = rulebook.writing
    patterns = _compiled(rulebook)
    if text != text.strip():
        report.refuse(where, "starts or ends with whitespace")
    if "  " in text:
        report.refuse(where, "contains a double space")
    for character, what in rules["refused_characters"].items():
        if character in text:
            report.refuse(where, f"contains {what}")
    if "--" in text or " - " in text:
        report.refuse(where, "uses a hyphen as a dash; rewrite")
    lowered = text.lower()
    for phrase, pattern in patterns.banned:
        if pattern.search(lowered):
            report.refuse(where, f"uses '{phrase}'")
    for phrase, pattern in patterns.soft:
        if pattern.search(lowered):
            report.flag(where, f"uses '{phrase}'; is it earning its place?")
    british = rules["british_spellings"]
    flagged = set()
    for match in WORD.finditer(text):
        word = match.group(0)
        if word[0].islower() and word in british:
            report.refuse(where, f"British spelling '{word}'; use '{british[word]}'")
            flagged.add(word)
    for suffix in patterns.british_suffixes:
        for match in suffix.finditer(text):
            if match.group(0)[0].islower() and match.group(0) not in flagged:
                report.refuse(where, f"British spelling '{match.group(0)}'; use the US form")
                flagged.add(match.group(0))


def check_neutral(report: Report, where: str, text: str, rulebook: Rulebook | None = None) -> None:
    """Guide information describes; it never judges or ranks (content.md, section 4.2)."""
    rulebook = rulebook or load()
    rules = rulebook.writing
    words = set(re.findall(r"(?<![A-Za-z])[a-z]+(?:-[a-z]+)*(?![A-Za-z])", text))
    for word in rules["guide_judging_words"]:
        if word in words:
            report.refuse(where, f"'{word}' is a judgment; say what the place is")
    for word in rules["guide_superlatives"]:
        if word in words:
            report.refuse(where, f"'{word}' is a superlative; records belong in stories")
    lowered = text.lower()
    for phrase, pattern in _compiled(rulebook).guide_phrases:
        if pattern.search(lowered):
            report.refuse(where, f"'{phrase}' ranks or pads; say what the place is")


# Abbreviations whose period doesn't end a sentence.
NOT_SENTENCE_END = re.compile(r"(?:\b[A-Z]|\b(?:No|St|Mr|Mrs|Dr|Jr|Sr|Ltd|Co|vs|c|ca))\.$")


def count_sentences(text: str) -> int:
    boundaries = [m for m in re.finditer(r"[.?!][\"')”]?\s+(?=[A-Z0-9\"'“(])", text)
                  if not NOT_SENTENCE_END.search(text[:m.start() + 1])]
    return len(boundaries) + 1
