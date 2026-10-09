"""`psst rules`: the rulebook's version and what it says."""

from __future__ import annotations

import argparse
import json

from psst import rules


def register(groups: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    group = groups.add_parser("rules", help="show the rulebook")
    commands = group.add_subparsers(dest="command", required=True, metavar="<rules command>")
    commands.add_parser("version", help="print the rulebook version").set_defaults(run=version)
    show = commands.add_parser("show", help="print one content type's rules as JSON")
    show.add_argument("type", help="story, guide, photo, trail, or translation")
    show.set_defaults(run=show_type)


def version(args: argparse.Namespace) -> int:
    print(rules.load().version)
    return 0


def show_type(args: argparse.Namespace) -> int:
    print(json.dumps(rules.load().type(args.type), indent=2, ensure_ascii=False))
    return 0
