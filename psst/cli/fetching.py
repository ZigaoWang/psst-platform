"""`psst fetch`: read a source through the fetch service, which saves what it said as a snapshot."""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from typing import Any

from psst import rules
from psst.core import config, tunnel
from psst.evidence import fetch as reading
from psst.services.fetch_service import PORT

from .runs import token


def register(groups: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    command = groups.add_parser("fetch", help="read a source and save a snapshot of it")
    command.add_argument("url")
    command.add_argument("--title", required=True, help="the page's title, as the source should be cited")
    command.add_argument("--publisher", required=True,
                         help="who published it (a web page's own site name is recorded when it gives one)")
    command.add_argument("--kind", required=True, choices=sorted(rules.load().sources["kinds"]))
    command.add_argument("--language", required=True, help="the page's language, such as en or zh-Hans")
    command.add_argument("--archive", action="store_true", help="read the newest Internet Archive copy")
    command.add_argument("--find", help="show only the paragraphs mentioning these words")
    command.add_argument("--max", type=int, default=12000, help="characters of text to print")
    command.add_argument("--links", action="store_true", help="also list the page's links")
    command.add_argument("--json", action="store_true", help="print the full response as JSON")
    command.set_defaults(run=run)


def service_url() -> str:
    return config.get("PSST_FETCH_URL") or f"http://127.0.0.1:{tunnel.local_port(PORT)}"


def request(payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload).encode()
    call = urllib.request.Request(service_url() + "/read", data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(call, timeout=180) as response:
            return dict(json.loads(response.read()))
    except urllib.error.HTTPError as error:
        detail = json.loads(error.read() or b"{}").get("error", error.reason)
        raise ConnectionError(f"couldn't read the page: {detail}") from None


def run(args: argparse.Namespace) -> int:
    result = request({"token": token(), "url": args.url, "title": args.title, "publisher": args.publisher,
                      "kind": args.kind, "language": args.language, "archive": args.archive})
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    head = [f"snapshot {result['snapshot']} of source {result['source']} ({result['kind']})", f"url: {result['url']}"]
    if result["via"] == "archive":
        head.append(f"read from the Internet Archive copy of {result['archived_at']}")
    if result.get("note"):
        head.append(result["note"])
    text = result["text"]
    if args.find:
        text = reading.passages(text, args.find, args.max)
    elif len(text) > args.max:
        text = text[:args.max] + f"\n\n[{len(result['text']) - args.max} more characters; use --max or --find]"
    print("\n".join(head) + "\n\n" + text)
    if args.links:
        print("\nlinks:\n" + "\n".join(f"- {label or '(no text)'}: {href}" for label, href in result["links"]))
    return 0
