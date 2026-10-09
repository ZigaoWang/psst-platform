"""`psst db`: apply migrations and show which are pending."""

from __future__ import annotations

import argparse

from psst.core import db


def register(groups: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    group = groups.add_parser("db", help="apply or list schema migrations")
    commands = group.add_subparsers(dest="command", required=True, metavar="<db command>")
    commands.add_parser("migrate", help="apply pending migrations as the schema owner").set_defaults(run=migrate)
    commands.add_parser("status", help="list pending migrations").set_defaults(run=status)


def migrate(args: argparse.Namespace) -> int:
    applied = db.migrate(db.conninfo("admin"))
    print("\n".join(f"applied {version}" for version in applied) or "nothing to apply")
    return 0


def status(args: argparse.Namespace) -> int:
    waiting = db.pending(db.conninfo("admin"))
    print("\n".join(f"pending {version}" for version in waiting) or "up to date")
    return 0
