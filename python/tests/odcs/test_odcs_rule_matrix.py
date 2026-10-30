# SPDX-License-Identifier: AGPL-3.0-only
"""Every ODCS vocabulary value the contract mapper dispatches on is classified, and demonstrated.

Mirrors ``test_function_matrix.py`` for the other side of the mapping: here the vendored
artifact is the bundled ODCS JSON schemas, not a PQL.Assert library. A schema gaining a new
quality metric, quality type, logicalType, relationship type, or logicalTypeOptions key fails
these tests until ``catalog/odcs_rules.yaml`` classifies it, and (for anything classified
``mapped`` or ``dax-only``) until some fixture under ``tests/odcs/fixtures/`` exercises it.
"""

from __future__ import annotations

from pathlib import Path

from pql_test.odcs.loader import load_contract
from pql_test.odcs.odcs_rules import extract_vocabularies, load_odcs_rules, union_vocabularies

FIXTURES = Path(__file__).resolve().parent / "fixtures"
# "library" is the default quality type (the key is simply absent), so no fixture can show
# it as a literal value the way the other three quality types are shown.
_NO_FIXTURE_NEEDED = {("quality_types", "library")}


def _flat_mismatch(found: set, classified: dict) -> tuple[set, set]:
    """``(unclassified, stale)``: values found but not classified, and classified but not found."""
    return found - classified.keys(), classified.keys() - found


def test_quality_metrics_are_classified():
    given = "the metric enum in every bundled ODCS schema"
    should = "match catalog/odcs_rules.yaml's quality_metrics exactly"

    unclassified, stale = _flat_mismatch(union_vocabularies()["quality_metrics"], load_odcs_rules().quality_metrics)

    assert (unclassified, stale) == (set(), set()), f"{given}: {should}"


def test_quality_types_are_classified():
    given = "the quality type enum in every bundled ODCS schema"
    should = "match catalog/odcs_rules.yaml's quality_types exactly"

    unclassified, stale = _flat_mismatch(union_vocabularies()["quality_types"], load_odcs_rules().quality_types)

    assert (unclassified, stale) == (set(), set()), f"{given}: {should}"


def test_logical_types_are_classified():
    given = "the logicalType enum in every bundled ODCS schema"
    should = "match catalog/odcs_rules.yaml's logical_types exactly"

    unclassified, stale = _flat_mismatch(union_vocabularies()["logical_types"], load_odcs_rules().logical_types)

    assert (unclassified, stale) == (set(), set()), f"{given}: {should}"


def test_relationship_types_are_classified():
    given = "the relationship type enum (ODCS v3.1+)"
    should = "match catalog/odcs_rules.yaml's relationship_types exactly"

    unclassified, stale = _flat_mismatch(
        union_vocabularies()["relationship_types"], load_odcs_rules().relationship_types
    )

    assert (unclassified, stale) == (set(), set()), f"{given}: {should}"


def test_logical_type_options_are_classified():
    given = "every logicalTypeOptions key, per logicalType with a model column"
    should = "match catalog/odcs_rules.yaml's logical_type_options exactly, type by type"
    found, classified = union_vocabularies()["logical_type_options"], load_odcs_rules().logical_type_options

    problems = []
    for logical_type in found.keys() | classified.keys():
        unclassified, stale = _flat_mismatch(found.get(logical_type, set()), classified.get(logical_type, {}))
        if unclassified or stale:
            problems.append(f"{logical_type}: unclassified {sorted(unclassified)}, stale {sorted(stale)}")

    assert problems == [], f"{given}: {should}\n" + "\n".join(problems)


def test_only_non_rule_fields_are_out_of_scope():
    given = "every value classified out-of-scope"
    should = "have a reason, so a value is never silently dropped from the matrix"
    rules = load_odcs_rules()
    flat = [
        *rules.quality_metrics.values(),
        *rules.quality_types.values(),
        *rules.logical_types.values(),
        *rules.relationship_types.values(),
        *rules.descriptive_fields.values(),
        *(c for options in rules.logical_type_options.values() for c in options.values()),
    ]

    missing_reason = [c for c in flat if c.use == "out-of-scope" and not c.reason]

    assert missing_reason == [], f"{given}: {should}"


def _fixture_touchpoints() -> dict:
    """Every classified value a fixture under FIXTURES actually uses."""
    touched = {
        "quality_metrics": set(),
        "quality_types": set(),
        "logical_types": set(),
        "relationship_types": set(),
        "logical_type_options": {},
    }

    def walk_property(prop: dict) -> None:
        if logical_type := prop.get("logicalType"):
            touched["logical_types"].add(logical_type)
            for key in prop.get("logicalTypeOptions") or {}:
                touched["logical_type_options"].setdefault(logical_type, set()).add(key)
        for rel in prop.get("relationships") or []:
            touched["relationship_types"].add(rel.get("type", "foreignKey"))
        for rule in prop.get("quality") or []:
            walk_quality(rule)
        for child in prop.get("properties") or []:
            walk_property(child)
        items = prop.get("items")
        if isinstance(items, dict):
            walk_property(items)
        map_def = prop.get("map") or {}
        for part in ("key", "value"):
            if isinstance(map_def.get(part), dict):
                walk_property(map_def[part])

    def walk_quality(rule: dict) -> None:
        touched["quality_types"].add(rule.get("type", "library"))
        if metric := rule.get("metric") or rule.get("rule"):
            touched["quality_metrics"].add(metric)

    for path in sorted(FIXTURES.glob("*.odcs.yaml")):
        contract = load_contract(path)
        for obj in contract.schema_objects:
            for rel in obj.get("relationships") or []:
                touched["relationship_types"].add(rel.get("type", "foreignKey"))
            for rule in obj.get("quality") or []:
                walk_quality(rule)
            for prop in obj.get("properties") or []:
                walk_property(prop)
    return touched


def test_every_mapped_value_is_demonstrated_in_a_fixture():
    given = "every value classified mapped or dax-only in catalog/odcs_rules.yaml"
    should = "appear in at least one fixture under tests/odcs/fixtures/, so it is proven to parse and dispatch"
    rules = load_odcs_rules()
    touched = _fixture_touchpoints()

    missing = []
    for category in ("quality_metrics", "quality_types", "logical_types", "relationship_types"):
        classified = getattr(rules, category)
        for name, c in classified.items():
            if (
                c.use in ("mapped", "dax-only")
                and name not in touched[category]
                and (category, name) not in _NO_FIXTURE_NEEDED
            ):
                missing.append(f"{category}.{name}")
    for logical_type, options in rules.logical_type_options.items():
        for name, c in options.items():
            if c.use in ("mapped", "dax-only") and name not in touched["logical_type_options"].get(logical_type, set()):
                missing.append(f"logical_type_options.{logical_type}.{name}")

    assert missing == [], f"{given}: {should}\nNot demonstrated: {', '.join(missing)}"


def test_extraction_matches_a_known_schema_shape():
    given = "extract_vocabularies on the bundled v3.2.0 schema"
    should = "find the specific values this file's docstring and odcs_rules.yaml assume exist"
    import json

    from importlib.resources import files

    schema = json.loads(
        files("pql_test.odcs").joinpath("schemas").joinpath("odcs-json-schema-v3.2.0.json").read_text("utf-8")
    )

    found = extract_vocabularies(schema)

    assert (
        "nullValues" in found["quality_metrics"],
        "custom" in found["quality_types"],
        "pattern" in found["logical_type_options"].get("string", set()),
        "exclusiveMinimum" in found["logical_type_options"].get("number", set()),
        "object" not in found["logical_type_options"],  # no model column: object's own keys are never reached
    ) == (True, True, True, True, True), f"{given}: {should}"
