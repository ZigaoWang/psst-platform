"""`psst publish` and `psst rollback`: build, stage, check, and promote, under one lock.

Nothing in the database says "published" until production holds the new version, so a failed publish leaves both
the database and readers exactly as they were.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from . import acceptance
from .build import Build, build
from .channels import Channels

LOCK = 0x70737470  # one publish or rollback at a time, from any machine
Connection = psycopg.Connection[dict[str, Any]]


class PublishError(RuntimeError):
    def __init__(self, message: str, problems: list[str] | None = None) -> None:
        super().__init__(message)
        self.problems = problems or []


@dataclass
class Outcome:
    version: str
    promoted: bool
    counts: dict[str, int]
    changes: dict[str, list[str]]
    held: list[dict[str, Any]] = field(default_factory=list)
    went_live: int = 0


def _lock(conn: Connection) -> None:
    row = conn.execute("SELECT pg_try_advisory_lock(%s) AS ok", (LOCK,)).fetchone()
    if not row or not row["ok"]:
        raise PublishError("Another publish or rollback is running. Wait for it to finish.")


def _next_version_time(conn: Connection) -> datetime:
    """Now, or one second after the latest version recorded, so every version is unique and ordered."""
    now = datetime.now(UTC).replace(microsecond=0)
    row = conn.execute("SELECT max(content_version) AS v FROM psst.publications").fetchone()
    if row and row["v"]:
        latest = datetime.strptime(row["v"], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        now = max(now, latest + timedelta(seconds=1))
    return now


def _changes(conn: Connection, result: Build) -> dict[str, list[str]]:
    """Item by item, what differs from the publication production holds now."""
    live = {r["item_id"]: r["revision_id"] for r in conn.execute("""
        SELECT item_id, revision_id FROM psst.publication_items WHERE publication_id = (
            SELECT id FROM psst.publications WHERE state = 'promoted' ORDER BY settled_at DESC LIMIT 1)""")}
    new = {i["item"]: i["revision"] for i in result.items}
    return {"added": sorted(set(new) - set(live)), "removed": sorted(set(live) - set(new)),
            "updated": sorted(i for i in set(new) & set(live) if new[i] != live[i])}


def publish(conn: Connection, token: str, channels: Channels, base_url: str, out_root: Path,
            only_staging: bool = False, allow_shrink: str | None = None) -> Outcome:
    _lock(conn)
    result: Build | None = None
    try:
        gate = conn.execute("SELECT psst.setting('gate.open') AS open").fetchone()
        if not (gate and gate["open"] is True):
            raise PublishError("The review gate is closed: no current calibration agrees with the editor's marks "
                               "(decision 25).")
        result = build(conn, out_root, _next_version_time(conn))
        changes = _changes(conn, result)
        conn.commit()
        channels.upload_staging(result.directory)
        problems = acceptance.check(base_url, result.version, allow_shrink)
        outcome = Outcome(result.version, False, result.counts, changes, result.held)
        if only_staging and not problems:
            return outcome
        publication = _record(conn, token, result, changes)
        if problems:
            _settle(conn, token, publication, False, problems)
            raise PublishError("Staging failed its checks; production is unchanged.", problems)
        channels.promote(result.version)
        outcome.went_live = _settle(conn, token, publication, True, [f"allowed to shrink: {allow_shrink}"]
                                    if allow_shrink else [])
        outcome.promoted = True
        return outcome
    finally:
        conn.rollback()
        conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK,))
        conn.commit()
        if result is not None:
            shutil.rmtree(result.directory, ignore_errors=True)


def _record(conn: Connection, token: str, result: Build, changes: dict[str, list[str]]) -> str:
    row = conn.execute("SELECT psst.record_publication(%s, %s, %s, %s, %s, %s, %s) AS id",
                       (token, result.version, Jsonb(result.manifest), Jsonb(result.counts), Jsonb(result.items),
                        Jsonb(changes), Jsonb(result.held))).fetchone()
    conn.commit()
    assert row
    return str(row["id"])


def _settle(conn: Connection, token: str, publication: str, promoted: bool, checks: list[str]) -> int:
    row = conn.execute("SELECT psst.settle_publication(%s, %s, %s, %s) AS n",
                       (token, publication, promoted, Jsonb(checks))).fetchone()
    conn.commit()
    return int(row["n"]) if row else 0


def rollback(conn: Connection, token: str, channels: Channels, version: str | None = None) -> tuple[str, str]:
    _lock(conn)
    try:
        before, after = channels.rollback(version)
        conn.execute("SELECT psst.record_rollback(%s, %s, %s)", (token, before, after))
        conn.commit()
        return before, after
    finally:
        conn.rollback()
        conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK,))
        conn.commit()
