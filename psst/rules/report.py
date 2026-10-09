"""Problems found by a check: refusals block, flags are for the next reader to weigh."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Report:
    refusals: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    def refuse(self, where: str, message: str) -> None:
        self.refusals.append(f"{where}: {message}")

    def flag(self, where: str, message: str) -> None:
        self.flags.append(f"{where}: {message}")

    @property
    def ok(self) -> bool:
        return not self.refusals

    def as_dict(self) -> dict[str, list[str]]:
        return {"refusals": self.refusals, "flags": self.flags}
