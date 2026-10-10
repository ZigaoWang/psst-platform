"""`psst run`: start and end runs. Every change is made under a run, named by its token."""

from __future__ import annotations

import argparse
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg

from psst.core import config, db

ROLE_FOR = {"worker": "worker", "editor": "console", "system": "system"}


def register(groups: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    group = groups.add_parser("run", help="start or end a run")
    commands = group.add_subparsers(dest="command", required=True, metavar="<run command>")
    start = commands.add_parser("start", help="start a run and print its token as shell exports")
    start.add_argument("--kind", choices=sorted(ROLE_FOR), default="worker")
    start.add_argument("--model", help="the model doing the work, such as claude-haiku-5-5 (required for workers)")
    start.add_argument("--notes", default="")
    start.set_defaults(run=start_run)
    end = commands.add_parser("end", help="end the run in PSST_RUN_TOKEN")
    end.add_argument("--notes", default="")
    end.add_argument("--kind", choices=sorted(ROLE_FOR), default="worker")
    end.set_defaults(run=end_run)
    usage = commands.add_parser("tokens", help="record the tokens an ended worker run used")
    usage.add_argument("run_id")
    usage.add_argument("tokens", type=int)
    usage.set_defaults(run=record_tokens)


def start_run(args: argparse.Namespace) -> int:
    if args.kind == "worker" and not args.model:
        raise config.ConfigError("a worker run names its model with --model")
    operator = os.environ.get("USER") or "unknown"
    with db.connect(ROLE_FOR[args.kind]) as conn:  # type: ignore[arg-type]
        row = conn.execute("SELECT * FROM psst.start_run(%s, %s, %s, %s)",
                           (args.kind, operator, args.model, args.notes)).fetchone()
    assert row
    print(f"export PSST_RUN={row['run_id']}\nexport PSST_RUN_TOKEN={row['token']}")
    return 0


def end_run(args: argparse.Namespace) -> int:
    with db.connect(ROLE_FOR[args.kind]) as conn:  # type: ignore[arg-type]
        row = conn.execute("SELECT psst.end_run(%s, %s) AS id", (token(), args.notes)).fetchone()
    assert row
    print(f"ended {row['id']}")
    return 0


def record_tokens(args: argparse.Namespace) -> int:
    with db.connect("worker") as conn:
        conn.execute("SELECT psst.record_run_tokens(%s, %s)", (args.run_id, args.tokens))
    print(f"{args.run_id}: {args.tokens} tokens")
    return 0


def token() -> str:
    return config.require("PSST_RUN_TOKEN")


@contextmanager
def session(conn: psycopg.Connection[dict[str, Any]], kind: str, notes: str,
            model: str | None = None) -> Iterator[str]:
    """A run of `kind` for a command that works on its own (system, publisher, the harness's worker), ended however
    the command ends. Yields the run's token."""
    row = conn.execute("SELECT * FROM psst.start_run(%s, %s, %s, %s)",
                       (kind, os.environ.get("USER") or kind, model, notes)).fetchone()
    conn.commit()
    assert row
    try:
        yield str(row["token"])
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.execute("SELECT psst.end_run(%s)", (row["token"],))
        conn.commit()
