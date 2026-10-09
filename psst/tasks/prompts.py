"""Prompts, one per task type, in `prompts/`. A prompt's version is the hash of its text; every result records
the version that produced it."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from psst.core import config

PROMPTS = config.ROOT / "prompts"


@dataclass(frozen=True)
class Prompt:
    task_type: str
    text: str

    @property
    def version(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()[:12]


def load(task_type: str) -> Prompt:
    shared = (PROMPTS / "_shared.md").read_text()
    path = PROMPTS / f"{task_type}.md"
    if not path.exists():
        raise FileNotFoundError(f"no prompt for task type {task_type} ({path})")
    return Prompt(task_type, path.read_text().rstrip() + "\n\n" + shared.rstrip() + "\n")
