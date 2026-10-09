"""HTTP for shared public services (Wikidata, Wikipedia, OpenStreetMap), with the retries they need. Requests
carry a plain User-Agent and nothing personal."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

USER_AGENT = "PsstPlatform/1.0 (+https://psst.zigao.wang)"
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]


def get_json(url: str, data: bytes | None = None, attempts: int = 5, timeout: int = 90) -> Any:
    last_error: Exception | None = None
    for attempt in range(attempts):
        request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            last_error = error
            if error.code in (400, 403, 404):
                raise
            retry_after = error.headers.get("Retry-After") if error.headers else None
            wait = float(retry_after) if retry_after and retry_after.isdigit() else 3 * (attempt + 1)
            time.sleep(min(wait, 30))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ConnectionError) as error:
            last_error = error
            time.sleep(3 * (attempt + 1))
    raise ConnectionError(f"request failed after {attempts} attempts: {url[:120]} ({last_error})")


def overpass(query: str) -> Any:
    data = urllib.parse.urlencode({"data": query}).encode()
    errors = []
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            return get_json(endpoint, data=data, attempts=3, timeout=180)
        except (ConnectionError, urllib.error.HTTPError) as error:
            errors.append(str(error))
    raise ConnectionError("Overpass unavailable: " + "; ".join(errors))


def wikidata_entities(qids: list[str], props: str = "labels|claims|sitelinks", batch: int = 50) -> dict[str, Any]:
    """Entities by id, following redirects (a redirected id maps to the entity it now points at)."""
    found: dict[str, Any] = {}
    for start in range(0, len(qids), batch):
        chunk = qids[start:start + batch]
        url = ("https://www.wikidata.org/w/api.php?action=wbgetentities&format=json&props="
               + urllib.parse.quote(props) + "&ids=" + "|".join(chunk))
        payload = get_json(url)
        for qid, entity in payload.get("entities", {}).items():
            if "missing" not in entity:
                found[qid] = entity
                redirected = entity.get("redirects", {}).get("from")
                if redirected:
                    found[redirected] = entity
        time.sleep(0.3)
    return found
