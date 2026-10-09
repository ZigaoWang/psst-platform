"""`psst publish`, `psst rollback`, and `psst prune` (publisher role)."""

from __future__ import annotations

import argparse
import json
import os
from typing import Any

import psycopg

from psst.core import config, db
from psst.publish.channels import Channels
from psst.publish.run import PublishError, publish, rollback

WORK = config.ROOT / "work" / "publish"


def register(groups: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    command = groups.add_parser("publish", help="build, stage, check, and promote the output")
    command.add_argument("--only-staging", action="store_true", help="stop after checking staging")
    command.add_argument("--allow-shrink", metavar="REASON", help="allow fewer places or stories, saying why")
    command.set_defaults(run=run_publish)
    back = groups.add_parser("rollback", help="point production back at an earlier version")
    back.add_argument("--to", metavar="VERSION", help="a content version (default: the one before the current)")
    back.set_defaults(run=run_rollback)
    groups.add_parser("prune", help="delete packs no recent version uses").set_defaults(run=run_prune)


def channels() -> Channels:
    host = config.require("PSST_PUBLISH_HOST")
    return Channels(config.require("PSST_PUBLISH_ROOT"), None if host == "local" else host)


def _start(conn: psycopg.Connection[dict[str, Any]]) -> str:
    row = conn.execute("SELECT * FROM psst.start_run('publisher', %s)",
                       (os.environ.get("USER") or "publisher",)).fetchone()
    conn.commit()
    assert row
    return str(row["token"])


def run_publish(args: argparse.Namespace) -> int:
    with db.open_connection(db.conninfo("publisher")) as conn:
        token = _start(conn)
        try:
            outcome = publish(conn, token, channels(), config.require("PSST_PUBLIC_URL"), WORK,
                              only_staging=args.only_staging, allow_shrink=args.allow_shrink)
        except PublishError as error:
            print(f"psst: {error}\n" + "\n".join(f"- {p}" for p in error.problems))
            return 1
    state = "promoted to production" if outcome.promoted else "staged and checked"
    print(f"{outcome.version} {state}: {json.dumps(outcome.counts)}; {len(outcome.changes['added'])} added, "
          f"{len(outcome.changes['updated'])} updated, {len(outcome.changes['removed'])} removed")
    for held in outcome.held:
        print(f"held back: {held}")
    return 0


def run_rollback(args: argparse.Namespace) -> int:
    with db.open_connection(db.conninfo("publisher")) as conn:
        before, after = rollback(conn, _start(conn), channels(), args.to)
    print(f"production moved from {before} back to {after}")
    return 0


def run_prune(args: argparse.Namespace) -> int:
    print(f"{channels().prune()} unused packs deleted")
    return 0
