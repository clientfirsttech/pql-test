# SPDX-License-Identifier: AGPL-3.0-only
"""Extract the closed ODCS vocabularies the contract mapper dispatches on, from the bundled schemas.

Loads a packaged classification (``catalog/odcs_rules.yaml``) of every value in those
vocabularies, so a new ODCS release that adds one (a metric, a quality type, a
``logicalTypeOptions`` key, ...) can be told apart from one already handled.
``python/tests/odcs/test_odcs_rule_matrix.py`` is what actually enforces the match; this
module only does the extraction and the loading, so both the test and (if ever needed)
``pql-test contract doctor`` can use it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from importlib.resources import files

import yaml

from pql_test.odcs.loader import SCHEMAS

# $defs keys the vocabularies live under, when a bundled schema version defines them. Older
# versions can lack one entirely (v3.0.2 has no RelationshipBase: relationships are v3.1+) or
# define it without an enum (v3.0.2's DataQualityLibrary has a free-text `rule`, not `metric`):
# extraction treats either case as "this version contributes nothing here", not an error.
_DATA_QUALITY_LIBRARY = "DataQualityLibrary"
_DATA_QUALITY = "DataQuality"
_SCHEMA_BASE_PROPERTY = "SchemaBaseProperty"
_RELATIONSHIP_BASE = "RelationshipBase"
# logicalType values with no semantic model column (pql_test.odcs.mapping.context.NON_COLUMN_TYPES):
# their own logicalTypeOptions keys (object's minProperties, vector's dimensions, ...) are
# never reached, so extraction does not collect them.
_NON_COLUMN_TYPES = frozenset({"object", "array", "map", "vector"})


@dataclass(frozen=True)
class Classification:
    use: str  # mapped | dax-only | out-of-scope
    reason: str | None = None


@dataclass(frozen=True)
class OdcsRules:
    """One packaged classification, keyed the same way :func:`extract_vocabularies` is."""

    quality_metrics: dict[str, Classification]
    quality_types: dict[str, Classification]
    logical_types: dict[str, Classification]
    relationship_types: dict[str, Classification]
    logical_type_options: dict[str, dict[str, Classification]]
    descriptive_fields: dict[str, Classification]


@cache
def load_odcs_rules() -> OdcsRules:
    """The packaged classification in ``catalog/odcs_rules.yaml``."""
    text = files("pql_test.odcs.catalog").joinpath("odcs_rules.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(text)

    def flat(key: str) -> dict[str, Classification]:
        return {name: Classification(**spec) for name, spec in data[key].items()}

    def nested(key: str) -> dict[str, dict[str, Classification]]:
        return {outer: {name: Classification(**spec) for name, spec in inner.items()} for outer, inner in data[key].items()}

    return OdcsRules(
        quality_metrics=flat("quality_metrics"),
        quality_types=flat("quality_types"),
        logical_types=flat("logical_types"),
        relationship_types=flat("relationship_types"),
        logical_type_options=nested("logical_type_options"),
        descriptive_fields=flat("descriptive_fields"),
    )


def _load_schema(version_key: str) -> dict:
    text = files("pql_test.odcs").joinpath("schemas").joinpath(SCHEMAS[version_key]).read_text(encoding="utf-8")
    return json.loads(text)


def _logical_type_consts(if_clause: dict) -> list[str]:
    """``logicalType`` const value(s) an ``allOf[i].if`` clause matches: direct, or wrapped in ``anyOf``."""
    branches = if_clause.get("anyOf") or [if_clause]
    consts = []
    for branch in branches:
        const = (branch.get("properties") or {}).get("logicalType", {}).get("const")
        if const:
            consts.append(const)
    return consts


def _enum(defs: dict, def_name: str, property_name: str) -> set[str]:
    """``$defs[def_name].properties[property_name].enum``, or an empty set if any step is absent."""
    prop = (defs.get(def_name, {}).get("properties") or {}).get(property_name, {})
    return set(prop.get("enum") or [])


def extract_vocabularies(schema: dict) -> dict:
    """The closed vocabularies one bundled ODCS schema dict defines.

    Same shape as :class:`OdcsRules`, but with raw value names (no classification) — a
    set for each flat vocabulary, and ``{logicalType: set(option keys)}`` for the nested one.
    A vocabulary this schema version does not define (or defines without an enum) is an
    empty set, not an error: see the ``_DATA_QUALITY_LIBRARY`` comment above.
    """
    defs = schema["$defs"]
    base = defs.get(_SCHEMA_BASE_PROPERTY, {})
    logical_types = set((base.get("properties") or {}).get("logicalType", {}).get("enum") or [])
    options: dict[str, set[str]] = {}
    for clause in base.get("allOf", []):
        if "if" not in clause:
            continue
        then_options = (clause["then"].get("properties") or {}).get("logicalTypeOptions", {}).get("properties") or {}
        if not then_options:
            continue
        for logical_type in _logical_type_consts(clause["if"]):
            if logical_type not in _NON_COLUMN_TYPES:
                options.setdefault(logical_type, set()).update(then_options)
    return {
        "quality_metrics": _enum(defs, _DATA_QUALITY_LIBRARY, "metric"),
        "quality_types": _enum(defs, _DATA_QUALITY, "type"),
        "logical_types": logical_types,
        "relationship_types": _enum(defs, _RELATIONSHIP_BASE, "type"),
        "logical_type_options": options,
    }


def union_vocabularies() -> dict:
    """:func:`extract_vocabularies` for every bundled schema version, unioned together."""
    merged: dict = {
        "quality_metrics": set(),
        "quality_types": set(),
        "logical_types": set(),
        "relationship_types": set(),
        "logical_type_options": {},
    }
    for version_key in SCHEMAS:
        found = extract_vocabularies(_load_schema(version_key))
        for key in ("quality_metrics", "quality_types", "logical_types", "relationship_types"):
            merged[key] |= found[key]
        for logical_type, keys in found["logical_type_options"].items():
            merged["logical_type_options"].setdefault(logical_type, set()).update(keys)
    return merged
