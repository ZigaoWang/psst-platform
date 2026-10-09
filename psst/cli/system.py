"""`psst system`: the system worker and audit planning (system role)."""

from __future__ import annotations

import argparse
import logging
import os

from psst.core import db
from psst.services.system_worker import SystemWorker


def register(groups: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    group = groups.add_parser("system", help="run the system worker")
    commands = group.add_subparsers(dest="command", required=True, metavar="<system command>")
    work = commands.add_parser("work", help="run tool checks and other system tasks")
    work.add_argument("--once", action="store_true", help="stop when no task is waiting")
    work.set_defaults(run=run_work)
    audits = commands.add_parser("plan-audits", help="group accepted work into audit batches")
    audits.add_argument("--force", action="store_true", help="also batch groups smaller than the minimum")
    audits.set_defaults(run=run_plan_audits)


def _worker() -> SystemWorker:
    info = db.conninfo("system")
    with db.open_connection(info) as conn:
        row = conn.execute("SELECT * FROM psst.start_run('system', %s, NULL, 'system worker')",
                           (os.environ.get("USER") or "system",)).fetchone()
        conn.commit()
    assert row
    return SystemWorker(lambda: db.open_connection(info), row["token"])


def run_work(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    _worker().work(once=args.once)
    return 0


def run_plan_audits(args: argparse.Namespace) -> int:
    print(f"{_worker().plan_audits(force=args.force)} audit batches planned")
    return 0
