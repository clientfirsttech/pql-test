# SPDX-License-Identifier: AGPL-3.0-only
"""Walk a contract, dispatch every rule to a mapper, and return one outcome per rule."""

from __future__ import annotations

import dataclasses
from collections import Counter
from collections.abc import Iterator, Mapping

from pql_test.odcs.catalog import Catalog, load_catalog
from pql_test.odcs.ir import RuleOutcome, Status
from pql_test.odcs.loader import Contract
from pql_test.odcs.mapping.context import MapContext, is_column, skipped
from pql_test.odcs.mapping.library import describe, map_library
from pql_test.odcs.mapping.schema import (
    NO_COLUMN,
    nested_rules,
    object_rules,
    property_rules,
    relationship_rules,
    scheduled_property_rules,
    sla_rules,
)

_TYPE_REASONS = {
    "sql": "type: sql rules are not translated to DAX (an optional, review-marked DAX stub is planned for later)",
    "custom": "type: custom rules run in their own engine (e.g. Soda, Great Expectations); no DAX equivalent",
    "text": "type: text rules are human-readable only; nothing to execute",
}


def _properties(obj: Mapping, scope: str) -> Iterator[tuple[Mapping, str, bool]]:
    """Yield ``(property, scope, top_level)`` for every property, nested ones included."""
    for prop in obj.get("properties") or []:
        yield from _walk_property(prop, f"{scope}.{prop.get('name', '?')}", top_level=True)


def _walk_property(prop: Mapping, scope: str, top_level: bool) -> Iterator[tuple[Mapping, str, bool]]:
    yield prop, scope, top_level
    for child in prop.get("properties") or []:
        yield from _walk_property(child, f"{scope}.{child.get('name', '?')}", top_level=False)
    items = prop.get("items")
    if isinstance(items, Mapping):
        yield from _walk_property(items, f"{scope}.items", top_level=False)
    map_def = prop.get("map")  # ODCS 3.2 map: {key, value}
    if isinstance(map_def, Mapping):
        for part in ("key", "value"):
            if isinstance(map_def.get(part), Mapping):
                yield from _walk_property(map_def[part], f"{scope}.map.{part}", top_level=False)


def _quality_entries(contract: Contract) -> Iterator[tuple[Mapping, Mapping | None, str, int, Mapping, bool]]:
    """Yield ``(obj, prop, scope, index, rule, top_level)`` for every quality rule."""
    for obj in contract.schema_objects:
        for prop, scope, top_level in _properties(obj, obj["name"]):
            for index, rule in enumerate(prop.get("quality") or []):
                yield obj, prop, scope, index, rule, top_level
        for index, rule in enumerate(obj.get("quality") or []):
            yield obj, None, obj["name"], index, rule, True


def _quality_rule_id(scope: str, index: int, rule: Mapping, duplicate_ids: set) -> str:
    """ODCS ``id`` when present and unique in the contract; otherwise a stable path."""
    rule_id = rule.get("id")
    if not rule_id:
        return f"{scope}.quality[{index}]"
    return f"{scope}.{rule_id}" if rule_id in duplicate_ids else str(rule_id)


def _map_quality(ctx: MapContext, obj, prop, scope, rule_id, rule, top_level) -> RuleOutcome:
    kind = rule.get("type", "library")
    if kind in _TYPE_REASONS:
        return skipped(rule_id, _TYPE_REASONS[kind], describe(rule, scope))
    if kind != "library":
        return skipped(rule_id, f"unrecognised quality type {kind!r}", describe(rule, scope))
    if prop is not None and not top_level:
        return skipped(rule_id, NO_COLUMN, describe(rule, scope))
    return map_library(ctx, rule, rule_id, obj, prop, scope)


def _dedupe(outcomes: list[RuleOutcome]) -> list[RuleOutcome]:
    """Point identical DAX calls from different rules at one shared assertion."""
    canonical: dict = {}
    result = []
    for outcome in outcomes:
        if outcome.status is Status.SKIPPED:
            result.append(outcome)
            continue
        shared = tuple(canonical.setdefault(a.dedupe_key(), a) for a in outcome.assertions)
        result.append(dataclasses.replace(outcome, assertions=shared))
    return result


def _unique_ids(outcomes: list[RuleOutcome]) -> list[RuleOutcome]:
    """Suffix ``#2``, ``#3``, ... onto any rule id that is still not unique (e.g. repeated ids in one scope)."""
    counts: Counter = Counter()
    result = []
    for o in outcomes:
        counts[o.rule_id] += 1
        if counts[o.rule_id] == 1:
            result.append(o)
            continue
        new_id = f"{o.rule_id}#{counts[o.rule_id]}"
        renamed = tuple(dataclasses.replace(a, rule_id=new_id) if a.rule_id == o.rule_id else a for a in o.assertions)
        result.append(dataclasses.replace(o, rule_id=new_id, assertions=renamed))
    return result


def map_contract(
    contract: Contract, names, *, closed_schema: bool = False, catalog: Catalog | None = None
) -> list[RuleOutcome]:
    """Map every rule in *contract*; never drops a rule (unmappable ones are SKIPPED).

    *catalog* (default: PQL.Assert 0.7) decides which ops mappers may use.
    """
    ctx = MapContext(contract, names, closed_schema, catalog or load_catalog())
    id_counts = Counter(r.get("id") for *_, r, _ in _quality_entries(contract) if r.get("id"))
    duplicate_ids = {i for i, n in id_counts.items() if n > 1}
    quality_by_scope: dict[str, list[RuleOutcome]] = {}
    for obj, prop, scope, index, rule, top_level in _quality_entries(contract):
        rule_id = _quality_rule_id(scope, index, rule, duplicate_ids)
        outcome = _map_quality(ctx, obj, prop, scope, rule_id, rule, top_level)
        quality_by_scope.setdefault(scope, []).append(outcome)

    outcomes: list[RuleOutcome] = []
    for obj in contract.schema_objects:
        outcomes.extend(object_rules(ctx, obj))
        key_columns = [
            ctx.names.column(obj, p)
            for p in obj.get("properties") or []
            if p.get("primaryKey") is True and is_column(p)
        ]
        for prop, scope, top_level in _properties(obj, obj["name"]):
            if top_level and is_column(prop):
                outcomes.extend(property_rules(ctx, obj, prop, scope, key_columns))
                outcomes.extend(scheduled_property_rules(ctx, obj, prop, scope))
            else:
                outcomes.extend(nested_rules(prop, scope))
            outcomes.extend(relationship_rules(prop, scope))
            outcomes.extend(quality_by_scope.pop(scope, []))
        outcomes.extend(relationship_rules(obj, obj["name"]))
        outcomes.extend(quality_by_scope.pop(obj["name"], []))
    outcomes.extend(sla_rules(ctx, contract.data))
    return _dedupe(_unique_ids(outcomes))
