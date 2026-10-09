"""Rechecking after a rulebook change: every current revision whose last tool check ran under another rulebook is
checked again by the tools. Items under check get the new verdict at once; accepted and published items go back to
checking, where the system worker runs the tools as for any revision."""

from __future__ import annotations

from typing import Any

import psycopg

from psst import rules

from . import runner

Connection = psycopg.Connection[dict[str, Any]]


def stale(conn: Connection, version: str) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute("""
        SELECT i.id AS item, i.state, i.current_revision AS revision
        FROM psst.items i
        CROSS JOIN LATERAL (SELECT details ->> 'rulebook' AS rulebook FROM psst.checks
                            WHERE revision_id = i.current_revision AND kind = 'tool' ORDER BY id DESC LIMIT 1) last
        WHERE i.state IN ('checking', 'accepted', 'published') AND last.rulebook IS DISTINCT FROM %s
        ORDER BY i.id""", (version,))]


def recheck(conn: Connection, token: str) -> dict[str, int]:
    version = rules.load().version
    counts = {"rechecked": 0, "sent_back": 0}
    for entry in stale(conn, version):
        if entry["state"] == "checking":
            runner.run(conn, token, entry["revision"])  # recording the verdict settles the revision if it fails
            counts["rechecked"] += 1
        else:
            conn.execute("SELECT psst.recheck_for_rules(%s, %s, %s)", (token, entry["item"], version))
            counts["sent_back"] += 1
        conn.commit()
    return counts
