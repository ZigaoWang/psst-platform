"""The system worker: runs the deterministic tasks (tool checks, place lookups) and plans audits.

It runs on the server as a service under one system run, leasing system tasks the same way workers lease theirs.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from psst.checks import runner
from psst.photos import importing
from psst.places import cells, research, resolve
from psst.tasks import prompts
from psst.tasks.files import golden_bar

log = logging.getLogger("psst.system")
Connection = psycopg.Connection[dict[str, Any]]
AUDIT_PLAN_SECONDS = 600
GATE_SECONDS = 300
REVIEW_PLAN_SECONDS = 600
HEXAGON_SECONDS = 600  # long enough for a reviser's batch of revisions to gather


class SystemWorker:
    def __init__(self, connect: Callable[[], Connection], token: str) -> None:
        self.connect = connect
        self.token = token
        self.handlers: dict[str, Callable[[Connection, dict[str, Any]], dict[str, Any]]] = {
            "tool_check": self.tool_check,
            "resolve_places": self.resolve_places,
            "import_photo": self.import_photo,
            "queue_research": self.queue_research,
            "relink_place": self.relink_place,
        }
        self._audits_planned = 0.0
        self._gate_refreshed = 0.0
        self._reviews_planned = 0.0
        self._hexagons_filled = 0.0

    def tool_check(self, conn: Connection, task: dict[str, Any]) -> dict[str, Any]:
        result = runner.run(conn, self.token, task["revision_id"], task["id"])
        return {"pass": result.ok, "refusals": len(result.report.refusals)}

    def resolve_places(self, conn: Connection, task: dict[str, Any]) -> dict[str, Any]:
        return resolve.resolve(conn, self.token, list(task["input"].get("places") or []), task["city_id"])

    def import_photo(self, conn: Connection, task: dict[str, Any]) -> dict[str, Any]:
        return importing.import_photo(conn, self.token, task)

    def queue_research(self, conn: Connection, task: dict[str, Any]) -> dict[str, Any]:
        return research.queue(conn, self.token, task["input"]["city"], int(task["input"]["cells"]))

    def relink_place(self, conn: Connection, task: dict[str, Any]) -> dict[str, Any]:
        return resolve.relink(conn, self.token, task)

    def step(self) -> bool:
        """Do one task, if one is waiting. Returns whether there was one."""
        with self.connect() as conn:
            task = conn.execute("SELECT * FROM psst.lease_task(%s, %s)", (self.token, list(self.handlers))).fetchone()
            conn.commit()
            if task is None:
                return False
            try:
                result = self.handlers[task["type"]](conn, task)
                # A tool check settles a revision (submit_task advances it); other system tasks just close.
                finish = "submit_task" if task["type"] == "tool_check" else "finish_system_task"
                conn.execute(f"SELECT psst.{finish}(%s, %s, %s)", (self.token, task["id"], Jsonb(result)))
                conn.commit()
                log.info("%s %s done", task["type"], task["id"])
            except Exception as error:  # one bad task must not stop the worker
                conn.rollback()
                conn.execute("SELECT psst.return_task(%s, %s, %s)", (self.token, task["id"], str(error)[:500]))
                conn.commit()
                log.exception("%s %s failed", task["type"], task["id"])
        return True

    def refresh_gate(self) -> dict[str, Any]:
        """Open or close the review gate for the current review prompt and golden bar, queueing any calibration it
        lacks (decision 25)."""
        with self.connect() as conn:
            bar = golden_bar(conn)
            row = conn.execute("SELECT psst.refresh_gate(%s, %s, %s) AS s",
                               (self.token, prompts.load("review").version, bar["version"] if bar else None)).fetchone()
            conn.commit()
        self._gate_refreshed = time.monotonic()
        return dict(row["s"]) if row else {}

    def fill_hexagons(self) -> int:
        """Give each place its density hexagon, and outline every hexagon of the dense research cells, so the density
        map shows the gaps as well as what is there (decision 27)."""
        with self.connect() as conn:
            missing = conn.execute("""SELECT p.id, p.city_id, ST_Y(p.geom) AS lat, ST_X(p.geom) AS lon
                                      FROM psst.places p JOIN psst.cities c ON c.id = p.city_id
                                      WHERE p.state = 'active' AND p.h3_r9 IS NULL AND p.geom IS NOT NULL
                                      LIMIT 2000""").fetchall()  # only the platform's own cities are measured
            places = [{"place": r["id"], "cell": cells.cell_for(r["lat"], r["lon"], cells.DENSITY),
                       "city": r["city_id"]} for r in missing]
            dense = conn.execute("""
                SELECT rc.cell, rc.city_id FROM psst.research_cells rc
                WHERE (SELECT count(*) FROM psst.leads l WHERE l.cell = rc.cell)
                      >= psst.setting('research.dense_leads')::text::integer
                  AND NOT EXISTS (SELECT 1 FROM psst.hexagons h WHERE h.parent = rc.cell) LIMIT 20""").fetchall()
            hexagons = {p["cell"]: cells.density_hexagon(p["cell"], p["city"]) for p in places}
            for row in dense:
                hexagons.update({c: cells.density_hexagon(c, row["city_id"]) for c in cells.children(row["cell"])})
            conn.execute("SELECT psst.record_hexagons(%s, %s, %s)",
                         (self.token, Jsonb([{k: p[k] for k in ("place", "cell")} for p in places]),
                          Jsonb(list(hexagons.values()))))
            conn.commit()
        self._hexagons_filled = time.monotonic()
        return len(places) + len(hexagons)

    def plan_reviews(self) -> int:
        """Batch the items waiting for a review that no research cell's review covers (revisions, rechecks)."""
        with self.connect() as conn:
            row = conn.execute("SELECT psst.plan_reviews(%s) AS n", (self.token,)).fetchone()
            conn.commit()
        self._reviews_planned = time.monotonic()
        return int(row["n"]) if row else 0

    def plan_audits(self, force: bool = False) -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT psst.plan_audits(%s, %s) AS n", (self.token, force)).fetchone()
            conn.commit()
        self._audits_planned = time.monotonic()
        return int(row["n"]) if row else 0

    def work(self, once: bool = False, idle_seconds: float = 5.0) -> None:
        """Works until stopped. Whoever started the run ends it, which gives back the task in hand at once instead of
        leaving it leased until the lease runs out."""
        chores = [("_audits_planned", AUDIT_PLAN_SECONDS, self.plan_audits),
                  ("_reviews_planned", REVIEW_PLAN_SECONDS, self.plan_reviews),
                  ("_hexagons_filled", HEXAGON_SECONDS, self.fill_hexagons),
                  ("_gate_refreshed", GATE_SECONDS, self.refresh_gate)]
        while True:
            busy = self.step()
            for stamp, every, chore in chores:
                if time.monotonic() - getattr(self, stamp) > every:
                    try:
                        chore()
                    except (psycopg.Error, ValueError, LookupError, OSError):
                        # A periodic chore that fails is logged and tried again later; it never stops the checks.
                        log.exception("%s failed; trying again later", chore.__name__)
                        setattr(self, stamp, time.monotonic())
            if once and not busy:
                return
            if not busy:
                time.sleep(idle_seconds)
