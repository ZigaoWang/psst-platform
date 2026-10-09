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
from psst.places import research, resolve

log = logging.getLogger("psst.system")
Connection = psycopg.Connection[dict[str, Any]]
AUDIT_PLAN_SECONDS = 600


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

    def plan_audits(self, force: bool = False) -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT psst.plan_audits(%s, %s) AS n", (self.token, force)).fetchone()
            conn.commit()
        self._audits_planned = time.monotonic()
        return int(row["n"]) if row else 0

    def work(self, once: bool = False, idle_seconds: float = 5.0) -> None:
        while True:
            busy = self.step()
            if time.monotonic() - self._audits_planned > AUDIT_PLAN_SECONDS:
                self.plan_audits()
            if once and not busy:
                return
            if not busy:
                time.sleep(idle_seconds)
