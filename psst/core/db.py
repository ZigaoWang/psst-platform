"""Database access.

Each command connects as the least privileged role that can do its job (design.md, section 14). On the server
the database is reached directly; elsewhere through an SSH tunnel the CLI opens and closes itself, so the
database never listens on the internet.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row

from . import config, tunnel

Role = Literal["admin", "system", "worker", "publisher", "console", "api"]
MIGRATIONS = config.ROOT / "db" / "migrations"
ROLES_SQL = config.ROOT / "db" / "roles.sql"


def conninfo(role: Role) -> str:
    """Connection settings for one role, from `PSST_DATABASE_URL_<ROLE>` or the host, tunnel, and password."""
    url = config.get(f"PSST_DATABASE_URL_{role.upper()}")
    if url:
        return url
    password = config.require(f"PSST_DB_PASSWORD_{role.upper()}")
    name = config.get("PSST_DB_NAME", "psst_platform")
    host = config.get("PSST_DB_HOST")
    if host:
        port = int(config.get("PSST_DB_PORT", "5432") or 5432)
    else:
        host, port = "127.0.0.1", tunnel.local_port(5432)
    return psycopg.conninfo.make_conninfo(host=host, port=port, dbname=name, user=f"psst_platform_{role}",
                                          password=password, application_name=f"psst-{role}")


def open_connection(info: str, autocommit: bool = False) -> psycopg.Connection[dict[str, Any]]:
    conn = psycopg.connect(info, row_factory=dict_row, autocommit=autocommit)
    conn.execute("SET search_path = psst, public")
    if not autocommit:
        conn.commit()
    return conn


@contextmanager
def connect(role: Role) -> Iterator[psycopg.Connection[dict[str, Any]]]:
    """A connection whose work is one transaction: committed on success, rolled back on any error."""
    with open_connection(conninfo(role)) as conn:
        with conn.transaction():
            yield conn


def migrations() -> list[Path]:
    return sorted(MIGRATIONS.glob("*.sql"))


def migrate(info: str) -> list[str]:
    """Apply every migration not yet applied, in order, each in its own transaction. Connects as the schema
    owner. Returns the versions applied."""
    applied: list[str] = []
    with psycopg.connect(info, autocommit=True) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS public.psst_platform_migrations "
                     "(version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
        done = {row[0] for row in conn.execute("SELECT version FROM public.psst_platform_migrations")}
        for path in migrations():
            if path.stem in done:
                continue
            with conn.transaction():
                conn.execute(path.read_text())  # type: ignore[arg-type]  # migration files are trusted SQL
                conn.execute("INSERT INTO public.psst_platform_migrations (version) VALUES (%s)", (path.stem,))
            applied.append(path.stem)
    return applied


def pending(info: str) -> list[str]:
    with psycopg.connect(info) as conn:
        exists = conn.execute("SELECT to_regclass('public.psst_platform_migrations') IS NOT NULL").fetchone()
        done = set()
        if exists and exists[0]:
            done = {row[0] for row in conn.execute("SELECT version FROM public.psst_platform_migrations")}
    return [p.stem for p in migrations() if p.stem not in done]
