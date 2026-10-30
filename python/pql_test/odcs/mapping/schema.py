# SPDX-License-Identifier: AGPL-3.0-only
"""Mappers for rules implied by the schema itself: tables, columns, required, keys."""

from __future__ import annotations

from collections.abc import Mapping

from pql_test.odcs.datatypes import LOGICAL_TYPES, MODEL_TYPES, model_type
from pql_test.odcs.ir import (
    DATA_QUALITY_SUITE,
    SCHEMA_SUITE,
    Assertion,
    RuleOutcome,
    Target,
)
from pql_test.odcs.mapping.context import (
    BLANKS_COUNT_AS_VALUE,
    EMPTY_STRING_IS_BLANK,
    MapContext,
    approximated,
    is_column,
    is_text,
    mapped,
    skipped,
)
from pql_test.odcs.mapping.validity import (
    LENGTH_KEYS,
    RANGE_KEYS,
    enum_rule,
    length_rule,
    option_skips,
    range_rule,
)
from pql_test.odcs.naming import DATA_TYPE_KEY, custom_property

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
                f"composite primary key ({', '.join(composite_key)}); multi-column keys are planned",
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
    out = [
        skipped(f"{scope}.{key}", NO_COLUMN, f"{scope} {key}")
        for key in ("required", "primaryKey", "unique")
        if prop.get(key) is True
    ]
    if custom_property(prop, DATA_TYPE_KEY) is not None:
        out.append(skipped(f"{scope}.type", NO_COLUMN, f"{scope} is {custom_property(prop, DATA_TYPE_KEY)}"))
    return out


# logicalTypeOptions key groups -> where they land (reported as skipped until then).
_TYPE_OPTION_RELEASES = (
    (
        ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"),
        "planned (Col.ShouldBeInRange / MinShouldBeAtLeast / MaxShouldBeAtMost)",
    ),
    (("minLength", "maxLength"), "planned (Col.TextLengthShouldBeInRange)"),
    (("pattern",), "planned for a later release (ShouldMatch per gap plan C3 / R7)"),
)


def type_rule(ctx: MapContext, obj: Mapping, prop: Mapping, scope: str) -> RuleOutcome | None:
    """The column's data type: ``pbiDataType`` when set, else the model types its ``logicalType`` allows."""
    logical, physical = prop.get("logicalType"), prop.get("physicalType")
    pinned = custom_property(prop, DATA_TYPE_KEY)
    if not (logical or physical or pinned is not None):
        return None
    rule_id = f"{scope}.type"
    reason = None
    if pinned is not None:
        pinned_type = model_type(pinned)
        types = (pinned_type,) if pinned_type else ()
        if not types:
            return skipped(
                rule_id,
                f"{DATA_TYPE_KEY} {pinned!r} is not a model data type; use one of {', '.join(MODEL_TYPES)}",
                f"{scope} is {pinned}",
            )
        declared = types[0]
    elif str(logical).lower() in LOGICAL_TYPES:
        types, reason = LOGICAL_TYPES[str(logical).lower()]
        declared = str(logical)
    else:
        what = f"logicalType {logical}" if logical else f"physicalType {physical} (the source system's type)"
        return skipped(
            rule_id,
            f"{what} has no model data type; add a logicalType ({', '.join(LOGICAL_TYPES)}) "
            f"or a {DATA_TYPE_KEY} custom property",
            f"{scope} is {logical or physical}",
        )
    target = Target(ctx.names.table(obj), ctx.names.column(obj, prop))
    description = f"{scope} is {declared} ({' or '.join(types)} in the model)"
    assertion = Assertion(rule_id, SCHEMA_SUITE, "tbl.column_type", target, {"types": list(types)}, description)
    return approximated(rule_id, reason, assertion) if reason else mapped(rule_id, assertion)


def scheduled_property_rules(ctx: MapContext, obj: Mapping, prop: Mapping, scope: str) -> list[RuleOutcome]:
    """The column type rule, plus the enum and logicalTypeOptions rules (values and patterns from PQL.Assert 0.8)."""
    out = []
    typed = type_rule(ctx, obj, prop, scope)
    if typed is not None:
        out.append(typed)
    if prop.get("enum"):
        out.append(enum_rule(ctx, obj, prop, scope))
    options = prop.get("logicalTypeOptions") or {}
    handled: tuple = ()
    if options.get("pattern") and ctx.supports("col.contains"):
        # Imported here: pattern mapping lives with the library mapper, which imports this module.
        from pql_test.odcs.mapping.library import pattern_outcome

        target = Target(ctx.names.table(obj), ctx.names.column(obj, prop))
        description = f"{scope} matches pattern {options['pattern']}"
        out.append(pattern_outcome(ctx, f"{scope}.pattern", target, options["pattern"], description))
        handled = ("pattern",)
    if ctx.supports("col.in_range"):
        for rule in (range_rule(ctx, obj, prop, scope, options), length_rule(ctx, obj, prop, scope, options)):
            if rule is not None:
                out.append(rule)
        handled += (*RANGE_KEYS, *LENGTH_KEYS)
    checkable = []
    for keys, release in _TYPE_OPTION_RELEASES:
        present = [k for k in keys if k in options and k not in handled]
        if present:
            checkable.append(f"{', '.join(present)} checks are {release}")
    checkable.extend(option_skips(options, handled))
    if checkable:
        remaining = sorted(k for k in options if k not in handled)
        out.append(
            skipped(f"{scope}.logicalTypeOptions", "; ".join(checkable), f"{scope} logicalTypeOptions {remaining}")
        )
    return out


def _distinct(rule_id: str, target: Target, description: str) -> Assertion:
    return Assertion(rule_id, DATA_QUALITY_SUITE, "col.distinct", target, {}, description)
