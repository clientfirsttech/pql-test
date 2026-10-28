# SPDX-License-Identifier: AGPL-3.0-only
"""Shared state and small helpers for the rule mappers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from pql_test.odcs.catalog import Catalog, load_catalog
from pql_test.odcs.ir import Assertion, RuleOutcome, Status
from pql_test.odcs.loader import Contract
from pql_test.odcs.naming import NameResolver

# Logical types with no single semantic model column (map and vector arrive in ODCS 3.2).
NON_COLUMN_TYPES = ("object", "array", "map", "vector")


@dataclass(frozen=True)
class MapContext:
    contract: Contract
    names: NameResolver
    closed_schema: bool = False
    catalog: Catalog = field(default_factory=load_catalog)

    def supports(self, op: str) -> bool:
        """True when the selected PQL.Assert catalog has *op* (mappers fall back to 0.7 behaviour otherwise)."""
        return self.catalog.has(op)


def is_column(prop: Mapping) -> bool:
    """True when an ODCS property maps to one flat semantic model column."""
    return prop.get("logicalType") not in NON_COLUMN_TYPES and not prop.get("properties") and not prop.get("items")


def mapped(rule_id: str, *assertions: Assertion) -> RuleOutcome:
    return RuleOutcome(rule_id, Status.MAPPED, tuple(assertions), description=assertions[0].description)


def approximated(rule_id: str, reason: str, *assertions: Assertion) -> RuleOutcome:
    """Mapped to a close equivalent whose semantics differ in a documented way."""
    return RuleOutcome(
        rule_id, Status.APPROXIMATED, tuple(assertions), reason=reason, description=assertions[0].description
    )


BLANKS_COUNT_AS_VALUE = (
    "Col.ShouldBeDistinct compares DISTINCTCOUNT (counts BLANK as a value) with COUNTA (ignores blanks): "
    "a blank fails an otherwise distinct column, and one blank plus one duplicate still passes "
    "(PQL.Assert gap plan C4)"
)
EMPTY_STRING_IS_BLANK = "DAX treats empty strings as BLANK, so empty strings also count as nulls"


def is_text(prop: Mapping | None) -> bool:
    return bool(prop) and prop.get("logicalType") == "string"


def skipped(rule_id: str, reason: str, description: str = "") -> RuleOutcome:
    return RuleOutcome(rule_id, Status.SKIPPED, (), reason=reason, description=description)
