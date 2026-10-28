# SPDX-License-Identifier: MIT
"""Mappers for rules implied by the schema itself: tables, columns, required, keys."""

from __future__ import annotations

import math
from collections.abc import Mapping

from pql_odcs.ir import DATA_QUALITY_SUITE, SCHEMA_SUITE, Assertion, RuleOutcome, Target
from pql_odcs.mapping.context import (
    BLANKS_COUNT_AS_VALUE,
    EMPTY_STRING_IS_BLANK,
    MapContext,
    approximated,
    is_column,
    is_text,
    mapped,
    skipped,
)

NO_COLUMN = "object, array, map, and vector properties have no semantic model column"


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
        if ctx.supports("col.null_count_at_most"):
            assertion = Assertion(
                rule_id, DATA_QUALITY_SUITE, "col.null_count_at_most", target, {"maxCount": 0}, description
            )
            out.append(mapped(rule_id, assertion))
        else:
            assertion = Assertion(
                rule_id, DATA_QUALITY_SUITE, "col.null_rate_at_most", target, {"maxPct": 0}, description
            )
            out.append(
                approximated(rule_id, EMPTY_STRING_IS_BLANK, assertion) if is_text(prop) else mapped(rule_id, assertion)
            )
    if prop.get("primaryKey") is True:
        out.append(_primary_key(ctx, obj, scope, target, composite_key))
    if prop.get("unique") is True:
        rule_id = f"{scope}.unique"
        description = f"{scope} is unique"
        if ctx.supports("col.non_null_distinct"):
            assertion = Assertion(rule_id, DATA_QUALITY_SUITE, "col.non_null_distinct", target, {}, description)
            out.append(mapped(rule_id, assertion))
        else:
            out.append(approximated(rule_id, BLANKS_COUNT_AS_VALUE, _distinct(rule_id, target, description)))
    return out


def _primary_key(ctx: MapContext, obj: Mapping, scope: str, target: Target, composite_key: list[str]) -> RuleOutcome:
    rule_id = f"{scope}.primaryKey"
    if len(composite_key) > 1:
        # Every key property carries the flag; they share one assertion (same description, same args).
        description = f"{obj['name']} primary key ({', '.join(composite_key)}) is distinct"
        if not ctx.supports("tbl.rows_distinct"):
            return skipped(
                rule_id,
                f"composite primary key ({', '.join(composite_key)}); multi-column keys arrive in v0.2",
                f"{scope} is a primary key (distinct)",
            )
        table = Target(target.table)
        assertion = Assertion(
            rule_id, DATA_QUALITY_SUITE, "tbl.rows_distinct", table, {"columns": list(composite_key)}, description
        )
        return mapped(rule_id, assertion)
    description = f"{scope} is a primary key (distinct)"
    if ctx.supports("col.primary_key"):
        return mapped(rule_id, Assertion(rule_id, DATA_QUALITY_SUITE, "col.primary_key", target, {}, description))
    return approximated(rule_id, BLANKS_COUNT_AS_VALUE, _distinct(rule_id, target, description))


def nested_rules(prop: Mapping, scope: str) -> list[RuleOutcome]:
    """Report attribute rules on a non-column property as skipped (never drop them)."""
    return [
        skipped(f"{scope}.{key}", NO_COLUMN, f"{scope} {key}")
        for key in ("required", "primaryKey", "unique")
        if prop.get(key) is True
    ]


# logicalTypeOptions key groups -> where they land (reported as skipped until then).
_TYPE_OPTION_RELEASES = (
    (
        ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"),
        "v0.2 (Col.ShouldBeInRange / MinShouldBeAtLeast / MaxShouldBeAtMost)",
    ),
    (("minLength", "maxLength"), "v0.2 (Col.TextLengthShouldBeInRange)"),
    (("pattern",), "v0.3 (ShouldMatch per gap plan C3 / R7)"),
)
RELATIONSHIP_REASON = "relationship checks arrive in v0.2 (Relationship.ShouldExist with cardinality and direction)"


def scheduled_property_rules(ctx: MapContext, obj: Mapping, prop: Mapping, scope: str) -> list[RuleOutcome]:
    """Column type and logicalTypeOptions rules, which arrive after v0.1 (patterns from PQL.Assert 0.8)."""
    out = []
    if prop.get("logicalType") or prop.get("physicalType"):
        declared = prop.get("physicalType") or prop.get("logicalType")
        out.append(
            skipped(
                f"{scope}.type",
                "column data type checks arrive in v0.2 (Tbl.ColumnDataTypeShouldBe via an ODCS-to-model type table)",
                f"{scope} is {declared}",
            )
        )
    if prop.get("enum"):
        values = [str(e.get("value")) if isinstance(e, Mapping) else str(e) for e in prop["enum"]]
        out.append(
            skipped(
                f"{scope}.enum",
                "enum (allowed values, ODCS 3.2) arrives in v0.2 (Col.ValuesShouldBeInSet)",
                f"{scope} is one of {', '.join(values)}",
            )
        )
    options = prop.get("logicalTypeOptions") or {}
    handled: tuple = ()
    if options.get("pattern") and ctx.supports("col.contains"):
        # Imported here: pattern mapping lives with the library mapper, which imports this module.
        from pql_odcs.mapping.library import pattern_outcome

        target = Target(ctx.names.table(obj), ctx.names.column(obj, prop))
        description = f"{scope} matches pattern {options['pattern']}"
        out.append(pattern_outcome(ctx, f"{scope}.pattern", target, options["pattern"], description))
        handled = ("pattern",)
    checkable = []
    for keys, release in _TYPE_OPTION_RELEASES:
        present = [k for k in keys if k in options and k not in handled]
        if present:
            checkable.append(f"{', '.join(present)} arrive in {release}")
    if checkable:
        remaining = sorted(k for k in options if k not in handled)
        out.append(
            skipped(f"{scope}.logicalTypeOptions", "; ".join(checkable), f"{scope} logicalTypeOptions {remaining}")
        )
    return out


def relationship_rules(element: Mapping, scope: str) -> list[RuleOutcome]:
    """v3.1 relationships on a schema object or property (v0.2)."""
    return [
        skipped(f"{scope}.relationships[{i}]", RELATIONSHIP_REASON, f"{scope} relationship to {rel.get('to', '?')}")
        for i, rel in enumerate(element.get("relationships") or [])
    ]


_DAY_UNITS = {"d": 1.0, "day": 1.0, "days": 1.0, "h": 1 / 24, "hr": 1 / 24, "hour": 1 / 24, "hours": 1 / 24}
LATENCY_APPROXIMATION = (
    "latency is checked as the age, in UTC days, of the newest value in the element column "
    "(Col.MaxDateShouldBeWithinDays); the result depends on when the test runs"
)


def sla_rules(ctx: MapContext, contract_data: Mapping) -> list[RuleOutcome]:
    """Contract-level SLA properties: ``latency`` maps to a freshness check from PQL.Assert 0.8 (gap plan R8)."""
    out = []
    for i, sla in enumerate(contract_data.get("slaProperties") or []):
        rule_id, description = f"slaProperties[{i}]", f"SLA {sla.get('property', '?')}"
        if not ctx.supports("col.max_date_within_days"):
            out.append(
                skipped(rule_id, "SLA and freshness checks are out of scope for v0.1 (gap plan R8)", description)
            )
            continue
        out.append(_latency(ctx, sla, rule_id, description))
    return out


def _latency(ctx: MapContext, sla: Mapping, rule_id: str, description: str) -> RuleOutcome:
    if sla.get("property") != "latency":
        return skipped(
            rule_id, f"SLA property {sla.get('property')!r} has no PQL.Assert check; only latency maps", description
        )
    value, unit = sla.get("value"), str(sla.get("unit", "")).lower()
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return skipped(rule_id, f"latency needs a non-negative number, got {value!r}", description)
    if unit not in _DAY_UNITS:
        return skipped(rule_id, f"latency unit {sla.get('unit')!r} is not days or hours", description)
    element = str(sla.get("element") or "")
    table_name, _, column_name = element.partition(".")
    obj = next((o for o in ctx.contract.schema_objects if o["name"] == table_name), None)
    prop = next((p for p in (obj or {}).get("properties") or [] if p.get("name") == column_name), None)
    if obj is None or prop is None or not is_column(prop):
        return skipped(
            rule_id, f"latency element {element!r} is not a table.column in the contract schema", description
        )
    target = Target(ctx.names.table(obj), ctx.names.column(obj, prop))
    days = round(value * _DAY_UNITS[unit], 6)
    assertion = Assertion(
        rule_id,
        DATA_QUALITY_SUITE,
        "col.max_date_within_days",
        target,
        {"maxAgeDays": days},
        f"{element} is at most {value} {sla.get('unit')} old",
    )
    return approximated(rule_id, LATENCY_APPROXIMATION, assertion)


def _distinct(rule_id: str, target: Target, description: str) -> Assertion:
    return Assertion(rule_id, DATA_QUALITY_SUITE, "col.distinct", target, {}, description)
