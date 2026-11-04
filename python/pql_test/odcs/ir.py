# SPDX-License-Identifier: AGPL-3.0-only
"""Neutral intermediate representation between ODCS rule mapping and DAX emission."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

SCHEMA_SUITE = "Schema"
DATA_QUALITY_SUITE = "DataQuality"
# Refresh checks read INFO.* model metadata; their own suite keeps a permission error
# from failing every other rule (a suite runs as one query). Not "Refresh": the DAX query
# parser rejects that word as a segment of a function name.
REFRESH_SUITE = "RefreshAge"
# Rules whose DAX the contract wrote (`engine: pql-test`): their own suite, so a mistake in that
# DAX (an unknown measure, say) cannot error the rules pql-test translated.
CONTRACT_DAX_SUITE = "ContractDax"
ERROR = "error"
WARNING = "warning"
# A contract rule's direct call of a PQL.Assert function: args["function"] and args["arguments"]
# (DAX source), with no catalog entry.
DIRECT_CALL = "dax.call"
# RuleOutcome.source for rules whose DAX comes from the contract (`engine: pql-test`).
CONTRACT_DAX = "contract-dax"


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
    source: str | None = None  # CONTRACT_DAX when the contract wrote the DAX

    def __post_init__(self) -> None:
        if self.status is not Status.MAPPED and not self.reason:
            raise ValueError(f"Rule {self.rule_id}: a {self.status.value} outcome needs a reason.")
