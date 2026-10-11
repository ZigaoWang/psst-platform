"""`psst harness`: run tasks through API models (decision 28). `run` does one task type on one model; `calibrate`
measures a model against the golden set; `status` shows spend against the budget and the credit left."""

from __future__ import annotations

import argparse
import json
import logging
from datetime import UTC, datetime
from typing import Any

from psycopg.types.json import Jsonb

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
    run.add_argument("--max-leads", type=int, help="leads one research pass takes at most (a trial run)")
    run.set_defaults(run=run_tasks)
    calibrate = commands.add_parser("calibrate", help="measure a model against the editor's golden set")
    calibrate.add_argument("--model", required=True)
    calibrate.set_defaults(run=run_calibration)
    work = commands.add_parser("work", help="work the queue continuously with the routed models (the service)")
    work.add_argument("--once", action="store_true", help="stop when nothing is waiting")
    work.set_defaults(run=run_work)
    negatives = commands.add_parser("negatives", help="rebuild the golden set's constructed negatives")
    negatives.add_argument("--per-defect", type=int, default=6)
    negatives.set_defaults(run=run_negatives)
    trial = commands.add_parser("trial", help="several writers write the same leads, stored nowhere, then reviewed")
    trial.add_argument("--models", required=True, help="comma-separated, such as openrouter:z-ai/glm-5.3,...")
    trial.add_argument("--cell", required=True, help="the research cell whose waiting leads they write")
    trial.add_argument("--leads", type=int, default=20, help="how many of its leads (default 20)")
    trial.set_defaults(run=run_trial)
    status = commands.add_parser("status", help="spend against the budget, and the credit left")
    status.set_defaults(run=show_status)
    report = commands.add_parser("report", help="what the harness did since a time: cells, places, cost, skips")
    report.add_argument("--since", required=True, help="a time, such as 2026-10-11T00:00:00Z")
    report.add_argument("--samples", type=int, default=5, help="stories to show")
    report.set_defaults(run=show_report)


def run_tasks(args: argparse.Namespace) -> int:
    from psst.harness.executor import BudgetReached, Executor  # it uses the task commands, which load this module
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    providers.check(args.model)
    done: list[dict[str, Any]] = []
    with db.open_connection(db.conninfo("worker")) as conn, \
            session(conn, "worker", f"harness {args.task_type}", args.model) as token:
        executor = Executor(token, args.model, getattr(args, "max_places", 12), getattr(args, "max_leads", None))
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


def run_trial(args: argparse.Namespace) -> int:
    """Each model writes the cell's first leads through the research path with every check, nothing stored; the
    routed reviewer marks it all; cost per accepted place and three samples per model."""
    from psst.cli import tasks as task_cli
    from psst.harness import trial
    from psst.harness.executor import GaveUp
    from psst.tasks import files
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    for model in models:
        providers.check(model)
    with db.connect("worker") as conn:
        task = conn.execute("""SELECT * FROM psst.tasks WHERE type = 'research_cell' AND state = 'queued'
                               AND input ->> 'cell' = %s ORDER BY created_at DESC LIMIT 1""", (args.cell,)).fetchone()
        if task is None:
            print(f"no research of {args.cell} is waiting")
            return 1
        task = dict(task)
        document = json.loads(json.dumps(files.build(conn, task, files.Lookups(
            task_cli._lead, task_cli._key_facts, task_cli._photo_candidates, task_cli._photo_file)), default=str))
        document["data"]["leads"] = document["data"]["leads"][:args.leads]
        routed = conn.execute("SELECT psst.task_model('review', '{}') AS m").fetchone()
        assert routed
        reviewer = routed["m"]
        shared = trial.shared_review_data(conn, task)
    rows: dict[str, Any] = {}
    for model in models:
        with db.open_connection(db.conninfo("worker")) as conn, \
                session(conn, "worker", "harness trial", model) as token:
            started = datetime.now(UTC)
            try:
                placed, unwritten = trial.write(token, model, task, document | {"run_token": token})
            except GaveUp as reason:  # one model that can't work through the path doesn't end the trial
                rows[model] = {"gave_up": str(reason)[:500], "writing": spent(conn, model, started)}
                continue
            written = spent(conn, model, started)
        with db.open_connection(db.conninfo("worker")) as conn, \
                session(conn, "worker", "harness trial review", reviewer) as token:
            started = datetime.now(UTC)
            items = trial.review_items(placed)
            marks = trial.review(token, reviewer, task, items, shared) if items else []
            reviewed = spent(conn, reviewer, started)
        result = trial.outcome(placed, items, marks)
        accepted = result["accepted"]
        rows[model] = result | {
            "writing": written, "review": reviewed | {"per_item": round(reviewed["usd"] / len(items), 5)
                                                      if items else None},
            "usd_per_accepted_place": round((written["usd"] + reviewed["usd"]) / accepted, 4) if accepted else None,
            "samples": trial.samples(placed, result["accepted_places"]), "marks_given": marks,
            "unwritten": unwritten}
        log.info("%s: %s", model, json.dumps({k: v for k, v in rows[model].items()
                                               if k not in ("samples", "marks_given", "unwritten")}, default=str))
    print(trial.report(rows))
    return 0


def spent(conn: Any, model: str, since: Any) -> dict[str, Any]:
    row = conn.execute("""SELECT count(*) AS calls, coalesce(sum(cost_usd), 0) AS usd,
                                 coalesce(sum(input_tokens), 0) AS input FROM psst.harness_calls
                          WHERE model = %s AND created_at >= %s""", (model, since)).fetchone()
    assert row
    return {"calls": row["calls"], "usd": round(float(row["usd"]), 4), "input_tokens": int(row["input"])}


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


def show_report(args: argparse.Namespace) -> int:
    """Cells worked since a time, with places that still stand (with stories, and guide-only) against the previous
    app's count in each cell, what failed, cost per step and per place, review marks, skips by reason, and sample
    stories: the report on an unattended run (decision 36)."""
    with db.open_connection(db.conninfo("system")) as conn:
        print(json.dumps(report(conn, args.since, args.samples), ensure_ascii=False, indent=2, default=str))
    return 0


def report(conn: Any, since: str, samples: int) -> dict[str, Any]:
    window = {"s": since}
    steps = [dict(r) for r in conn.execute("""
        SELECT step, count(*) AS calls, round(sum(cost_usd), 4) AS usd, round(sum(latency_ms) / 1000.0) AS seconds
        FROM psst.harness_calls WHERE created_at >= %(s)s GROUP BY step ORDER BY usd DESC""", window)]
    cells = [dict(r) for r in conn.execute("""
        WITH worked AS (
            SELECT input ->> 'cell' AS cell, count(*) AS passes FROM psst.tasks
            WHERE type = 'research_cell' AND state = 'done' AND done_at >= %(s)s GROUP BY 1),
        placed AS (
            SELECT p.h3_r7 AS cell, i.place_id,
                   count(*) FILTER (WHERE i.type = 'story') AS stories,
                   count(*) FILTER (WHERE i.type = 'story'
                                    AND i.state IN ('checking', 'accepted', 'published')) AS kept,
                   bool_or(i.state IN ('checking', 'accepted', 'published')) AS standing
            FROM psst.items i JOIN psst.places p ON p.id = i.place_id
            WHERE i.created_at >= %(s)s AND i.type IN ('story', 'guide') GROUP BY 1, 2)
        SELECT w.cell, w.passes,
               (SELECT count(*) FROM psst.legacy_places l JOIN psst.research_cells r ON ST_Intersects(l.geom, r.geom)
                WHERE r.cell = w.cell) AS previous_app,
               count(pl.place_id) FILTER (WHERE pl.kept > 0) AS with_stories,
               count(pl.place_id) FILTER (WHERE pl.standing AND pl.stories = 0) AS guide_only,
               count(pl.place_id) FILTER (WHERE pl.standing AND pl.stories > 0 AND pl.kept = 0) AS story_sent_back,
               count(pl.place_id) FILTER (WHERE NOT pl.standing) AS failed,
               (SELECT count(*) FROM psst.leads d WHERE d.cell = w.cell AND d.status IN ('open', 'later')) AS leads_left
        FROM worked w LEFT JOIN placed pl ON pl.cell = w.cell GROUP BY w.cell, w.passes ORDER BY w.cell""", window)]
    marks = [dict(r) for r in conn.execute("""
        SELECT i.type, i.state, i.tier, count(*) AS n FROM psst.items i
        WHERE i.created_at >= %(s)s AND i.type IN ('story', 'guide') GROUP BY 1, 2, 3 ORDER BY 1, 2, 3""", window)]
    skips: dict[str, int] = {}
    for r in conn.execute("""SELECT reason FROM psst.leads
                             WHERE decided_at >= %(s)s AND status IN ('skipped', 'later')""", window):
        skips[skip_kind(r["reason"])] = skips.get(skip_kind(r["reason"]), 0) + 1
    stories = [dict(r) for r in conn.execute("""
        SELECT (SELECT name FROM psst.place_names n WHERE n.place_id = i.place_id AND n.role = 'display') AS place,
               i.state, coalesce(i.tier, v.body ->> 'tier') AS tier, v.body ->> 'headline' AS headline,
               v.body ->> 'short' AS short, v.body ->> 'look' AS look
        FROM psst.items i JOIN psst.revisions v ON v.id = i.current_revision
        WHERE i.created_at >= %(s)s AND i.type = 'story' AND i.state IN ('checking', 'accepted', 'published')
        ORDER BY md5(i.id) LIMIT %(n)s""", window | {"n": samples})]
    spent = sum(float(s["usd"]) for s in steps)
    standing = sum(c["with_stories"] + c["guide_only"] + c["story_sent_back"] for c in cells)
    return {"since": since, "spent_usd": round(spent, 4), "places_standing": standing,
            "usd_per_place": round(spent / standing, 4) if standing else None, "cells": cells, "steps": steps,
            "items": marks, "skips": dict(sorted(skips.items(), key=lambda s: -s[1])), "samples": stories}


def skip_kind(reason: str | None) -> str:
    """A lead's skip reason, sorted into the step that gave it and a short kind."""
    text = (reason or "").casefold()
    if text.startswith("couldn't be written"):
        problem = text.split("allowed: ", 1)[-1]
        kind = ("values" if "values" in problem or "isn't in the facts" in problem else
                "length" if "too long" in problem or "too short" in problem else
                "own words" if "copies" in problem else "other")
        return f"writing: {kind}"
    if text.startswith("the evidence isn't there"):
        return "evidence: " + ("pages unreadable" if "none of its pages" in text else "too little in the sources")
    kinds = [("not one physical thing", ("not one physical", "not a place", "an area", "district", "event",
                                         "organisation", "organization", "route")),
             ("no record or primary source", ("no record", "need its listing", "need a source")),
             ("nothing beyond its record or encyclopedia", ("nothing beyond", "generic", "similar", "no story",
                                                           "no specific", "thin")),
             ("nothing to see", ("nothing visible", "nothing to see", "nothing to point"))]
    for kind, words in kinds:
        if any(w in text for w in words):
            return f"triage: {kind}"
    return "triage: other"


# The order the service works in: what unblocks publishing first, research last (workers.md).
WORK_ORDER = ["audit", "review", "calibrate", "revise", "research_cell"]
IDLE_SECONDS = 60
JUDGING_IDLE_SECONDS = 15  # judging looks for work more often, so marks follow writing closely
CITYLESS = {"calibrate"}


def run_work(args: argparse.Namespace) -> int:
    """Lease and do tasks with whichever harness model each type is routed to, city by city, skipping paused cities,
    until a budget is reached (or, with --once, until nothing is waiting). Judging (review, revise, audit) runs in a
    lane of its own beside research, so a problem shows in the marks while passes go on; either lane stopping stops
    both. After each research pass the city's next cell is queued, and the window's two stops are checked
    (decision 36)."""
    import threading
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    with db.open_connection(db.conninfo("system")) as conn, session(conn, "system", "harness service start") as token:
        ended = conn.execute("SELECT psst.end_earlier_service_runs(%s) AS n", (token,)).fetchone()
        log.info("ended %s runs an earlier start left open", ended["n"] if ended else 0)
    stop = threading.Event()
    judging = threading.Thread(target=work_lane, args=(PARALLEL, JUDGING_IDLE_SECONDS, stop, args.once), daemon=True)
    judging.start()
    work_lane(set(WORK_ORDER) - PARALLEL, IDLE_SECONDS, stop, args.once)
    judging.join()
    return 0


def work_lane(lane: set[str], idle: int, stop: Any, once: bool) -> None:
    """One lane of the service: the task types in `lane`, until `stop` is set or (with `once`) nothing is waiting.
    Setting `stop` when this lane reaches a budget or a stop rule ends the other lane too."""
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import ExitStack

    from psst.harness.coverage import coverage_cells
    from psst.harness.executor import Executor
    from psst.harness.research import parallel_places
    from psst.places import research
    with db.open_connection(db.conninfo("worker")) as conn, db.open_connection(db.conninfo("system")) as system, \
            ExitStack() as runs:
        tokens: dict[str, str] = {}
        planner = runs.enter_context(session(system, "system", "research planning for the harness service"))
        while not stop.is_set():
            busy = False
            limits = conn.execute("""SELECT psst.setting('harness.work_types') AS types,
                                            psst.setting('harness.max_usd_per_place') AS per_place,
                                            psst.setting('harness.max_failed_share') AS failed_share""").fetchone()
            assert limits
            order = [t for t in WORK_ORDER if t in lane and (limits["types"] is None or t in limits["types"])]
            routes = conn.execute("""
                SELECT t.name AS type, psst.task_model(t.name, '{}') AS model FROM psst.task_types t
                WHERE t.runner = 'worker' AND t.active AND t.name = ANY(%s)""", (order,)).fetchall()
            cities = conn.execute("""SELECT id, slug FROM psst.cities WHERE NOT slug IN (
                                       SELECT jsonb_array_elements_text(psst.setting('harness.paused_cities')))
                                     ORDER BY research_order""").fetchall()
            conn.commit()
            for route in sorted(routes, key=lambda r: WORK_ORDER.index(r["type"])):
                model = route["model"] or ""
                if ":" not in model or stop.is_set():
                    continue  # routed to a worker session, not the harness
                if model not in tokens:
                    tokens[model] = runs.enter_context(session(conn, "worker", "harness service", model))
                executor = Executor(tokens[model], model)
                # A calibration belongs to no city; everything else is worked city by city.
                for city in [None] if route["type"] in CITYLESS else cities:
                    # Judging steps run several tasks at once, as research writes several places at once; a research
                    # pass is one task, followed by queuing the next cell.
                    most = parallel_places() if route["type"] in PARALLEL else 1
                    full = sorted(coverage_cells()) if route["type"] == "research_cell" else []
                    if full and not conn.execute(
                            "SELECT 1 FROM psst.tasks WHERE type = 'research_cell' AND state = 'queued' "
                            "AND input ->> 'cell' = ANY(%s)", (full,)).fetchone():
                        continue  # while cells are worked to full coverage, no other cell is researched
                    leased = []
                    for _ in range(most):
                        task = conn.execute("SELECT * FROM psst.lease_task(%s, %s, %s)",
                                            (tokens[model], [route["type"]], city and city["id"])).fetchone()
                        conn.commit()
                        if task is None:
                            break
                        leased.append(dict(task))
                    if not leased:
                        continue
                    busy = True
                    with ThreadPoolExecutor(max_workers=len(leased)) as pool:
                        outcomes = list(pool.map(work_one, [executor] * len(leased), leased))
                    stopped = next((reason for _, reason in outcomes if reason), None)
                    if stopped:
                        log.info("stopping: %s", stopped)
                        stop.set()
                        return
                    done = outcomes[0][0]
                    if route["type"] != "research_cell" or city is None or done is None:
                        continue
                    # The city's next cell, often the same dense cell again, is queued for the next pass; while cells
                    # are worked to full coverage, only they are, ahead of everything else, until they are done.
                    full = sorted(coverage_cells())
                    queued = research.queue(system, planner, city["slug"], len(full) or 1, full or None,
                                            COVERAGE_PRIORITY if full else None)
                    log.info("queued: %s", json.dumps(queued))
                    if full and not queued["queued"] and not conn.execute(
                            "SELECT 1 FROM psst.tasks WHERE type = 'research_cell' AND state IN ('queued', 'leased') "
                            "AND input ->> 'cell' = ANY(%s)", (full,)).fetchone():
                        log.info("stopping: the coverage cells are done")
                        stop.set()
                        return
                    stop_reason = window_stop(conn, done.get("outcome"), limits)
                    if stop_reason:
                        log.info("stopping: %s", stop_reason)
                        stop.set()
                        return
            if not busy:
                if once:
                    return
                stop.wait(idle)


COVERAGE_PRIORITY = 1_000_000  # a cell worked to full coverage goes ahead of every other cell
PARALLEL = {"audit", "review", "revise"}  # judging steps, worked harness.parallel_places tasks at a time


def work_one(executor: Any, task: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Do one leased task: its outcome, or the reason the run must stop. A task that fails for any other reason is
    given back with the reason, and the service goes on with the rest."""
    from psst.harness.executor import BudgetReached
    try:
        done = executor.run(task)
        log.info("%s", json.dumps(done, default=str)[:400])
        return done, None
    except BudgetReached as reason:
        executor.give_back({"task": task["id"]}, f"the harness stopped: {reason}")
        return None, str(reason)
    except Exception as error:  # noqa: BLE001  one task's failure, whatever it is, never stops the service
        executor.give_back({"task": task["id"]}, f"the harness failed on it: {error}")
        log.warning("gave back %s: %s", task["id"], str(error)[:300])
        return None, None


def window_stop(conn: Any, outcome: Any, limits: dict[str, Any]) -> str | None:
    """Why an unattended run stops after a research pass (decision 36): more than the allowed share of the pass's
    places failed, or the window's spend per place still standing passed the limit. None to go on."""
    if isinstance(outcome, dict) and limits["failed_share"] is not None and outcome.get("chosen"):
        if outcome["failed"] / outcome["chosen"] > float(limits["failed_share"]):
            return f"{outcome['failed']} of the pass's {outcome['chosen']} places failed"
    row = conn.execute("SELECT psst.harness_window() AS w").fetchone()
    conn.commit()
    window = row["w"] if row else None
    if window and limits["per_place"] is not None:
        # Judged once the window has spent what ten places may cost, so one pass that finds nothing worth writing
        # doesn't end the run.
        spent, places, most = float(window["spent"]), int(window["places"]), float(limits["per_place"])
        if spent >= 10 * most and spent / max(places, 1) > most:
            return (f"{spent:.4f} USD for {places} places still standing, over {limits['per_place']} USD a place")
    return None


def run_negatives(args: argparse.Namespace) -> int:
    """Break each of the editor's good stories in known ways (decision 31) and replace the constructed set."""
    from psst.harness import negatives
    with db.open_connection(db.conninfo("system")) as conn, session(conn, "system", "constructed negatives") as token:
        good = [dict(r) for r in conn.execute("""SELECT id, place, headline, short, long, look FROM psst.golden_stories
                                                 WHERE mark = 'good' AND constructed_from IS NULL ORDER BY id""")]
        rows = negatives.construct(good, args.per_defect)
        count = conn.execute("SELECT psst.replace_constructed_negatives(%s, %s) AS n",
                             (token, Jsonb(rows))).fetchone()
    print(f"{count['n'] if count else 0} constructed negatives from {len(good)} good stories")
    return 0

