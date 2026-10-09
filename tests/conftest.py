"""The test database: a throwaway PostGIS 14 server (the version the platform runs on), one template database
built from the migrations, and a fresh copy of it for every test. Nothing here can reach a real database: the
server must be on this machine and every database name starts with `psst_test_`.

Set PSST_TEST_SUPERUSER_URL to use a server you started (CI does); otherwise a Docker container is started.
"""

from __future__ import annotations

import functools
import os
import secrets
import subprocess
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from psst.core import db
from psst.publish.channels import Channels

CONTAINER = "psst-platform-test"
IMAGE = "postgis/postgis:14-3.4"
PORT = 55432
ROLES = ("admin", "system", "worker", "publisher", "console", "api")
PASSWORD = "test"


def _superuser_url() -> str:
    url = os.environ.get("PSST_TEST_SUPERUSER_URL")
    if url:
        return url
    running = subprocess.run(["docker", "ps", "-q", "-f", f"name=^{CONTAINER}$"], capture_output=True, text=True)
    if running.returncode != 0:
        pytest.exit("Docker isn't available; start Docker or set PSST_TEST_SUPERUSER_URL.", returncode=2)
    if not running.stdout.strip():
        subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True)
        subprocess.run(["docker", "run", "-d", "--rm", "--name", CONTAINER, "-e", f"POSTGRES_PASSWORD={PASSWORD}",
                        "-p", f"127.0.0.1:{PORT}:5432", IMAGE], check=True, capture_output=True)
    return f"postgresql://postgres:{PASSWORD}@127.0.0.1:{PORT}/postgres"


def _guard(url: str) -> None:
    parts = conninfo_to_dict(url)
    if parts.get("host") not in ("127.0.0.1", "localhost", "::1"):
        pytest.exit(f"Refusing to test against {parts.get('host')}: tests use a local server only.", returncode=2)


def _wait(url: str) -> None:
    deadline = time.monotonic() + 60
    while True:
        try:
            with psycopg.connect(url, connect_timeout=2):
                return
        except psycopg.OperationalError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.5)


def _url(base: str, dbname: str, user: str = "postgres", password: str = PASSWORD) -> str:
    assert dbname.startswith("psst_test_") or dbname == "postgres"
    parts = conninfo_to_dict(base)
    parts.update(dbname=dbname, user=user, password=password if user != "postgres" else parts.get("password"))
    return make_conninfo(**parts)


@dataclass
class Database:
    name: str
    superuser: str

    def url(self, role: str) -> str:
        if role == "superuser":
            return _url(self.superuser, self.name)
        return _url(self.superuser, self.name, f"psst_platform_{role}")

    @contextmanager
    def connect(self, role: str) -> Iterator[psycopg.Connection[dict[str, Any]]]:
        """A connection as one role, committing each statement, so tests see what each role really can do."""
        with db.open_connection(self.url(role), autocommit=True) as conn:
            yield conn

    def start_run(self, kind: str, model: str | None = None, role: str | None = None) -> tuple[str, str]:
        role = role or {"worker": "worker", "system": "system", "editor": "console"}[kind]
        with self.connect(role) as conn:
            row = conn.execute("SELECT * FROM psst.start_run(%s, 'test', %s)", (kind, model)).fetchone()
        assert row
        return row["run_id"], row["token"]


@pytest.fixture(scope="session")
def template() -> Iterator[tuple[str, str]]:
    superuser = _superuser_url()
    _guard(superuser)
    _wait(superuser)
    name = f"psst_test_template_{secrets.token_hex(4)}"
    with psycopg.connect(superuser, autocommit=True) as conn:
        conn.execute(db.ROLES_SQL.read_text())  # type: ignore[arg-type]
        for role in ROLES:
            conn.execute(f"ALTER ROLE psst_platform_{role} LOGIN PASSWORD '{PASSWORD}'")  # type: ignore[arg-type]
        conn.execute(f'CREATE DATABASE "{name}" OWNER psst_platform_admin')  # type: ignore[arg-type]
    with psycopg.connect(_url(superuser, name), autocommit=True) as conn:
        for extension in ("postgis", "pg_trgm", "unaccent", "pgcrypto"):
            conn.execute(f"CREATE EXTENSION IF NOT EXISTS {extension}")  # type: ignore[arg-type]
    db.migrate(_url(superuser, name, "psst_platform_admin"))
    yield superuser, name
    with psycopg.connect(superuser, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')  # type: ignore[arg-type]


@pytest.fixture
def database(template: tuple[str, str]) -> Iterator[Database]:
    superuser, template_name = template
    name = f"psst_test_{secrets.token_hex(6)}"
    with psycopg.connect(superuser, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}" TEMPLATE "{template_name}" OWNER psst_platform_admin')  # type: ignore[arg-type]
    yield Database(name, superuser)
    with psycopg.connect(superuser, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')  # type: ignore[arg-type]


@pytest.fixture
def city(database: Database) -> dict[str, str]:
    from tests.flow import setup_city
    return setup_city(database)


@pytest.fixture
def site(tmp_path: Any) -> Iterator[dict[str, Any]]:
    """The public directory, served over HTTP the way nginx serves it."""
    public = tmp_path / "public"
    (public / "content").mkdir(parents=True)
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(public))
    handler.log_message = lambda *args: None  # type: ignore[attr-defined]
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield {"channels": Channels(str(public / "content")), "url": f"http://127.0.0.1:{server.server_port}",
           "public": public, "work": tmp_path / "work"}
    server.shutdown()
