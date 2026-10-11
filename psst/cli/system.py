"""`psst system`: the system worker and audit planning (system role)."""

from __future__ import annotations

import argparse
import json
import logging

from psycopg.types.json import Jsonb

from psst.checks import rechecks
from psst.core import db
from psst.services import intake as reader_intake
from psst.services.fetch_service import FetchService, serve
from psst.services.system_worker import SystemWorker

from .runs import session


def register(groups: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    group = groups.add_parser("system", help="run the system worker")
    commands = group.add_subparsers(dest="command", required=True, metavar="<system command>")
    work = commands.add_parser("work", help="run tool checks and other system tasks")
    work.add_argument("--once", action="store_true", help="stop when no task is waiting")
    work.set_defaults(run=run_work)
    fetcher = commands.add_parser("serve-fetch", help="run the fetch service on this machine's loopback interface")
    fetcher.set_defaults(run=run_fetch)
    intake = commands.add_parser("serve-intake", help="run reader intake (reports and demand) on the loopback")
    intake.set_defaults(run=run_intake)
    recheck = commands.add_parser("recheck-rules", help="check again everything last checked under an older rulebook")
    recheck.set_defaults(run=run_recheck)
    setting = commands.add_parser("set", help="change a setting, with the reason recorded beside it")
    setting.add_argument("key", help="such as routing.research_writer")
    setting.add_argument("value", help="the new value as JSON, such as '\"openrouter:deepseek/deepseek-v4.1-flash\"'")
    setting.add_argument("--reason", required=True, help="why it changes; shown in the console and the reports")
    setting.set_defaults(run=run_set)
    again = commands.add_parser("review-again",
                                help="send a research cell's accepted stories and guides back to review")
    again.add_argument("--cell", required=True, help="the research cell, such as 87194ad32ffffff")
    again.add_argument("--reason", required=True, help="why they are reviewed again; recorded on each item")
    again.set_defaults(run=run_review_again)
    audits = commands.add_parser("plan-audits", help="group accepted work into audit batches")
    audits.add_argument("--force", action="store_true", help="also batch groups smaller than the minimum")
    audits.set_defaults(run=run_plan_audits)


def run_work(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    info = db.conninfo("system")
    with db.open_connection(info) as conn, session(conn, "system", "system worker") as token:
        SystemWorker(lambda: db.open_connection(info), token).work(once=args.once)
    return 0


def run_set(args: argparse.Namespace) -> int:
    value = json.loads(args.value)
    with db.open_connection(db.conninfo("system")) as conn, session(conn, "system", "setting change") as token:
        old = conn.execute("SELECT psst.setting(%s) AS v", (args.key,)).fetchone()
        conn.execute("SELECT psst.change_setting(%s, %s, %s, %s)", (token, args.key, Jsonb(value), args.reason))
        conn.commit()
    print(f"{args.key}: {json.dumps(old['v'] if old else None)} -> {json.dumps(value)}")
    return 0


def run_review_again(args: argparse.Namespace) -> int:
    with db.open_connection(db.conninfo("system")) as conn, session(conn, "system", "review again") as token:
        items = [r["id"] for r in conn.execute("""
            SELECT i.id FROM psst.items i JOIN psst.places p ON p.id = i.place_id
            WHERE p.h3_r7 = %s AND i.state = 'accepted' AND i.type IN ('story', 'guide')
            ORDER BY i.id""", (args.cell,))]
        for item in items:
            conn.execute("SELECT psst.review_again(%s, %s, %s)", (token, item, args.reason))
            conn.commit()
    print(f"{len(items)} items of {args.cell} sent back to review")
    return 0


def run_plan_audits(args: argparse.Namespace) -> int:
    info = db.conninfo("system")
    with db.open_connection(info) as conn, session(conn, "system", "audit planning") as token:
        planned = SystemWorker(lambda: db.open_connection(info), token).plan_audits(force=args.force)
    print(f"{planned} audit batches planned")
    return 0


def run_fetch(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    info = db.conninfo("system")
    with db.open_connection(info) as conn, session(conn, "system", "fetch service") as token:
        server = serve(FetchService(lambda: db.open_connection(info), token))
        logging.getLogger("psst.fetch").info("listening on %s:%s", *server.server_address[:2])
        server.serve_forever()
    return 0


def run_intake(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    info = db.conninfo("api")
    server = reader_intake.serve(reader_intake.Intake(lambda: db.open_connection(info, autocommit=True)))
    logging.getLogger("psst.intake").info("listening on %s:%s", *server.server_address[:2])
    server.serve_forever()
    return 0


def run_recheck(args: argparse.Namespace) -> int:
    with db.open_connection(db.conninfo("system")) as conn, session(conn, "system", "rulebook recheck") as token:
        print(json.dumps(rechecks.recheck(conn, token)))
    return 0
