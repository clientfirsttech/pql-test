# SPDX-License-Identifier: MIT
"""Neutral intermediate representation between ODCS rule mapping and DAX emission."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

SCHEMA_SUITE = "Schema"
DATA_QUALITY_SUITE = "DataQuality"
ERROR = "error"
WARNING = "warning"


class Status(Enum):
    MAPPED = "mapped"  # exact equivalent
    APPROXIMATED = "approximated"  # close, documented difference
    SKIPPED = "skipped"  # no target; reason required


@dataclass(frozen=True)
class Target:
    table: str  # semantic model name
    column: str | None = None


@dataclass(frozen=True)
class Assertion:
    rule_id: str  # contract rule that produced it (names the generated test)
    suite: str  # SCHEMA_SUITE | DATA_QUALITY_SUITE
    op: str  # catalog key, e.g. "col.distinct"
    target: Target
    args: Mapping[str, Any]  # thresholds, column lists
    description: str  # human-readable, uses ODCS logical names
    severity: str = ERROR

    def dedupe_key(self) -> tuple:
        """Identity of the DAX call, independent of which rule asked for it."""
        frozen_args = tuple(sorted((k, tuple(v) if isinstance(v, list) else v) for k, v in self.args.items()))
        return (self.suite, self.op, self.target, frozen_args, self.severity)


@dataclass(frozen=True)
class RuleOutcome:
    rule_id: str
    status: Status
    assertions: tuple[Assertion, ...] = field(default_factory=tuple)
    reason: str | None = None
    description: str = ""

    def __post_init__(self) -> None:
        if self.status is not Status.MAPPED and not self.reason:
            raise ValueError(f"Rule {self.rule_id}: a {self.status.value} outcome needs a reason.")
