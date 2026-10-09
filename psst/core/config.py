"""Settings from the environment file and the process environment.

The file is `~/.config/psst-platform/env` (or the path in `PSST_CONFIG`), with one `KEY=value` per line. Values in
the process environment win. See `.env.example` for every key.
"""

from __future__ import annotations

import os
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def config_path() -> Path:
    return Path(os.environ.get("PSST_CONFIG", Path.home() / ".config" / "psst-platform" / "env"))


@cache
def _file_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    return values


def get(key: str, default: str | None = None) -> str | None:
    if key in os.environ:
        return os.environ[key]
    return _file_values(config_path()).get(key, default)


def require(key: str) -> str:
    value = get(key)
    if not value:
        raise ConfigError(f"{key} is not set in {config_path()} or the environment. See .env.example.")
    return value


class ConfigError(RuntimeError):
    pass
