"""Reader intake: problem reports and empty-area demand signals, anonymous and write-only.

    POST /api/v1/reports  {"factId": "it_...", "reason": "wrong", "message": "...", "appVersion": "1.1 (7)"}
    POST /api/v1/demand   {"cell": "85194ad3fffffff"}   (an H3 resolution 5 cell of an empty map view)
    GET  /api/v1/health

The same requests the app already sends. It runs behind nginx (which rate limits and caps request sizes) on the
loopback interface, connects as the role that can only file reports and demand, and stores no addresses.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import h3
import psycopg

PORT = 8788
MAX_BODY = 4096
REASONS = {"wrong", "outdated", "location", "offensive", "other"}
ITEM = re.compile(r"^it_[0-9a-hjkmnp-tv-z]{10}$")
DEMAND_RESOLUTION = 5
log = logging.getLogger("psst.intake")


class Intake:
    def __init__(self, connect: Callable[[], psycopg.Connection[Any]]) -> None:
        self.connect = connect
        self.local = threading.local()

    def connection(self) -> psycopg.Connection[Any]:
        conn = getattr(self.local, "conn", None)
        if conn is None or conn.closed:
            conn = self.connect()
            conn.autocommit = True
            self.local.conn = conn
        return conn

    def report(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        item, reason = body.get("factId"), body.get("reason")
        if not isinstance(item, str) or not ITEM.match(item) or reason not in REASONS:
            return 400, {"error": "factId and reason are required"}
        message, version = body.get("message"), body.get("appVersion")
        try:
            self.connection().execute("SELECT psst.submit_report(%s, %s, %s, %s)", (
                item, reason, message if isinstance(message, str) else None,
                version if isinstance(version, str) else None))
        except psycopg.errors.NoDataFound:
            return 422, {"error": "no published story with that id"}
        return 201, {"status": "received"}

    def demand(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        cell = body.get("cell")
        if not isinstance(cell, str) or not h3.is_valid_cell(cell) or h3.get_resolution(cell) != DEMAND_RESOLUTION:
            return 400, {"error": "cell must be an H3 resolution 5 cell"}
        self.connection().execute("SELECT psst.record_demand(%s)", (cell,))
        return 204, {}


def handler(intake: Intake) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "psst-intake"
        sys_version = ""

        def log_message(self, format: str, *args: Any) -> None:  # no addresses in logs
            log.info("%s %s", self.command, self.path)

        def reply(self, status: int, body: dict[str, Any]) -> None:
            payload = json.dumps(body).encode() if status != 204 else b""
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:  # noqa: N802
            if self.path != "/api/v1/health":
                return self.reply(404, {"error": "not found"})
            try:
                intake.connection().execute("SELECT 1")
                return self.reply(200, {"ok": True})
            except psycopg.Error:
                intake.local.conn = None
                return self.reply(503, {"ok": False})

        def do_POST(self) -> None:  # noqa: N802
            routes = {"/api/v1/reports": intake.report, "/api/v1/demand": intake.demand}
            route = routes.get(self.path)
            if route is None:
                return self.reply(404, {"error": "not found"})
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return self.reply(400, {"error": "invalid Content-Length"})
            if not 0 < length <= MAX_BODY:
                return self.reply(413, {"error": "body too large or empty"})
            try:
                body = json.loads(self.rfile.read(length))
            except ValueError:
                return self.reply(400, {"error": "invalid JSON"})
            if not isinstance(body, dict):
                return self.reply(400, {"error": "invalid JSON"})
            try:
                return self.reply(*route(body))
            except psycopg.errors.CheckViolation:
                return self.reply(422, {"error": "rejected"})
            except psycopg.Error:
                log.exception("database error")
                intake.local.conn = None
                return self.reply(503, {"error": "try again later"})

    return Handler


def serve(intake: Intake, host: str = "127.0.0.1", port: int = PORT) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), handler(intake))
