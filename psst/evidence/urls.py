"""Source addresses: the key a source is stored under, archive copies, and addresses that are never sources."""

from __future__ import annotations

import re
import urllib.parse

from psst import rules

ARCHIVE_COPY = re.compile(r"^https?://web\.archive\.org/web/\d+(?:[a-z]{2}_)?/(.+)$", re.I)
TRACKING = ("utm_", "fbclid", "gclid", "spm")


def original(url: str) -> str:
    """The page an Internet Archive copy is a copy of, as https; any other address unchanged."""
    match = ARCHIVE_COPY.match(url.strip())
    if not match:
        return url.strip()
    page = match.group(1)
    if not re.match(r"^https?://", page, re.I):
        page = "https://" + page
    return re.sub(r"^http://", "https://", page, flags=re.I)


def key(url: str) -> str:
    """The key a source is stored under, so one page cited twice is one source: no scheme, no `www.`, the
    desktop Wikipedia host, no trailing slash, sorted query without tracking parameters."""
    parts = urllib.parse.urlsplit(original(url))
    host = parts.netloc.lower().removeprefix("www.").replace(".m.wikipedia.org", ".wikipedia.org")
    path = parts.path.rstrip("/") or "/"
    query = urllib.parse.urlencode(sorted(
        (k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith(TRACKING)))
    return f"{host}{path}" + (f"?{query}" if query else "")


def problem(url: str) -> str | None:
    """Why an address can't be a source, or None."""
    parts = urllib.parse.urlsplit(url.strip())
    if parts.scheme != "https" or not parts.netloc or " " in url:
        return "a source is a full https address without spaces"
    for pattern in rules.load().sources["refused_url_patterns"]:
        if re.search(pattern, url):
            return "search results and generated answers are never sources"
    return None


def is_reference_host(url: str) -> bool:
    host = urllib.parse.urlsplit(original(url)).netloc.lower().removeprefix("www.")
    return any(host == h or host.endswith("." + h) for h in rules.load().sources["reference_hosts"])
