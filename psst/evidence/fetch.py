"""Reading a source as plain text.

Many sites refuse scripts or have gone; then the newest Internet Archive copy is read instead. A Historic England
list entry whose text is loaded by script is read from British Listed Buildings, which republishes the same
official entry. Either way the source is the original address. Only public internet addresses are read, so a
link or redirect can never reach the server's own network.
"""

from __future__ import annotations

import gzip
import html
import http.client
import io
import ipaddress
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
import zlib
from dataclasses import dataclass, field
from html.parser import HTMLParser

import pypdf

from psst.core import http as shared_http
from psst.core.text import normalize_snapshot

TIMEOUT = 30
MAX_BYTES = 8_000_000


@dataclass
class Page:
    url: str                      # what was actually read
    status: int
    title: str
    text: str
    via: str = "live"             # live, archive, or mirror
    archived_at: str | None = None
    links: list[tuple[str, str]] = field(default_factory=list)
    note: str | None = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 400 and bool(self.text)


class _Text(HTMLParser):
    """Visible text with paragraph breaks; scripts, styles, navigation, and footers dropped."""
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "aside", "template"}
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article", "blockquote",
             "dd", "dt", "td", "th", "table", "pre", "figcaption"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self.links: list[tuple[str, str]] = []
        self._skip = 0
        self._in_title = False
        self._href: str | None = None
        self._link_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._link_text = []
        if tag in self.SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href:
            self.links.append((re.sub(r"\s+", " ", "".join(self._link_text)).strip(), self._href))
            self._href = None
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._link_text.append(data)
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


def is_public(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(parts.hostname, parts.port or 443)}
    except OSError:
        return True  # unresolvable: the request fails on its own and says so
    return all(ipaddress.ip_address(str(a).split("%")[0]).is_global for a in addresses)


class Reader:
    """Reads pages. `public_only` is off only in tests, which serve pages from this machine."""

    def __init__(self, public_only: bool = True) -> None:
        self.public_only = public_only
        reader = self

        class Redirects(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
                if reader.public_only and not is_public(newurl):
                    raise urllib.error.HTTPError(newurl, 403, "redirect to a private address", headers, fp)
                return super().redirect_request(req, fp, code, msg, headers, newurl)

        self._opener = urllib.request.build_opener(Redirects)

    def read(self, url: str, archive: bool = False) -> Page:
        page = self._read(url, archive)
        entry = HISTORIC_ENGLAND.search(url)
        # A list entry's own text includes its grid reference; a page without one is only the site's frame.
        if entry and "ngr" not in page.text.lower():
            mirror = self._read(f"https://britishlistedbuildings.co.uk/10{entry.group(1)}", False)
            if mirror.ok and len(mirror.text) > len(page.text):
                mirror.via = "mirror"
                mirror.note = "Historic England's page held no list entry text; this is the same entry from British " \
                              "Listed Buildings."
                return mirror
        return page

    def _get(self, url: str) -> tuple[int, str, bytes]:
        """(status, content type, body). A failure to connect is status 0, never an exception."""
        if self.public_only and not is_public(url):
            return 403, "", b""
        request = urllib.request.Request(url, headers={"User-Agent": shared_http.USER_AGENT,
                                                       "Accept": "text/html,application/pdf,*/*"})
        try:
            with self._opener.open(request, timeout=TIMEOUT) as response:
                body = response.read(MAX_BYTES)
                encoding = (response.headers.get("Content-Encoding") or "").lower()
                return response.status, response.headers.get("Content-Type", ""), _decompress(body, encoding)
        except urllib.error.HTTPError as error:
            return error.code, "", b""
        except (OSError, ValueError, http.client.HTTPException):
            return 0, "", b""

    def _archive_copy(self, url: str) -> tuple[str, str] | None:
        """The newest good Internet Archive copy: (raw copy address, timestamp)."""
        query = urllib.parse.urlencode({"url": url, "output": "json", "filter": "statuscode:200", "limit": "-1"})
        try:
            rows = shared_http.get_json(f"https://web.archive.org/cdx/search/cdx?{query}", attempts=2, timeout=40)
        except (ConnectionError, urllib.error.HTTPError):
            return None
        if len(rows) < 2:
            return None
        stamp, page = rows[-1][1], rows[-1][2]
        return f"https://web.archive.org/web/{stamp}id_/{page}", stamp

    def _read(self, url: str, archive: bool) -> Page:
        url = WAYBACK.sub(r"\1id_\2", url)
        status = None
        if not archive:
            status, content_type, body = self._get(url)
            if 200 <= status < 400 and body:
                page = _page(url, status, content_type, body)
                if page.ok:
                    return page
        copy = self._archive_copy(url)
        if not copy:
            reason = "there's no archived copy" if archive else \
                f"the site answered {status or 'nothing'} and there's no archived copy"
            return Page(url, status or 0, "", "", note=f"Couldn't read this page: {reason}.")
        copy_url, stamp = copy
        status, content_type, body = self._get(copy_url)
        if not (200 <= status < 400 and body):
            return Page(copy_url, status, "", "", note=f"The archived copy answered {status}.")
        page = _page(copy_url, status, content_type, body)
        page.via, page.archived_at = "archive", f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}"
        return page


HISTORIC_ENGLAND = re.compile(r"historicengland\.org\.uk/listing/the-list/list-entry/(\d+)", re.I)
WAYBACK = re.compile(r"^(https?://web\.archive\.org/web/\d+)(?!id_)(/.+)$", re.I)


def _decompress(body: bytes, encoding: str) -> bytes:
    """Archived copies come back exactly as captured, sometimes still compressed."""
    try:
        if body[:2] == b"\x1f\x8b" or "gzip" in encoding:
            return gzip.decompress(body)
        if "deflate" in encoding:
            return zlib.decompress(body)
    except (OSError, zlib.error):
        pass
    return body


def _decode(body: bytes, content_type: str) -> str:
    """Text in its declared encoding: the header, else the page's <meta> tag, else UTF-8, else GB18030 for older
    Chinese pages that declare nothing."""
    declared = re.search(r"charset=[\"']?([\w-]+)", content_type)
    name: str | None = declared.group(1) if declared else None
    if not name:
        meta = re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", body[:4096], re.I)
        name = meta.group(1).decode("ascii", "ignore") if meta else None
    if name and name.lower() in ("gb2312", "gbk", "gb_2312-80"):
        name = "gb18030"  # a superset of both
    if name:
        try:
            return body.decode(name, errors="replace")
        except LookupError:
            pass
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return body.decode("gb18030", errors="replace")


def _page(url: str, status: int, content_type: str, body: bytes) -> Page:
    if "pdf" in content_type or body[:5] == b"%PDF-":
        return _pdf(url, status, body)
    decoded = _decode(body, content_type)
    if "html" not in content_type and not decoded.lstrip().startswith("<"):
        return Page(url, status, "", normalize_snapshot(decoded))
    parser = _Text()
    parser.feed(decoded)
    links, seen = [], set()
    for text, href in parser.links:
        absolute = urllib.parse.urljoin(url, href)
        if absolute.startswith("http") and absolute not in seen:
            seen.add(absolute)
            links.append((text, absolute))
    return Page(url, status, html.unescape(parser.title).strip(), normalize_snapshot("".join(parser.parts)),
                links=links)


def _pdf(url: str, status: int, body: bytes) -> Page:
    """A PDF's text, page by page. Scanned PDFs have no text layer and come back empty."""
    try:
        reader = pypdf.PdfReader(io.BytesIO(body))
        pages = [f"[Page {n}]\n{(page.extract_text() or '').strip()}" for n, page in enumerate(reader.pages, 1)]
        title = str(reader.metadata.title or "") if reader.metadata else ""
    except Exception:  # pypdf raises many kinds of errors on damaged files
        return Page(url, status, "", "", note="This PDF couldn't be read.")
    text = normalize_snapshot("\n\n".join(pages))
    if not re.search(r"\w{3}", re.sub(r"\[Page \d+\]", "", text)):
        return Page(url, status, title, "", note="This PDF has no text layer; it's probably scanned images.")
    return Page(url, status, title, text)


STOPWORDS = {"the", "and", "for", "was", "were", "that", "this", "with", "from", "into", "its", "his", "her",
             "their", "they", "been", "has", "had", "are", "but", "not", "who", "which", "when", "where", "one"}


def passages(text: str, find: str, limit: int = 4000, most: int = 6) -> str:
    """Only the paragraphs that mention the given words (and the one before each), in page order."""
    terms = {t for t in re.findall(r"\w+", find.lower()) if (len(t) > 2 or t.isdigit()) and t not in STOPWORDS}
    paragraphs = [p.strip() for p in re.split(r"\n", text) if p.strip()]
    if not terms or not paragraphs:
        return text[:limit]
    scored = []
    for index, paragraph in enumerate(paragraphs):
        lowered = paragraph.lower()
        found = set(re.findall(r"\w+", lowered))
        hits = len(terms & found) + sum(1 for t in terms if t not in found and (len(t) > 5 or not t.isascii())
                                        and t in lowered)
        if hits:
            scored.append((hits, index))
    if not scored:
        return f"(None of {', '.join(sorted(terms))} appear on this page. Its opening:)\n\n" + text[:1500]
    best = sorted(scored, key=lambda s: (-s[0], s[1]))[:most]
    keep = sorted({i for _, i in best} | {i - 1 for _, i in best if i > 0})
    out: list[str] = []
    used, previous = 0, None
    for i in keep:
        if previous is not None and i != previous + 1:
            out.append("[...]")
        piece = paragraphs[i]
        if used + len(piece) > limit:
            out.append(piece[:max(0, limit - used)] + " [...]")
            break
        out.append(piece)
        used += len(piece)
        previous = i
    return "\n\n".join(out)
