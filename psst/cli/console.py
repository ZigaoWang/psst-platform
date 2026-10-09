"""`psst console`: editor accounts for the admin console (schema owner)."""

from __future__ import annotations

import argparse
import secrets

from psst.core import db


def register(groups: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    group = groups.add_parser("console", help="manage console accounts")
    commands = group.add_subparsers(dest="command", required=True, metavar="<console command>")
    add = commands.add_parser("add-account", help="add an editor account and print its password once")
    add.add_argument("name", help="lowercase letters, digits, dots, dashes, or underscores")
    add.set_defaults(run=add_account)


def add_account(args: argparse.Namespace) -> int:
    password = secrets.token_urlsafe(18)
    with db.connect("admin") as conn:
        conn.execute("SELECT psst.console_add_account(%s, %s)", (args.name, password))
    print(f"Account {args.name} added. Its password, shown only now:\n{password}")
    return 0
