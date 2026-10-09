"""`psst research`: set up cities and queue research for their most wanted cells (system role)."""

from __future__ import annotations

import argparse
import json

from psst.core import db
from psst.places import research

from .runs import start


def register(groups: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    group = groups.add_parser("research", help="set up cities and queue research")
    commands = group.add_subparsers(dest="command", required=True, metavar="<research command>")
    city = commands.add_parser("setup-city", help="register a city and plan its research cells")
    city.add_argument("--area", type=int, required=True, help="the city's area id in the boundary data")
    city.add_argument("--slug", required=True, help="its short name in links, such as london")
    city.add_argument("--languages", default="", help="local languages, comma separated, such as zh-Hans")
    city.add_argument("--order", type=int, required=True, help="its place in the research order")
    city.set_defaults(run=setup_city)
    queue = commands.add_parser("queue", help="sweep leads for the most wanted open cells and queue research")
    queue.add_argument("--city", required=True)
    queue.add_argument("--cells", type=int, default=10)
    queue.set_defaults(run=queue_cells)



def setup_city(args: argparse.Namespace) -> int:
    with db.open_connection(db.conninfo("system")) as conn:
        planned = research.setup_city(conn, start(conn, "system", "city setup"), args.area, args.slug,
                                      [lang for lang in args.languages.split(",") if lang], args.order)
        conn.commit()
    print(f"{args.slug} is set up; {planned} new research cells planned")
    return 0


def queue_cells(args: argparse.Namespace) -> int:
    with db.open_connection(db.conninfo("system")) as conn:
        token = start(conn, "system", "research planning")
        outcome = research.queue(conn, token, args.city, args.cells)
    print(json.dumps(outcome, indent=2))
    return 0
