# SPDX-License-Identifier: AGPL-3.0-only
"""Mappers for value rules on one column: numeric bounds, text length, and allowed-value lists.

They need the PQL.Assert 0.8 catalog; callers keep the 0.7 skip when ``ctx.supports`` says no.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from pql_test.odcs.ir import DATA_QUALITY_SUITE, ERROR, Assertion, RuleOutcome, Target
from pql_test.odcs.mapping.context import MapContext, approximated, mapped, skipped

RANGE_KEYS = ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum")
LENGTH_KEYS = ("minLength", "maxLength")
# The maxLength used when a contract gives only minLength: longer than any text a model column holds.
MAX_TEXT_LENGTH = 2147483647
_SYMBOLS = {"minimum": ">=", "maximum": "<=", "exclusiveMinimum": ">", "exclusiveMaximum": "<"}
CASE_INSENSITIVE = (
    "DAX compares text without regard to case, so a value that differs from a listed value only in case also matches"
)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _logical(prop: Mapping) -> str:
    return str(prop.get("logicalType") or "").lower()


def _column(ctx: MapContext, obj: Mapping, prop: Mapping) -> Target:
    return Target(ctx.names.table(obj), ctx.names.column(obj, prop))


def range_rule(ctx: MapContext, obj: Mapping, prop: Mapping, scope: str, options: Mapping) -> RuleOutcome | None:
    """``logicalTypeOptions`` numeric bounds -> one or two PQL.Assert range checks, or a skip."""
    present = [k for k in RANGE_KEYS if k in options]
    if not present:
        return None
    rule_id = f"{scope}.range"
    description = f"{scope} is " + " and ".join(f"{_SYMBOLS[k]} {options[k]}" for k in present)
    logical = _logical(prop)
    if logical not in ("integer", "number"):
        return skipped(
            rule_id,
            f"{', '.join(present)} on a {logical or 'untyped'} property: only integer and number bounds map "
            "(date and time bounds are planned)",
            description,
        )
    if not all(_is_number(options[k]) for k in present):
        return skipped(rule_id, "numeric bounds need numbers", description)
    for inclusive, exclusive in (("minimum", "exclusiveMinimum"), ("maximum", "exclusiveMaximum")):
        if inclusive in options and exclusive in options:
            return skipped(rule_id, f"set {inclusive} or {exclusive}, not both", description)

    lower = options.get("minimum")
    positive = False
    if "exclusiveMinimum" in options:
        bound = options["exclusiveMinimum"]
        if bound == 0:
            positive = True
        elif logical == "integer":
            lower = math.floor(bound) + 1  # whole numbers > n are >= floor(n) + 1
        else:
            return skipped(rule_id, "a number's exclusiveMinimum other than 0 has no PQL.Assert check", description)
    upper = options.get("maximum")
    if "exclusiveMaximum" in options:
        if logical != "integer":
            return skipped(rule_id, "a number's exclusiveMaximum has no PQL.Assert check", description)
        upper = math.ceil(options["exclusiveMaximum"]) - 1
    if lower is not None and upper is not None and lower > upper:
        return skipped(rule_id, f"the bounds allow no value ({lower} > {upper})", description)

    target = _column(ctx, obj, prop)

    def check(op: str, **args: Any) -> Assertion:
        return Assertion(rule_id, DATA_QUALITY_SUITE, op, target, args, description)

    assertions = []
    if positive:
        assertions.append(check("col.positive"))
    if lower is not None and upper is not None:
        assertions.append(check("col.in_range", min=lower, max=upper))
    elif lower is not None:
        assertions.append(check("col.min_at_least", min=lower))
    elif upper is not None:
        assertions.append(check("col.max_at_most", max=upper))
    return mapped(rule_id, *assertions)


def length_rule(ctx: MapContext, obj: Mapping, prop: Mapping, scope: str, options: Mapping) -> RuleOutcome | None:
    """``minLength`` / ``maxLength`` -> ``Col.TextLengthShouldBeInRange``."""
    present = [k for k in LENGTH_KEYS if k in options]
    if not present:
        return None
    rule_id = f"{scope}.length"
    min_len, max_len = options.get("minLength", 0), options.get("maxLength", MAX_TEXT_LENGTH)
    description = f"{scope} length is " + " and ".join(
        f"{'>=' if k == 'minLength' else '<='} {options[k]}" for k in present
    )
    if _logical(prop) != "string":
        return skipped(rule_id, "text length checks need a string property", description)
    whole = [v for v in (min_len, max_len) if _is_number(v) and float(v).is_integer() and v >= 0]
    if len(whole) != 2 or min_len > max_len:
        return skipped(rule_id, "minLength and maxLength need whole numbers, minLength <= maxLength", description)
    args = {"minLen": int(min_len), "maxLen": int(max_len)}
    return mapped(
        rule_id,
        Assertion(rule_id, DATA_QUALITY_SUITE, "col.text_length_in_range", _column(ctx, obj, prop), args, description),
    )


def value_list(prop: Mapping, values: Sequence[Any]) -> tuple[list, str | None]:
    """``(values as the column compares them, problem)``: the problem says why the list cannot be checked."""
    logical = _logical(prop)
    if logical == "string":
        return [v if isinstance(v, str) else str(v) for v in values], None
    if logical in ("integer", "number"):
        ok = all(_is_number(v) for v in values)
        return list(values), None if ok else f"a {logical} column's value list needs numbers"
    if logical == "boolean":
        ok = all(isinstance(v, bool) for v in values)
        return list(values), None if ok else "a boolean column's value list needs true or false"
    if logical in ("date", "timestamp", "time"):
        return (
            [],
            "value lists on date and time columns are not checked (the model compares them as locale-formatted text)",
        )
    return [], f"value lists need a string, integer, number, or boolean logicalType, got {logical or 'none'}"


def case_matters(prop: Mapping, values: Sequence[Any]) -> bool:
    """True when DAX's case-insensitive text comparison could match a value the contract does not list."""
    return _logical(prop) == "string" and any(str(v).lower() != str(v).upper() for v in values)


def allowed_values(
    ctx: MapContext,
    rule_id: str,
    obj: Mapping,
    prop: Mapping,
    values: Sequence[Any],
    description: str,
    severity: str = ERROR,
) -> RuleOutcome:
    """Every non-null value is in *values* -> ``Col.ValuesShouldBeInSet`` (NULL rows are skipped, as ODCS intends)."""
    listed = [v for v in values if v is not None]
    if not listed:
        return skipped(rule_id, "the allowed-value list has no value besides null", description)
    listed, problem = value_list(prop, listed)
    if problem:
        return skipped(rule_id, problem, description)
    assertion = Assertion(
        rule_id,
        DATA_QUALITY_SUITE,
        "col.values_in_set",
        _column(ctx, obj, prop),
        {"values": listed},
        description,
        severity,
    )
    return (
        approximated(rule_id, CASE_INSENSITIVE, assertion) if case_matters(prop, listed) else mapped(rule_id, assertion)
    )


def enum_rule(ctx: MapContext, obj: Mapping, prop: Mapping, scope: str) -> RuleOutcome:
    """ODCS 3.2 ``enum`` (allowed values)."""
    values = [e.get("value") if isinstance(e, Mapping) else e for e in prop["enum"]]
    rule_id, description = f"{scope}.enum", f"{scope} is one of {', '.join(str(v) for v in values)}"
    if not ctx.supports("col.values_in_set"):
        return skipped(rule_id, "enum (allowed values, ODCS 3.2) is planned (Col.ValuesShouldBeInSet)", description)
    return allowed_values(ctx, rule_id, obj, prop, values, description)


def option_skips(options: Mapping, handled: Sequence[str]) -> list[str]:
    """Reasons for the ``logicalTypeOptions`` keys no mapper checks (format, multipleOf, ...)."""
    known = (*RANGE_KEYS, *LENGTH_KEYS, "pattern")
    return [f"{k} has no PQL.Assert check" for k in sorted(options) if k not in known and k not in handled]
