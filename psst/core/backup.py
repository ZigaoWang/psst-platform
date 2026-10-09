"""The text backup: every table as sorted CSV files, split so git stores only what changed each day. Boundaries are
kept only where places and cities use them (the rest reloads from public sources), and boundary parts are rebuilt
on restore."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import psycopg

ROWS_PER_FILE = 50_000
SKIPPED = {"area_parts"}
# Boundaries worth keeping: the ones places and cities use, with their parents.
USED_AREAS = """
    WITH RECURSIVE used AS (
        SELECT unnest(ARRAY[region_id, city_id, district_id, neighborhood_id]) AS id FROM psst.places
        UNION SELECT id FROM psst.cities
        UNION SELECT a.parent_id FROM psst.areas a JOIN used u ON u.id = a.id WHERE a.parent_id IS NOT NULL)
    SELECT id FROM used WHERE id IS NOT NULL"""


def export(conn: psycopg.Connection[Any], directory: Path) -> dict[str, int]:
    tables = [r[0] for r in conn.execute("""
        SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'psst' AND c.relkind = 'r' ORDER BY c.relname""")]
    counts: dict[str, int] = {}
    conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
    for table in tables:
        if table in SKIPPED:
            continue
        key = conn.execute("""
            SELECT string_agg(quote_ident(a.attname), ', ' ORDER BY array_position(i.indkey, a.attnum))
            FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = %s::regclass AND i.indisprimary""", (f"psst.{table}",)).fetchone()
        order = key[0] if key and key[0] else "1"
        where = f" WHERE id IN ({USED_AREAS})" if table == "areas" else ""
        if table == "area_names":
            where = f" WHERE area_id IN ({USED_AREAS})"
        target = directory / table
        target.mkdir(parents=True, exist_ok=True)
        for old in target.glob("*.csv"):
            old.unlink()
        query = f"COPY (SELECT * FROM psst.{table}{where} ORDER BY {order}) TO STDOUT WITH (FORMAT csv, HEADER)"
        part, rows, header = 0, 0, b""
        handle = None
        with conn.cursor().copy(query) as copy:  # type: ignore[arg-type]
            buffer = b""
            for chunk in copy:
                buffer += bytes(chunk)
                *lines, buffer = buffer.split(b"\n")
                for line in lines:
                    if not header:
                        header = line + b"\n"
                        continue
                    if handle is None or rows % ROWS_PER_FILE == 0:
                        if handle:
                            handle.close()
                        part += 1
                        handle = open(target / f"{part:05d}.csv", "wb")
                        handle.write(header)
                    handle.write(line + b"\n")
                    rows += 1
        if handle:
            handle.close()
        counts[table] = rows
    conn.rollback()
    return counts
