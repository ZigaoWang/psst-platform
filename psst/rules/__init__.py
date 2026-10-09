"""The rulebook (rules/): loading, its version, and the checks that apply its writing rules."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from psst.core import config

RULES = config.ROOT / "rules"


@dataclass(frozen=True, eq=False)
class Rulebook:
    version: str
    writing: dict[str, Any]
    sources: dict[str, Any]
    places: dict[str, Any]
    types: dict[str, dict[str, Any]]

    def type(self, name: str) -> dict[str, Any]:
        try:
            return self.types[name]
        except KeyError:
            raise KeyError(f"the rulebook has no content type {name!r}") from None


def _files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.yaml"))


def version_of(root: Path = RULES) -> str:
    """The first 12 hex digits of the SHA-256 of every rule file, by path, in name order."""
    digest = hashlib.sha256()
    for path in _files(root):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()[:12]


@cache
def load(root: Path = RULES) -> Rulebook:
    def read(path: Path) -> dict[str, Any]:
        return yaml.safe_load(path.read_text()) or {}

    return Rulebook(
        version=version_of(root),
        writing=read(root / "writing.yaml"),
        sources=read(root / "sources.yaml"),
        places=read(root / "places.yaml"),
        types={p.stem: read(p) for p in sorted((root / "types").glob("*.yaml"))},
    )
