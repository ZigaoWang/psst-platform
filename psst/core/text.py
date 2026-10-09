"""Text normalization for snapshots and quote matching.

Snapshots are stored in NFKC form with normalized line breaks. A quote matches when it appears in the snapshot
after both are folded the same way: curly quotes and apostrophes made straight, every run of whitespace made one
space, and spaces between CJK characters removed (CJK text has no spaces, but extraction sometimes adds them).
Matching is case-sensitive and otherwise exact. Offsets always refer to the stored snapshot text.
"""

from __future__ import annotations

import re
import unicodedata

FOLD = str.maketrans({"‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'", "“": '"', "”": '"', "„": '"', "″": '"',
                      " ": " ", "　": " "})
WHITESPACE = re.compile(r"\s+")
CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿　-〿＀-￯]")


def normalize_snapshot(text: str) -> str:
    """The form a snapshot is stored in: NFKC, Unix line breaks, trailing spaces trimmed, at most one blank line."""
    text = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t\f\v]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def fold(text: str) -> tuple[str, list[int]]:
    """The folded text and, for each of its characters, the offset of the character it came from."""
    text = unicodedata.normalize("NFKC", text).translate(FOLD)
    out: list[str] = []
    origin: list[int] = []
    pending_space = -1
    for index, char in enumerate(text):
        if char.isspace():
            if out and pending_space < 0:
                pending_space = index
            continue
        if pending_space >= 0:
            if not (CJK.match(char) or (out and CJK.match(out[-1]))):
                out.append(" ")
                origin.append(pending_space)
            pending_space = -1
        out.append(char)
        origin.append(index)
    return "".join(out), origin


def find_quote(snapshot: str, quote: str) -> tuple[int, int] | None:
    """Where `quote` appears in `snapshot`, as offsets into `snapshot`, or None."""
    folded_quote, _ = fold(quote)
    if not folded_quote:
        return None
    folded, origin = fold(snapshot)
    at = folded.find(folded_quote)
    if at < 0:
        return None
    return origin[at], origin[at + len(folded_quote) - 1] + 1


def contains(haystack: str, needle: str) -> bool:
    """Case-insensitive containment after folding, for checking a value against a passage."""
    folded_needle = fold(needle)[0].casefold()
    return bool(folded_needle) and folded_needle in fold(haystack)[0].casefold()


WORD = re.compile(r"[0-9A-Za-zÀ-ɏ]+(?:'[A-Za-z]+)?")


def words(text: str) -> list[str]:
    """Lowercase words, for comparing runs of words between prose and sources."""
    return [w.casefold() for w in WORD.findall(fold(text)[0])]
