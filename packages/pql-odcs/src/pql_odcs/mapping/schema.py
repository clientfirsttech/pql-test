# SPDX-License-Identifier: MIT
"""Mappers for rules implied by the schema itself: tables, columns, required, keys."""

from __future__ import annotations

from collections.abc import Mapping

from pql_odcs.ir import DATA_QUALITY_SUITE, SCHEMA_SUITE, Assertion, RuleOutcome, Target
from pql_odcs.mapping.context import MapContext, is_column, mapped, skipped

NO_COLUMN = "object and array properties have no semantic model column"


def object_rules(ctx: MapContext, obj: Mapping) -> list[RuleOutcome]:
    """Table exists, has the contract's columns, and (opt-in) has no others."""
    name = obj["name"]
    table = Target(ctx.names.table(obj))
    out = [
        mapped(f"{name}.exists", Assertion(f"{name}.exists", SCHEMA_SUITE, "tbl.exists", table, {}, f"{name} exists"))
    ]

    columns = [ctx.names.column(obj, p) for p in obj.get("properties") or [] if is_column(p)]
    if not columns:
        return out
    checks = [("columns", "tbl.has_columns", f"{name} has columns {', '.join(columns)}")]
    if ctx.closed_schema:
        checks.append(("closed", "tbl.no_extra_columns", f"{name} has no columns beyond the contract"))
    for suffix, op, description in checks:
        rule_id = f"{name}.{suffix}"
        commas = [c for c in columns if "," in c]
        if commas:
            out.append(
                skipped(
                    rule_id,
                    f"column name(s) {', '.join(commas)} contain a comma; PQL.Assert splits its column list on commas",
                    description,
                )
            )
            continue
        out.append(mapped(rule_id, Assertion(rule_id, SCHEMA_SUITE, op, table, {"columns": columns}, description)))
    return out


def property_rules(
    ctx: MapContext, obj: Mapping, prop: Mapping, scope: str, composite_key: list[str]
) -> list[RuleOutcome]:
    """``required``, ``primaryKey``, and ``unique`` on one top-level property."""
    out: list[RuleOutcome] = []
    target = Target(ctx.names.table(obj), ctx.names.column(obj, prop))
    if prop.get("required") is True:
        description = f"{scope} is required (no nulls)"
        rule_id = f"{scope}.required"
        out.append(
            mapped(
                rule_id,
                Assertion(rule_id, DATA_QUALITY_SUITE, "col.null_rate_at_most", target, {"maxPct": 0}, description),
            )
        )
    if prop.get("primaryKey") is True:
        rule_id = f"{scope}.primaryKey"
        description = f"{scope} is a primary key (distinct)"
        if len(composite_key) > 1:
            out.append(
                skipped(
                    rule_id,
                    f"composite primary key ({', '.join(composite_key)}); multi-column keys arrive in v0.2",
                    description,
                )
            )
        else:
            out.append(mapped(rule_id, _distinct(rule_id, target, description)))
    if prop.get("unique") is True:
        rule_id = f"{scope}.unique"
        description = f"{scope} is unique"
        out.append(mapped(rule_id, _distinct(rule_id, target, description)))
    return out


def nested_rules(prop: Mapping, scope: str) -> list[RuleOutcome]:
    """Report attribute rules on a non-column property as skipped (never drop them)."""
    return [
        skipped(f"{scope}.{key}", NO_COLUMN, f"{scope} {key}")
        for key in ("required", "primaryKey", "unique")
        if prop.get(key) is True
    ]


def _distinct(rule_id: str, target: Target, description: str) -> Assertion:
    return Assertion(rule_id, DATA_QUALITY_SUITE, "col.distinct", target, {}, description)
