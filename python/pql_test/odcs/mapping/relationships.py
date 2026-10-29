# SPDX-License-Identifier: AGPL-3.0-only
"""ODCS v3.1 ``relationships`` (foreign keys) -> ``Relationship.ShouldExist`` (PQL.Assert 0.8)."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import NamedTuple

from pql_test.odcs.ir import SCHEMA_SUITE, Assertion, RuleOutcome, Target
from pql_test.odcs.loader import Contract
from pql_test.odcs.mapping.context import MapContext, is_column, mapped, skipped
from pql_test.odcs.naming import NameResolver

RELATIONSHIP_REASON = "relationship checks are planned (Relationship.ShouldExist with cardinality and direction)"


class ModelRelationship(NamedTuple):
    """Model names of a relationship's ends: from (the foreign key) and to (the key it references)."""

    from_table: str
    from_column: str
    to_table: str
    to_column: str


def relationship_entries(contract: Contract) -> Iterator[tuple[Mapping, Mapping | None, str, int, Mapping]]:
    """Yield ``(obj, prop or None, scope, index, relationship)`` for every top-level relationship."""
    for obj in contract.schema_objects:
        for prop in obj.get("properties") or []:
            scope = f"{obj['name']}.{prop.get('name', '?')}"
            for i, rel in enumerate(prop.get("relationships") or []):
                yield obj, prop, scope, i, rel
        for i, rel in enumerate(obj.get("relationships") or []):
            yield obj, None, obj["name"], i, rel


def _end(contract: Contract, names: NameResolver, ref: object) -> tuple[str, str] | str:
    """Model ``(table, column)`` for a ``table.property`` reference; otherwise why it cannot resolve."""
    if isinstance(ref, list):
        return "composite (multi-column) relationships are not checked yet"
    if not isinstance(ref, str) or "/" in ref or "#" in ref:
        return f"{ref!r} is not a table.property reference (fully qualified id references are not resolved yet)"
    table_name, _, column_name = ref.partition(".")
    obj = next((o for o in contract.schema_objects if o["name"] == table_name), None)
    prop = next((p for p in (obj or {}).get("properties") or [] if p.get("name") == column_name), None)
    if obj is None or prop is None or not is_column(prop):
        return f"{ref!r} names no column property in the contract schema"
    return names.table(obj), names.column(obj, prop)


def resolve(
    contract: Contract, names: NameResolver, obj: Mapping, prop: Mapping | None, rel: Mapping
) -> ModelRelationship | str:
    """The relationship in model names, or the reason it cannot be resolved."""
    if rel.get("type", "foreignKey") != "foreignKey":
        return f"relationship type {rel.get('type')!r} is not a foreign key"
    source = _end(contract, names, f"{obj['name']}.{prop.get('name')}" if prop is not None else rel.get("from"))
    target = _end(contract, names, rel.get("to"))
    for end in (source, target):
        if isinstance(end, str):
            return end
    return ModelRelationship(*source, *target)


def relationship_rules(
    ctx: MapContext, obj: Mapping, prop: Mapping | None, scope: str, top_level: bool = True
) -> list[RuleOutcome]:
    """Every relationship on a schema object (*prop* None) or property."""
    element = obj if prop is None else prop
    return [_rule(ctx, obj, prop, scope, i, rel, top_level) for i, rel in enumerate(element.get("relationships") or [])]


def _rule(ctx: MapContext, obj, prop, scope: str, index: int, rel: Mapping, top_level: bool) -> RuleOutcome:
    rule_id, description = f"{scope}.relationships[{index}]", f"{scope} relationship to {rel.get('to', '?')}"
    if not ctx.supports("rel.exists"):
        return skipped(rule_id, RELATIONSHIP_REASON, description)
    if not top_level:
        return skipped(rule_id, "a nested property has no semantic model column", description)
    found = resolve(ctx.contract, ctx.names, obj, prop, rel)
    if isinstance(found, str):
        return skipped(rule_id, found, description)
    args = {
        "fromTable": found.from_table,
        "fromColumn": found.from_column,
        "toTable": found.to_table,
        "toColumn": found.to_column,
    }
    return mapped(rule_id, Assertion(rule_id, SCHEMA_SUITE, "rel.exists", Target(found.from_table), args, description))
