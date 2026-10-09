"""`psst place`: look up places for research."""

from __future__ import annotations

import argparse
import json

from psst.places import lookup


def register(groups: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    group = groups.add_parser("place", help="look up places")
    commands = group.add_subparsers(dest="command", required=True, metavar="<place command>")
    find = commands.add_parser("find", help="find the Wikidata item or OSM element for a place near a point")
    find.add_argument("name")
    find.add_argument("--near", required=True, help="latitude,longitude, such as the cell's middle")
    find.add_argument("--radius", type=int, default=1500, help="meters (default 1500)")
    find.add_argument("--language", default="en", help="the language of the name, such as zh")
    find.set_defaults(run=run_find)


def run_find(args: argparse.Namespace) -> int:
    lat, lon = (float(part) for part in args.near.split(","))
    print(json.dumps(lookup.find(args.name, lat, lon, args.radius, args.language), ensure_ascii=False, indent=2))
    return 0
