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


ID_FORM = "schema/<object id>/properties/<property id>"


class BrokenReference(str):
    """Why a well-formed reference resolves to nothing in the contract (a typo, not an unsupported form)."""


def _by(items: object, key: str, value: str) -> Mapping | None:
    return next((i for i in items or [] if isinstance(i, Mapping) and i.get(key) == value), None)


def _by_id(contract: Contract, ref: str) -> tuple[Mapping, Mapping] | str:
    """The elements a fully qualified ``schema/<object id>/properties/<property id>`` reference names.

    ODCS ids are unique only within their containing array, so the property is looked up under its object.
    """
    if "#" in ref:
        return f"{ref!r} references another file, which is not resolved"
    parts = ref.removeprefix("/").split("/")
    if len(parts) != 4 or parts[0] != "schema" or parts[2] != "properties":
        return f"{ref!r} is not a {ID_FORM} reference (other id paths are not resolved)"
    obj = _by(contract.schema_objects, "id", parts[1])
    if obj is None:
        return BrokenReference(f"{ref!r}: no schema object has the id {parts[1]!r}")
    prop = _by(obj.get("properties"), "id", parts[3])
    if prop is None:
        return BrokenReference(f"{ref!r}: schema object {obj['name']!r} has no property with the id {parts[3]!r}")
    return obj, prop


def resolve_reference(contract: Contract, ref: object) -> tuple[Mapping, Mapping] | str:
    """The contract ``(schema object, property)`` a relationship end names, or why it cannot be resolved.

    A :class:`BrokenReference` reason means the reference is well formed but names nothing.
    """
    if isinstance(ref, list):
        return "composite (multi-column) relationships are not checked yet"
    if not isinstance(ref, str):
        return f"{ref!r} is not a reference"
    if "/" in ref or "#" in ref:
        found = _by_id(contract, ref)
        if isinstance(found, str):
            return found
    else:
        table_name, _, column_name = ref.partition(".")
        if "." in column_name:  # ODCS 3.2 allows table.property.nested
            return f"{ref!r} references a nested property, which has no semantic model column"
        obj = _by(contract.schema_objects, "name", table_name)
        prop = _by((obj or {}).get("properties"), "name", column_name)
        if obj is None or prop is None:
            return BrokenReference(f"{ref!r} names no column property in the contract schema")
        found = (obj, prop)
    if not is_column(found[1]):
        return f"{ref!r} names a property that is not a column"
    return found


def _end(contract: Contract, names: NameResolver, ref: object) -> tuple[str, str] | str:
    """Model ``(table, column)`` for a relationship end; otherwise why it cannot resolve."""
    found = ref if isinstance(ref, tuple) else resolve_reference(contract, ref)
    if isinstance(found, str):
        return found
    obj, prop = found
    if not is_column(prop):  # the property-level source end; resolve_reference checks the referenced ends
        return f"{obj['name']}.{prop.get('name')} is not a column property"
    return names.table(obj), names.column(obj, prop)


def resolve(
    contract: Contract, names: NameResolver, obj: Mapping, prop: Mapping | None, rel: Mapping
) -> ModelRelationship | str:
    """The relationship in model names, or the reason it cannot be resolved.

    A :class:`BrokenReference` reason means an end is well formed but names nothing in the contract.
    """
    if rel.get("type", "foreignKey") != "foreignKey":
        return f"relationship type {rel.get('type')!r} is not a foreign key"
    source = _end(contract, names, (obj, prop) if prop is not None else rel.get("from"))
    target = _end(contract, names, rel.get("to"))
    for end in (source, target):
        if isinstance(end, str):
            return end
    return ModelRelationship(*source, *target)


def broken_references(contract: Contract, names: NameResolver) -> list[str]:
    """Every relationship whose reference is well formed but names nothing in the contract (for `lint`)."""
    found = (
        (f"{scope}.relationships[{index}]", resolve(contract, names, obj, prop, rel))
        for obj, prop, scope, index, rel in relationship_entries(contract)
    )
    return [f"{rule_id}: {reason}" for rule_id, reason in found if isinstance(reason, BrokenReference)]


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
