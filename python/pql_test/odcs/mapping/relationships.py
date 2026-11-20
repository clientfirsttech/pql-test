# SPDX-License-Identifier: AGPL-3.0-only
"""ODCS v3.1 ``relationships`` (foreign keys) -> ``Relationship.ShouldExist`` (PQL.Assert 0.8).

A relationship's ``customProperties`` can pin the settings on Power BI's Edit relationship dialog
that change results. Each is named after the TMDL property it checks, and becomes the
``ShouldExist`` argument of the same name.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any, NamedTuple

from pql_test.odcs.catalog import Catalog
from pql_test.odcs.ir import SCHEMA_SUITE, Assertion, RuleOutcome, Target
from pql_test.odcs.loader import Contract
from pql_test.odcs.mapping.context import (
    MapContext,
    approximated,
    is_column,
    mapped,
    skipped,
)
from pql_test.odcs.naming import NameResolver
from pql_test.odcs.udf import version_key

RELATIONSHIP_REASON = "relationship checks need --pql-assert 0.8 or later (Relationship.ShouldExist)"

CARDINALITY_KEY = "pbiCardinality"
CROSS_FILTER_KEY = "pbiCrossFilteringBehavior"
IS_ACTIVE_KEY = "pbiIsActive"
SECURITY_FILTER_KEY = "pbiSecurityFilteringBehavior"  # the RLS checkbox, not the cross-filter direction
SETTING_KEYS = (CARDINALITY_KEY, CROSS_FILTER_KEY, IS_ACTIVE_KEY, SECURITY_FILTER_KEY)
# The first PQL.Assert whose ShouldExist checks every setting: 0.9.1 added crossFilteringBehavior
# and isActive, and reports a limited relationship's security filter as None (0.9.0: Unknown).
SETTINGS_PQL_ASSERT = "0.9.1"

_ONE_DIRECTION, _BOTH = {"crossFilteringBehavior": "OneDirection"}, {"crossFilteringBehavior": "BothDirections"}
# Contract value -> ShouldExist arguments (TMDL names). Values compare case-insensitively.
SETTING_VALUES: dict[str, dict[str, dict[str, str]]] = {
    CARDINALITY_KEY: {
        "manyToOne": {"fromCardinality": "Many", "toCardinality": "One"},
        "oneToMany": {"fromCardinality": "One", "toCardinality": "Many"},
        "oneToOne": {"fromCardinality": "One", "toCardinality": "One"},
        "manyToMany": {"fromCardinality": "Many", "toCardinality": "Many"},
    },
    # The dialog's words, then the TMDL names; automatic is set outside Power BI Desktop.
    CROSS_FILTER_KEY: {
        "single": _ONE_DIRECTION,
        "both": _BOTH,
        "oneDirection": _ONE_DIRECTION,
        "bothDirections": _BOTH,
        "automatic": {"crossFilteringBehavior": "Automatic"},
    },
    IS_ACTIVE_KEY: {"true": {"isActive": "TRUE"}, "false": {"isActive": "FALSE"}},
    # TMDL names only: single/both are the cross-filter dropdown's words, and this is a checkbox.
    SECURITY_FILTER_KEY: {
        "oneDirection": {"securityFilteringBehavior": "OneDirection"},
        "bothDirections": {"securityFilteringBehavior": "BothDirections"},
        "none": {"securityFilteringBehavior": "None"},
    },
}


class Setting(NamedTuple):
    """One relationship setting a contract states: its value as written, and the ShouldExist arguments."""

    value: str
    args: dict[str, str]


def _custom_items(element: Mapping) -> Iterator[tuple[Any, Any]]:
    props = element.get("customProperties")
    if isinstance(props, Mapping):
        yield from props.items()
        return
    for item in props or []:
        if isinstance(item, Mapping):
            yield item.get("property"), item.get("value")


def stated_settings(rel: Mapping) -> dict[str, Setting] | str:
    """The settings *rel* pins, by contract property, or why one of them cannot be checked.

    Any ``pbi*`` property that is not a setting, or a value not in its list, is a problem, so a typo
    cannot quietly check less than the contract says.
    """
    found: dict[str, Setting] = {}
    for key, value in _custom_items(rel):
        if not (isinstance(key, str) and key.startswith("pbi")):
            continue
        if key not in SETTING_VALUES:
            return f"{key} is not a relationship property; use {', '.join(SETTING_KEYS)}"
        allowed = SETTING_VALUES[key]
        text = str(value).lower() if isinstance(value, (str, bool)) else None
        match = next((v for v in allowed if v.lower() == text), None)
        if match is None:
            return f"{key} {value!r} is not one of {', '.join(allowed)}"
        found[key] = Setting(str(value).lower() if isinstance(value, bool) else str(value), allowed[match])
    return found


def contract_value(key: str, settings: Mapping[str, str]) -> str:
    """How a contract writes the model *settings* (ShouldExist names) for property *key*: the dialog's
    words where it has them (``single``, ``both``), else the TMDL name."""
    for value, args in SETTING_VALUES[key].items():
        if all(str(settings.get(arg, "")).upper() == expected.upper() for arg, expected in args.items()):
            return value
    return "/".join(str(settings.get(arg)) for arg in next(iter(SETTING_VALUES[key].values())))


def setting_problems(contract: Contract) -> list[str]:
    """Every relationship with a setting that is not a known property or value (for `lint`)."""
    found = (
        (f"{scope}.relationships[{index}]", stated_settings(rel)) for _o, _p, scope, index, rel in relationship_entries(contract)
    )
    return [f"{rule_id}: {reason}" for rule_id, reason in found if isinstance(reason, str)]


def _not_checked(catalog: Catalog, op_args: tuple[str, ...], key: str, setting: Setting) -> str | None:
    """How to name *setting* when the selected catalog's PQL.Assert cannot check it, else None."""
    if any(arg not in op_args for arg in setting.args):
        return key
    older = version_key(catalog.min_version) < version_key(SETTINGS_PQL_ASSERT)
    if older and setting.args.get("securityFilteringBehavior") == "None":
        return f"{key}: none"
    return None


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
    settings = stated_settings(rel)
    if isinstance(settings, str):
        return skipped(rule_id, settings, description)
    found = resolve(ctx.contract, ctx.names, obj, prop, rel)
    if isinstance(found, str):
        return skipped(rule_id, found, description)
    ends = {
        "fromTable": found.from_table,
        "fromColumn": found.from_column,
        "toTable": found.to_table,
        "toColumn": found.to_column,
    }
    op_args = ctx.catalog.op("rel.settings").args if ctx.supports("rel.settings") else ()
    checked: dict[str, str] = {}
    unchecked: list[str] = []
    for key, setting in settings.items():
        why = _not_checked(ctx.catalog, op_args, key, setting)
        if why:
            unchecked.append(why)
        else:
            checked.update(setting.args)
    if checked:
        # ShouldExist skips a setting passed as "", so unstated ones are passed empty.
        args = {**ends, **{arg: checked.get(arg, "") for arg in op_args if arg != "testName" and arg not in ends}}
        assertion = Assertion(rule_id, SCHEMA_SUITE, "rel.settings", Target(found.from_table), args, description)
    else:
        assertion = Assertion(rule_id, SCHEMA_SUITE, "rel.exists", Target(found.from_table), ends, description)
    if unchecked:
        reason = (
            f"not checked: {', '.join(unchecked)}, which need --pql-assert {SETTINGS_PQL_ASSERT} "
            f"(PQL.Assert {SETTINGS_PQL_ASSERT} or later)"
        )
        return approximated(rule_id, reason, assertion)
    return mapped(rule_id, assertion)
