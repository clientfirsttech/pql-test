# SPDX-License-Identifier: MIT
"""Library-rule mappers (rowCount and the v0.1 skip list) and the rule registry."""

from __future__ import annotations

import pytest
from factories import contract_dict, prop, schema_object

from pql_odcs.ir import ERROR, WARNING, Status, Target
from pql_odcs.loader import load_contract
from pql_odcs.mapping import map_contract
from pql_odcs.naming import NameResolver


def _map_contract(data: dict):
    contract = load_contract(data)
    return map_contract(contract, NameResolver(contract))


def _object_rule(rule: dict, api_version: str = "v3.1.0"):
    """Map a single object-level quality rule on table T and return its outcome."""
    data = contract_dict(api_version, schema=[schema_object("T", quality=[rule])])
    return {o.rule_id: o for o in _map_contract(data)}["T.quality[0]"]


def _call(outcome):
    a = outcome.assertions[0]
    return a.op, a.target, dict(a.args)


class TestRowCount:
    def test_greater_than_zero_means_the_table_has_rows(self):
        given = "rowCount mustBeGreaterThan 0"
        should = "emit tbl.has_rows rather than more_rows_than(0)"

        actual = _call(_object_rule({"metric": "rowCount", "mustBeGreaterThan": 0}))

        assert actual == ("tbl.has_rows", Target("T"), {}), f"{given}: {should}"

    @pytest.mark.parametrize(
        ("rule", "expected"),
        [
            ({"mustBe": 42}, ("tbl.row_count", {"count": 42})),
            ({"mustBeGreaterThan": 100}, ("tbl.more_rows_than", {"threshold": 100})),
            ({"mustBeGreaterThan": 10.5}, ("tbl.rows_gt", {"threshold": 10.5})),
            ({"mustBeGreaterOrEqualTo": 5}, ("tbl.rows_ge", {"threshold": 5})),
            ({"mustBeLessThan": 5}, ("tbl.rows_lt", {"threshold": 5})),
            ({"mustBeLessOrEqualTo": 5}, ("tbl.rows_le", {"threshold": 5})),
            ({"mustNotBe": 0}, ("tbl.rows_ne", {"threshold": 0})),
            ({"mustBeBetween": [10, 20]}, ("tbl.rows_between", {"lower": 10, "upper": 20})),
        ],
    )
    def test_each_comparator_maps_to_its_op(self, rule, expected):
        given = f"rowCount with {rule}"
        should = f"emit {expected[0]}"
        op, _, args = _call(_object_rule({"metric": "rowCount", **rule}))

        assert (op, args) == expected, f"{given}: {should}"

    def test_must_not_be_between_waits_for_fallback_r2(self):
        given = "rowCount mustNotBeBetween"
        should = "be skipped with a reason naming fallback R2 and v0.2"
        outcome = _object_rule({"metric": "rowCount", "mustNotBeBetween": [1, 5]})

        assert (outcome.status, "R2" in outcome.reason, "v0.2" in outcome.reason) == (Status.SKIPPED, True, True), (
            f"{given}: {should}"
        )

    def test_odcs_3_0_rule_keyword_is_understood(self):
        given = "an ODCS v3.0.2 rule written with `rule: rowCount`"
        should = "map exactly like the 3.1 `metric` form"

        actual = _call(_object_rule({"type": "library", "rule": "rowCount", "mustBe": 3}, "v3.0.2"))

        assert actual == ("tbl.row_count", Target("T"), {"count": 3}), f"{given}: {should}"

    def test_fractional_exact_row_count_is_rejected(self):
        given = "rowCount mustBe 2.5"
        should = "be skipped, because a row count is a whole number"

        assert _object_rule({"metric": "rowCount", "mustBe": 2.5}).status is Status.SKIPPED, f"{given}: {should}"


class TestRegistry:
    @pytest.mark.parametrize("kind", ["sql", "custom", "text"])
    def test_non_library_types_are_skipped_with_a_reason(self, kind):
        given = f"a type: {kind} rule"
        should = "be skipped with a reason, never dropped"
        rule = {
            "sql": {"type": "sql", "query": "SELECT COUNT(*) FROM t", "mustBe": 0},
            "custom": {"type": "custom", "engine": "soda", "implementation": "checks: []"},
            "text": {"type": "text", "description": "Data is reviewed monthly"},
        }[kind]

        outcome = _object_rule(rule)

        assert (outcome.status, bool(outcome.reason)) == (Status.SKIPPED, True), f"{given}: {should}"

    @pytest.mark.parametrize(
        ("rule", "release"),
        [
            ({"metric": "missingValues", "mustBe": 0}, "v0.2"),
            ({"metric": "invalidValues", "mustBe": 0, "arguments": {"validValues": ["a"]}}, "v0.2"),
            ({"metric": "invalidValues", "mustBe": 0, "arguments": {"pattern": "^a$"}}, "v0.3"),
            ({"metric": "duplicateValues", "mustBe": 5}, "v0.3"),
        ],
    )
    def test_metrics_scheduled_after_v0_1_name_their_release(self, rule, release):
        given = f"a {rule['metric']} rule that v0.1 cannot map"
        should = f"be skipped with a reason naming {release}"
        data = contract_dict(schema=[schema_object("T", [prop("c", quality=[rule])])])

        outcome = {o.rule_id: o for o in _map_contract(data)}["T.c.quality[0]"]

        assert (outcome.status, release in outcome.reason) == (Status.SKIPPED, True), f"{given}: {should}"

    def test_unrecognised_metric_is_reported_not_dropped(self):
        given = "an ODCS 3.0 library rule whose free-text `rule` names no known metric"
        should = "be skipped, naming the unrecognised metric"
        outcome = _object_rule({"type": "library", "rule": "freshness", "mustBeLessThan": 3}, "v3.0.2")

        assert (outcome.status, "freshness" in outcome.reason) == (Status.SKIPPED, True), f"{given}: {should}"

    def test_every_rule_gets_exactly_one_outcome(self):
        given = "a contract mixing schema attributes and quality rules"
        should = "produce exactly one outcome per rule, with unique rule ids"
        data = contract_dict(
            schema=[
                schema_object(
                    "T",
                    [
                        prop("id", primaryKey=True, required=True),
                        prop("n", quality=[{"metric": "nullValues", "mustBe": 0}]),
                    ],
                    quality=[
                        {"metric": "rowCount", "mustBeGreaterThan": 0},
                        {"type": "sql", "query": "SELECT 1", "mustBe": 1},
                    ],
                )
            ]
        )

        ids = [o.rule_id for o in _map_contract(data)]

        assert ids == [
            "T.exists",
            "T.columns",
            "T.id.required",
            "T.id.primaryKey",
            "T.n.quality[0]",
            "T.quality[0]",
            "T.quality[1]",
        ], f"{given}: {should}"

    def test_warning_severity_flows_into_the_assertion(self):
        given = "a quality rule with severity warning"
        should = "carry warning severity into its IR assertion"
        outcome = _object_rule({"metric": "rowCount", "mustBeGreaterThan": 0, "severity": "warning"})

        assert outcome.assertions[0].severity == WARNING, f"{given}: {should}"

    def test_default_severity_is_error(self):
        given = "a quality rule without severity"
        should = "default to error"

        assert _object_rule({"metric": "rowCount", "mustBe": 1}).assertions[0].severity == ERROR, f"{given}: {should}"

    def test_odcs_id_names_the_rule_and_duplicates_are_qualified(self):
        given = "quality ids that are unique in one place and repeated across two objects"
        should = "use a unique id as-is and qualify repeated ids with their scope"
        data = contract_dict(
            schema=[
                schema_object(
                    "A",
                    quality=[
                        {"id": "rows", "metric": "rowCount", "mustBe": 1},
                        {"id": "solo", "metric": "rowCount", "mustBe": 2},
                    ],
                ),
                schema_object("B", quality=[{"id": "rows", "metric": "rowCount", "mustBe": 1}]),
            ]
        )

        ids = [o.rule_id for o in _map_contract(data) if not o.rule_id.endswith(".exists")]

        assert ids == ["A.rows", "solo", "B.rows"], f"{given}: {should}"
