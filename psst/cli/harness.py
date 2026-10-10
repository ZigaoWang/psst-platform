"""`psst harness`: run tasks through API models (decision 28). `run` does one task type on one model; `calibrate`
measures a model against the golden set; `status` shows spend against the budget and the credit left."""

from __future__ import annotations

import argparse
import json
import logging
from typing import Any

from psst.core import db
from psst.harness import providers
from psst.tasks import prompts
from psst.tasks.files import golden_bar

from .runs import session

log = logging.getLogger("psst.harness")


def register(groups: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    group = groups.add_parser("harness", help="run tasks through API models")
    commands = group.add_subparsers(dest="command", required=True, metavar="<harness command>")
    run = commands.add_parser("run", help="lease tasks of one type and do them with one model")
    run.add_argument("--model", required=True, help="<provider>:<model>, such as openrouter:qwen/qwen3.8-flash")
    run.add_argument("--type", required=True, dest="task_type")
    run.add_argument("--city", help="only tasks in this city (its slug)")
    run.add_argument("--limit", type=int, default=1, help="how many tasks at most (default 1)")
    run.add_argument("--max-places", type=int, default=12, help="places one research pass writes at most")
    run.set_defaults(run=run_tasks)
    calibrate = commands.add_parser("calibrate", help="measure a model against the editor's golden set")
    calibrate.add_argument("--model", required=True)
    calibrate.set_defaults(run=run_calibration)
    work = commands.add_parser("work", help="work the queue continuously with the routed models (the service)")
    work.add_argument("--once", action="store_true", help="stop when nothing is waiting")
    work.set_defaults(run=run_work)
    status = commands.add_parser("status", help="spend against the budget, and the credit left")
    status.set_defaults(run=show_status)


def run_tasks(args: argparse.Namespace) -> int:
    from psst.harness.executor import BudgetReached, Executor  # it uses the task commands, which load this module
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    providers.check(args.model)
    done: list[dict[str, Any]] = []
    with db.open_connection(db.conninfo("worker")) as conn, \
            session(conn, "worker", f"harness {args.task_type}", args.model) as token:
        executor = Executor(token, args.model, getattr(args, "max_places", 12))
        city = None
        if args.city:
            row = conn.execute("SELECT id FROM psst.cities WHERE slug = %s", (args.city,)).fetchone()
            city = row["id"] if row else None
        for _ in range(args.limit):
            task = conn.execute("SELECT * FROM psst.lease_task(%s, %s, %s)",
                                (token, [args.task_type], city)).fetchone()
            conn.commit()
            if task is None:
                break
            try:
                outcome = executor.run(dict(task))
            except BudgetReached as reason:
                log.info("stopping: %s", reason)
                executor.give_back({"task": task["id"]}, f"the harness stopped: {reason}")
                break
            log.info("%s", json.dumps(outcome, default=str)[:400])
            done.append(outcome)
    print(json.dumps(done, ensure_ascii=False, indent=2, default=str))
    return 0


def run_calibration(args: argparse.Namespace) -> int:
    """Queue both folds for the model and do them with it; the gate counts it only when it is the routed reviewer."""
    providers.check(args.model)
    with db.open_connection(db.conninfo("system")) as conn, session(conn, "system", "harness calibration") as token:
        bar = golden_bar(conn)
        queued = conn.execute("SELECT psst.queue_calibration(%s, %s, %s, %s) AS n",
                              (token, args.model, prompts.load("review").version,
                               bar["version"] if bar else None)).fetchone()
    print(f"{queued['n'] if queued else 0} calibration folds queued for {args.model}")
    return run_tasks(argparse.Namespace(model=args.model, task_type="calibrate", city=None, limit=2))


def show_status(args: argparse.Namespace) -> int:
    with db.connect("worker") as conn:
        row = conn.execute("""SELECT psst.harness_spend(NULL) AS spend, psst.setting('harness.budget_usd') AS budget,
                                     (SELECT jsonb_agg(x) FROM (
                                        SELECT step, model, count(*) AS calls, sum(input_tokens) AS input,
                                               sum(cached_tokens) AS cached, sum(output_tokens) AS output,
                                               sum(cost_usd) AS cost
                                        FROM psst.harness_calls GROUP BY step, model ORDER BY step, model) x) AS steps
                           """).fetchone()
    status: dict[str, Any] = dict(row) if row else {}
    try:
        status["openrouter"] = providers.credit()
    except OSError as error:
        status["openrouter"] = f"unavailable: {error}"
    print(json.dumps(status, ensure_ascii=False, indent=2, default=str))
    return 0


# The order the service works in: what unblocks publishing first, research last (workers.md).
WORK_ORDER = ["audit", "review", "calibrate", "revise", "research_cell"]
IDLE_SECONDS = 60
CITYLESS = {"calibrate"}


def run_work(args: argparse.Namespace) -> int:
    """Lease and do tasks with whichever harness model each type is routed to, city by city, skipping paused cities,
    until a budget is reached (or, with --once, until nothing is waiting). One run per model, for the whole service."""
    import time
    from contextlib import ExitStack

    from psst.harness.executor import BudgetReached, Executor
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    with db.open_connection(db.conninfo("worker")) as conn, ExitStack() as runs:
        tokens: dict[str, str] = {}
        while True:
            busy = False
            routes = conn.execute("""
                SELECT t.name AS type, psst.task_model(t.name, '{}') AS model FROM psst.task_types t
                WHERE t.runner = 'worker' AND t.active AND t.name = ANY(%s)""", (WORK_ORDER,)).fetchall()
            cities = conn.execute("""SELECT id, slug FROM psst.cities WHERE NOT slug IN (
                                       SELECT jsonb_array_elements_text(psst.setting('harness.paused_cities')))
                                     ORDER BY research_order""").fetchall()
            conn.commit()
            for route in sorted(routes, key=lambda r: WORK_ORDER.index(r["type"])):
                model = route["model"] or ""
                if ":" not in model:
                    continue  # routed to a worker session, not the harness
                if model not in tokens:
                    tokens[model] = runs.enter_context(session(conn, "worker", "harness service", model))
                executor = Executor(tokens[model], model)
                # A calibration belongs to no city; everything else is worked city by city.
                for city_id in [None] if route["type"] in CITYLESS else [c["id"] for c in cities]:
                    task = conn.execute("SELECT * FROM psst.lease_task(%s, %s, %s)",
                                        (tokens[model], [route["type"]], city_id)).fetchone()
                    conn.commit()
                    if task is None:
                        continue
                    busy = True
                    try:
                        log.info("%s", json.dumps(executor.run(dict(task)), default=str)[:400])
                    except BudgetReached as reason:
                        executor.give_back({"task": task["id"]}, f"the harness stopped: {reason}")
                        log.info("stopping: %s", reason)
                        return 0
            if not busy:
                if args.once:
                    return 0
                time.sleep(IDLE_SECONDS)
