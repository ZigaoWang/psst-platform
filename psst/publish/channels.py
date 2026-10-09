"""Where the output lives: a root with `staging/v2` and `production/v2`, each holding `manifest.json`, `packs/`,
and (production) `history/`. Packs are named by their hash and never change, so promotion and rollback only
replace `manifest.json`, which is atomic.

The root is a directory on this machine (on the server, or in tests) or on the server through SSH.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path
from typing import Any

FORMAT = "v2"
KEEP_VERSIONS = 20


class ChannelError(RuntimeError):
    pass


class Channels:
    def __init__(self, root: str, host: str | None = None) -> None:
        self.root = root.rstrip("/")
        self.host = host  # None: the root is on this machine

    def path(self, channel: str) -> str:
        return f"{self.root}/{channel}/{FORMAT}"

    def _sh(self, command: str) -> str:
        argv = ["sh", "-c", command] if self.host is None else ["ssh", self.host, command]
        done = subprocess.run(argv, capture_output=True, text=True)
        if done.returncode != 0:
            raise ChannelError(done.stderr.strip() or f"command failed: {command[:80]}")
        return done.stdout

    def _target(self, path: str) -> str:
        return path if self.host is None else f"{self.host}:{path}"

    def upload_staging(self, directory: Path) -> None:
        staging = self.path("staging")
        self._sh(f"mkdir -p {shlex.quote(staging)}/packs")
        subprocess.run(["rsync", "-a", f"{directory}/packs/", self._target(f"{staging}/packs/")], check=True,
                       capture_output=True)
        subprocess.run(["rsync", "-a", str(directory / "manifest.json"), self._target(f"{staging}/manifest.json.tmp")],
                       check=True, capture_output=True)
        self._sh(f"mv {shlex.quote(staging)}/manifest.json.tmp {shlex.quote(staging)}/manifest.json")

    def manifest(self, channel: str) -> dict[str, Any] | None:
        text = self._sh(f"cat {shlex.quote(self.path(channel))}/manifest.json 2>/dev/null || true")
        return dict(json.loads(text)) if text.strip() else None

    def promote(self, version: str) -> None:
        """Copy staging's packs into production and switch production's manifest, only if staging still holds
        `version`, the one that was checked."""
        staging, production = self.path("staging"), self.path("production")
        manifest = self.manifest("staging")
        if not manifest or manifest["contentVersion"] != version:
            raise ChannelError(f"staging no longer holds {version}; nothing was promoted")
        files = [manifest["common"]["file"]] + [c["file"] for c in manifest["cities"]]
        # Packs never change once written, so one already in production is the same file. (`cp -n` would do,
        # but it reports a skipped file as a failure on some systems.)
        copies = " && ".join(f"{{ [ -e {production}/{shlex.quote(f)} ] || cp {staging}/{shlex.quote(f)} "
                             f"{production}/{shlex.quote(f)}; }}" for f in files)
        self._sh(f"mkdir -p {production}/packs {production}/history && {copies} && "
                 f"cp {staging}/manifest.json {production}/history/{version}.json && "
                 f"cp {staging}/manifest.json {production}/manifest.json.tmp && "
                 f"mv {production}/manifest.json.tmp {production}/manifest.json")

    def history(self) -> list[str]:
        listing = self._sh(f"ls {shlex.quote(self.path('production'))}/history 2>/dev/null || true")
        return sorted(name.removesuffix(".json") for name in listing.split() if name.endswith(".json"))

    def rollback(self, version: str | None = None) -> tuple[str, str]:
        """Point production back at an earlier version (the one before the current, by default)."""
        production = self.path("production")
        current = self.manifest("production")
        if not current:
            raise ChannelError("production has nothing to roll back")
        history = self.history()
        if version is None:
            earlier = [v for v in history if v < current["contentVersion"]]
            if not earlier:
                raise ChannelError("there is no earlier version to roll back to")
            version = earlier[-1]
        if version not in history:
            raise ChannelError(f"no production version {version}")
        self._sh(f"cp {production}/history/{version}.json {production}/manifest.json.tmp && "
                 f"mv {production}/manifest.json.tmp {production}/manifest.json")
        return current["contentVersion"], version

    def prune(self) -> int:
        """Delete packs that neither staging nor the last KEEP_VERSIONS production versions use."""
        production = self.path("production")
        keep: set[str] = set()
        manifests = [self.manifest("staging")] + [
            json.loads(self._sh(f"cat {production}/history/{v}.json")) for v in self.history()[-KEEP_VERSIONS:]]
        for manifest in manifests:
            if manifest:
                keep.update([manifest["common"]["file"]] + [c["file"] for c in manifest["cities"]])
        removed = 0
        for channel in ("staging", "production"):
            directory = self.path(channel)
            for name in self._sh(f"ls {directory}/packs 2>/dev/null || true").split():
                if f"packs/{name}" not in keep:
                    self._sh(f"rm {directory}/packs/{shlex.quote(name)}")
                    removed += 1
        return removed
