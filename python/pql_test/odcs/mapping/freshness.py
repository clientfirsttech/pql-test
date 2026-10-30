# SPDX-License-Identifier: AGPL-3.0-only
"""Contract-level ``slaProperties``: ``latency`` (data age) and ``frequency`` (refresh recency).

The two are different questions, and a model can pass one and fail the other:

- ``latency`` is the delay between the source and the model. It is checked on the newest
  value in a timestamp column, which is the only evidence of how fresh the *data* is.
- ``frequency`` is how often the data is updated. It is checked on the time the model's
  partitions last refreshed. A successful refresh of stale source data passes it.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

from pql_test.odcs.ir import DATA_QUALITY_SUITE, REFRESH_SUITE, Assertion, RuleOutcome, Target
from pql_test.odcs.mapping.context import MapContext, approximated, is_column, skipped

_HOURS_PER_UNIT = {"d": 24, "day": 24, "days": 24, "h": 1, "hr": 1, "hour": 1, "hours": 1}
_DAY_UNITS = ("d", "day", "days")
LATENCY_APPROXIMATION = (
    "latency is checked as the age, in UTC, of the newest value in the element column "
    "(Col.MaxDateShouldBeWithinDays / Hours): it measures the source delay plus the refresh delay, "
    "as the model's users see it, and the result depends on when the test runs"
)
FREQUENCY_APPROXIMATION = (
    "frequency is checked as the hours since the table's partitions last refreshed (INFO.PARTITIONS): "
    "it proves the refresh ran, not that the source sent new data (check that with latency)"
)
LATENCY_NEEDS_COLUMN = "latency needs a timestamp column (table.column); refresh time is not source latency"
_OTHER_REASONS = {
    "timeOfAvailability": "timeOfAvailability is a time of day; a test of it would depend on when it runs, so it is not checked",
    "retention": "retention (how long data is kept) has no PQL.Assert check yet (Partitions.ShouldExist could approximate it)",
}


def sla_rules(ctx: MapContext, contract_data: Mapping) -> list[RuleOutcome]:
    """One outcome per SLA property: latency and frequency map from PQL.Assert 0.8; the rest are skipped."""
    out = []
    for i, sla in enumerate(contract_data.get("slaProperties") or []):
        rule_id, description = f"slaProperties[{i}]", f"SLA {sla.get('property', '?')}"
        if not ctx.supports("col.max_date_within_days"):
            out.append(skipped(rule_id, "SLA and freshness checks need --pql-assert 0.8 (gap plan R8)", description))
            continue
        prop = sla.get("property")
        if prop == "latency":
            out.append(_latency(ctx, sla, rule_id, description))
        elif prop == "frequency":
            out.append(_frequency(ctx, sla, rule_id, description))
        else:
            reason = _OTHER_REASONS.get(
                prop, f"SLA property {prop!r} has no PQL.Assert check; only latency and frequency map"
            )
            out.append(skipped(rule_id, reason, description))
    return out


def _duration(sla: Mapping) -> tuple[float, str] | str:
    """``(value, unit)`` for a non-negative number in days or hours; otherwise the skip reason."""
    value, unit = sla.get("value"), str(sla.get("unit", "")).lower()
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return f"{sla.get('property')} needs a non-negative number, got {value!r}"
    if unit not in _HOURS_PER_UNIT:
        return f"{sla.get('property')} unit {sla.get('unit')!r} is not days or hours"
    return value, unit


def _elements(sla: Mapping) -> list[str]:
    return [e.strip() for e in str(sla.get("element") or "").split(",") if e.strip()]


def _schema_object(ctx: MapContext, name: str) -> Mapping | None:
    return next((o for o in ctx.contract.schema_objects if o["name"] == name), None)


def _latency(ctx: MapContext, sla: Mapping, rule_id: str, description: str) -> RuleOutcome:
    duration = _duration(sla)
    if isinstance(duration, str):
        return skipped(rule_id, duration, description)
    value, unit = duration
    elements = _elements(sla)
    if not elements:
        return skipped(rule_id, LATENCY_NEEDS_COLUMN, description)
    assertions = []
    for element in elements:
        table_name, _, column_name = element.partition(".")
        obj = _schema_object(ctx, table_name)
        if obj is not None and not column_name:
            return skipped(rule_id, LATENCY_NEEDS_COLUMN, description)
        prop = next((p for p in (obj or {}).get("properties") or [] if p.get("name") == column_name), None)
        if obj is None or prop is None or not is_column(prop):
            return skipped(
                rule_id, f"latency element {element!r} is not a table.column in the contract schema", description
            )
        target = Target(ctx.names.table(obj), ctx.names.column(obj, prop))
        if unit in _DAY_UNITS:
            op, args = "col.max_date_within_days", {"maxAgeDays": value}
        else:
            op, args = "col.max_date_within_hours", {"maxAgeHours": value}
        text = f"{element} is at most {sla.get('value')} {sla.get('unit')} old"
        assertions.append(Assertion(rule_id, DATA_QUALITY_SUITE, op, target, args, text))
    return approximated(rule_id, LATENCY_APPROXIMATION, *assertions)


def _frequency(ctx: MapContext, sla: Mapping, rule_id: str, description: str) -> RuleOutcome:
    duration = _duration(sla)
    if isinstance(duration, str):
        return skipped(rule_id, duration, description)
    value, unit = duration
    elements = _elements(sla)
    if not elements:
        return skipped(rule_id, "frequency needs an element naming the table(s) whose refresh to check", description)
    assertions = []
    for element in elements:
        obj = _schema_object(ctx, element.partition(".")[0])
        if obj is None:
            return skipped(rule_id, f"frequency element {element!r} names no table in the contract schema", description)
        text = f"{obj['name']} refreshed within the last {sla.get('value')} {sla.get('unit')}"
        args = {"maxAgeHours": round(value * _HOURS_PER_UNIT[unit], 6)}
        target = Target(ctx.names.table(obj))
        assertions.append(Assertion(rule_id, REFRESH_SUITE, "tbl.refresh_age_at_most", target, args, text))
    return approximated(rule_id, FREQUENCY_APPROXIMATION, *assertions)
