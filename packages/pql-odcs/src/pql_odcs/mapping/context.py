# SPDX-License-Identifier: MIT
"""Shared state and small helpers for the rule mappers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from pql_odcs.ir import Assertion, RuleOutcome, Status
from pql_odcs.loader import Contract
from pql_odcs.naming import NameResolver


@dataclass(frozen=True)
class MapContext:
    contract: Contract
    names: NameResolver
    closed_schema: bool = False


def is_column(prop: Mapping) -> bool:
    """True when an ODCS property maps to one flat semantic model column."""
    return prop.get("logicalType") not in ("object", "array") and not prop.get("properties") and not prop.get("items")


def mapped(rule_id: str, *assertions: Assertion) -> RuleOutcome:
    return RuleOutcome(rule_id, Status.MAPPED, tuple(assertions), description=assertions[0].description)


def approximated(rule_id: str, reason: str, *assertions: Assertion) -> RuleOutcome:
    """Mapped to a close equivalent whose semantics differ in a documented way."""
    return RuleOutcome(
        rule_id, Status.APPROXIMATED, tuple(assertions), reason=reason, description=assertions[0].description
    )


BLANKS_COUNT_AS_VALUE = (
    "Col.ShouldBeDistinct compares DISTINCTCOUNT (counts BLANK as a value) with COUNTA (ignores blanks), "
    "so it also fails when the column contains any blank"
)
EMPTY_STRING_IS_BLANK = "DAX treats empty strings as BLANK, so empty strings also count as nulls"


def is_text(prop: Mapping | None) -> bool:
    return bool(prop) and prop.get("logicalType") == "string"


def skipped(rule_id: str, reason: str, description: str = "") -> RuleOutcome:
    return RuleOutcome(rule_id, Status.SKIPPED, (), reason=reason, description=description)
