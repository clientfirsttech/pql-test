# SPDX-License-Identifier: MIT
"""Mapper for ODCS library quality rules (rowCount, nullValues, duplicateValues, ...)."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from pql_odcs.ir import DATA_QUALITY_SUITE, ERROR, WARNING, Assertion, RuleOutcome, Target
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
from pql_odcs.mapping.patterns import MATCH_CASE, simple_pattern
from pql_odcs.mapping.schema import NO_COLUMN

OPERATORS = (
    "mustBe",
    "mustNotBe",
    "mustBeGreaterThan",
    "mustBeGreaterOrEqualTo",
    "mustBeLessThan",
    "mustBeLessOrEqualTo",
    "mustBeBetween",
    "mustNotBeBetween",
)
# ODCS 3.0.x `rule:` names -> 3.1 `metric:` names.
LEGACY_METRICS = {"nullCheck": "nullValues", "duplicateCount": "duplicateValues", "validValues": "invalidValues"}
# rowCount comparators that map onto a generic comparison over COUNTROWS.
_ROW_COMPARISONS = {
    "mustNotBe": "tbl.rows_ne",
    "mustBeGreaterOrEqualTo": "tbl.rows_ge",
    "mustBeLessThan": "tbl.rows_lt",
    "mustBeLessOrEqualTo": "tbl.rows_le",
}


def metric_of(rule: Mapping) -> str | None:
    metric = rule.get("metric") or rule.get("rule")
    return LEGACY_METRICS.get(metric, metric)


def comparator_of(rule: Mapping) -> tuple[str, Any] | None:
    present = [op for op in OPERATORS if op in rule]
    return (present[0], rule[present[0]]) if len(present) == 1 else None


def severity_of(rule: Mapping) -> str:
    return WARNING if str(rule.get("severity", "")).lower() in ("warning", "info") else ERROR


def describe(rule: Mapping, scope: str) -> str:
    """The rule's own description or name, else a generated one; always one line."""
    text = rule.get("description") or rule.get("name")
    if not text:
        cmp = comparator_of(rule)
        text = " ".join(str(p) for p in (scope, metric_of(rule) or rule.get("type", "rule"), *(cmp or ())))
    return " ".join(str(text).split())


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_zero_ceiling(cmp: tuple[str, Any]) -> bool:
    op, value = cmp
    return op in ("mustBe", "mustBeLessOrEqualTo") and _is_number(value) and value == 0


def _whole_ceiling(cmp: tuple[str, Any]) -> int | None:
    """The largest whole count a ``mustBeLessOrEqualTo`` / ``mustBeLessThan`` comparator allows, else None."""
    op, value = cmp
    if op not in ("mustBeLessOrEqualTo", "mustBeLessThan") or not _is_number(value):
        return None
    ceiling = math.floor(value) if op == "mustBeLessOrEqualTo" else math.ceil(value) - 1
    return ceiling if ceiling >= 0 else None


def pattern_outcome(
    ctx: MapContext, rule_id: str, target: Target, pattern: Any, description: str, severity: str = ERROR
) -> RuleOutcome:
    """Map a column pattern to a PQL.Assert 0.8 prefix/suffix/contains check, or skip with the reason."""
    found = simple_pattern(pattern)
    if isinstance(found, str):
        return skipped(rule_id, f"pattern {pattern!r}: {found}", description)
    op, text = found
    if not ctx.supports(op):
        return skipped(rule_id, "pattern checks need a PQL.Assert catalog with column pattern functions", description)
    args = {"text": text, "matchCase": MATCH_CASE}
    return mapped(rule_id, Assertion(rule_id, DATA_QUALITY_SUITE, op, target, args, description, severity))


def map_library(
    ctx: MapContext, rule: Mapping, rule_id: str, obj: Mapping, prop: Mapping | None, scope: str
) -> RuleOutcome:
    """Map one ``type: library`` rule on a schema object (``prop`` None) or property."""
    description = describe(rule, scope)
    metric = metric_of(rule)
    cmp = comparator_of(rule)
    if cmp is None:
        return skipped(rule_id, f"expected exactly one comparator ({', '.join(OPERATORS)})", description)
    args = (ctx, rule_id, obj, prop, cmp, description, severity_of(rule))
    if metric == "rowCount":
        return _row_count(*args)
    if metric == "nullValues":
        return _null_values(rule, *args)
    if metric == "duplicateValues":
        return _duplicate_values(rule, *args)
    if metric == "missingValues":
        return skipped(
            rule_id,
            "missingValues arrives in v0.2 (Col.NullOrBlankRateShouldBeAtMost, Col.ValuesShouldNotBeInSet, fallback R5)",
            description,
        )
    if metric == "invalidValues":
        pattern = (rule.get("arguments") or {}).get("pattern")
        if pattern and not ctx.supports("col.contains"):
            return skipped(
                rule_id, "invalidValues with a pattern arrives in v0.3 (ShouldMatch per gap plan C3 / R7)", description
            )
        if pattern:
            return _invalid_pattern(ctx, rule_id, obj, prop, cmp, description, severity_of(rule), pattern)
        return skipped(rule_id, "invalidValues arrives in v0.2 (Col.ValuesShouldBeInSet, fallback R5)", description)
    return skipped(rule_id, f"unrecognised library metric {metric!r}", description)


def _invalid_pattern(ctx, rule_id, obj, prop, cmp, description, severity, pattern) -> RuleOutcome:
    target = _column_target(ctx, rule_id, obj, prop, description, "invalidValues")
    if isinstance(target, RuleOutcome):
        return target
    if not _is_zero_ceiling(cmp):
        return skipped(rule_id, "invalidValues with a pattern maps only with a zero ceiling", description)
    return pattern_outcome(ctx, rule_id, target, pattern, description, severity)


def _row_count(ctx, rule_id, obj, prop, cmp, description, severity) -> RuleOutcome:
    table = Target(ctx.names.table(obj))
    op, value = cmp

    def emit(ir_op: str, **ir_args: Any) -> RuleOutcome:
        return mapped(rule_id, Assertion(rule_id, DATA_QUALITY_SUITE, ir_op, table, ir_args, description, severity))

    if op in ("mustBeBetween", "mustNotBeBetween"):
        if not (isinstance(value, list) and len(value) == 2 and all(_is_number(v) for v in value)):
            return skipped(rule_id, f"{op} needs two numbers", description)
        bounds = {"lower": min(value), "upper": max(value)}
        if op == "mustBeBetween":
            return emit("tbl.rows_between", **bounds)
        if ctx.supports("tbl.rows_not_between"):
            return emit("tbl.rows_not_between", **bounds)
        return skipped(rule_id, "mustNotBeBetween arrives in v0.2 (fallback R2: ShouldBeTrue with an OR)", description)
    if not _is_number(value):
        return skipped(rule_id, f"{op} needs a number, got {value!r}", description)
    whole = float(value).is_integer()
    if op == "mustBeGreaterThan":
        if value == 0:
            return emit("tbl.has_rows")
        return emit("tbl.more_rows_than", threshold=int(value)) if whole else emit("tbl.rows_gt", threshold=value)
    if op == "mustBe":
        if whole and value >= 0:
            return emit("tbl.row_count", count=int(value))
        return skipped(rule_id, f"rowCount mustBe needs a whole, non-negative number, got {value!r}", description)
    return emit(_ROW_COMPARISONS[op], threshold=value)


def _column_target(ctx, rule_id, obj, prop, description, metric) -> Target | RuleOutcome:
    if prop is None:
        return skipped(rule_id, f"{metric} on a schema object needs a property", description)
    if not is_column(prop):
        return skipped(rule_id, NO_COLUMN, description)
    return Target(ctx.names.table(obj), ctx.names.column(obj, prop))


def _null_values(rule, ctx, rule_id, obj, prop, cmp, description, severity) -> RuleOutcome:
    target = _column_target(ctx, rule_id, obj, prop, description, "nullValues")
    if isinstance(target, RuleOutcome):
        return target

    def emit(op: str, **ir_args: Any) -> Assertion:
        return Assertion(rule_id, DATA_QUALITY_SUITE, op, target, ir_args, description, severity)

    if _is_zero_ceiling(cmp):
        if ctx.supports("col.null_count_at_most"):
            return mapped(rule_id, emit("col.null_count_at_most", maxCount=0))
        assertion = emit("col.null_rate_at_most", maxPct=0)
        return approximated(rule_id, EMPTY_STRING_IS_BLANK, assertion) if is_text(prop) else mapped(rule_id, assertion)
    if rule.get("unit") == "percent":
        if not ctx.supports("col.null_pct_at_most"):
            return skipped(rule_id, "nullValues percent thresholds arrive in v0.2 (units per gap plan C2)", description)
        op, value = cmp
        if op == "mustBeLessOrEqualTo" and _is_number(value) and 0 <= value <= 100:
            return mapped(rule_id, emit("col.null_pct_at_most", maxPct=value))
        return skipped(
            rule_id, f"nullValues percent maps only for mustBeLessOrEqualTo 0-100, got {op} {value!r}", description
        )
    if not ctx.supports("col.null_count_at_most"):
        return skipped(rule_id, "nullValues absolute thresholds arrive in v0.2 (fallback R4: COUNTBLANK)", description)
    ceiling = _whole_ceiling(cmp)
    if ceiling is None:
        return skipped(
            rule_id,
            f"nullValues maps only as a ceiling (mustBeLessOrEqualTo / mustBeLessThan), got {cmp[0]} {cmp[1]!r}",
            description,
        )
    return mapped(rule_id, emit("col.null_count_at_most", maxCount=ceiling))


def _duplicate_values(rule, ctx, rule_id, obj, prop, cmp, description, severity) -> RuleOutcome:
    if prop is None:
        return _duplicate_columns(rule, ctx, rule_id, obj, cmp, description, severity)
    target = _column_target(ctx, rule_id, obj, prop, description, "duplicateValues")
    if isinstance(target, RuleOutcome):
        return target
    if _is_zero_ceiling(cmp):
        if ctx.supports("col.non_null_distinct"):
            assertion = Assertion(
                rule_id, DATA_QUALITY_SUITE, "col.non_null_distinct", target, {}, description, severity
            )
            return mapped(rule_id, assertion)
        assertion = Assertion(rule_id, DATA_QUALITY_SUITE, "col.distinct", target, {}, description, severity)
        return approximated(rule_id, BLANKS_COUNT_AS_VALUE, assertion)
    ceiling = _whole_ceiling(cmp)
    if ceiling is not None and ctx.supports("col.duplicates_at_most"):
        assertion = Assertion(
            rule_id, DATA_QUALITY_SUITE, "col.duplicates_at_most", target, {"maxCount": ceiling}, description, severity
        )
        return mapped(rule_id, assertion)
    if ceiling is None and ctx.supports("col.duplicates_at_most"):
        return skipped(rule_id, f"duplicateValues maps only as a ceiling, got {cmp[0]} {cmp[1]!r}", description)
    return skipped(rule_id, "non-zero duplicateValues thresholds arrive in v0.3 (fallback R6)", description)


def _duplicate_columns(rule, ctx, rule_id, obj, cmp, description, severity) -> RuleOutcome:
    """``duplicateValues`` on a schema object, over ``arguments.properties``."""
    names = (rule.get("arguments") or {}).get("properties") or []
    if len(names) < 2:
        return skipped(rule_id, "duplicateValues on a schema object needs arguments.properties", description)
    if not ctx.supports("tbl.rows_distinct"):
        reason = (
            "two-column duplicateValues arrives in v0.2 (Col.ComboShouldBeDistinct)"
            if len(names) == 2
            else "3+ column duplicateValues arrives in v0.2 (fallback R3: SUMMARIZE)"
        )
        return skipped(rule_id, reason, description)
    if not _is_zero_ceiling(cmp):
        return skipped(rule_id, "multi-column duplicateValues maps only with a zero ceiling", description)
    by_name = {p.get("name"): p for p in obj.get("properties") or []}
    unknown = [n for n in names if n not in by_name or not is_column(by_name[n])]
    if unknown:
        return skipped(
            rule_id, f"duplicateValues names no column property: {', '.join(map(str, unknown))}", description
        )
    columns = [ctx.names.column(obj, by_name[n]) for n in names]
    assertion = Assertion(
        rule_id,
        DATA_QUALITY_SUITE,
        "tbl.rows_distinct",
        Target(ctx.names.table(obj)),
        {"columns": columns},
        description,
        severity,
    )
    return mapped(rule_id, assertion)
