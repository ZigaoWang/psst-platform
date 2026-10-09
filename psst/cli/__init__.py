"""The `psst` command. Each command group is a module in this package with a `register(subparsers)` function."""

from __future__ import annotations

import argparse
import sys

import psycopg

from psst.core.config import ConfigError

from . import console, database, fetching, publishing, rulebook, runs, system, tasks

GROUPS = [runs, tasks, fetching, system, publishing, console, database, rulebook]


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="psst", description="The Psst content platform.")
    groups = root.add_subparsers(dest="group", required=True, metavar="<command>")
    for group in GROUPS:
        group.register(groups)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return int(args.run(args) or 0)
    except (ConfigError, ConnectionError) as error:
        print(f"psst: {error}", file=sys.stderr)
        return 2
    except psycopg.Error as error:
        message = error.diag.message_primary if error.diag and error.diag.message_primary else str(error)
        print(f"psst: {message}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
