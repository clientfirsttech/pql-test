# SPDX-License-Identifier: AGPL-3.0-only
"""Value rules mapped with PQL.Assert 0.8: bounds, text length, allowed values, missing and invalid values,
and relationships."""

from __future__ import annotations

import pytest

from pql_test.odcs.api import plan_contract, render
from pql_test.odcs.ir import Status, Target
from tests.odcs.factories import contract_dict, custom, prop, schema_object


def _outcomes(schema: list, version: str = "0.8", **overrides) -> dict:
    plan = plan_contract(contract_dict(schema=schema, **overrides), pql_assert=version)
    return {o.rule_id: o for o in plan.outcomes}


def _table(*props, **extra) -> list:
    return [schema_object("T", list(props), **extra)]


def _calls(outcome) -> list:
    return [(a.op, dict(a.args)) for a in outcome.assertions]


def _option_rule(logical: str, rule_suffix: str, version: str = "0.8", **options):
    return _outcomes(_table(prop("a", logical, logicalTypeOptions=options)), version)[f"T.a.{rule_suffix}"]


def _column_rule(rule: dict, logical: str = "string", version: str = "0.8"):
    return _outcomes(_table(prop("a", logical, quality=[rule])), version)["T.a.quality[0]"]


def _dax(schema: list, **overrides) -> str:
    plan = plan_contract(contract_dict(schema=schema, **overrides), pql_assert="0.8")
    return "".join(f.content for f in render(plan, env="DEV"))


class TestRanges:
    @pytest.mark.parametrize(
        ("logical", "options", "calls"),
        [
            ("number", {"minimum": 0, "maximum": 10}, [("col.in_range", {"min": 0, "max": 10})]),
            ("integer", {"minimum": 5}, [("col.min_at_least", {"min": 5})]),
            ("number", {"maximum": 2.5}, [("col.max_at_most", {"max": 2.5})]),
            ("number", {"exclusiveMinimum": 0}, [("col.positive", {})]),
            (
                "number",
                {"exclusiveMinimum": 0, "maximum": 9},
                [("col.positive", {}), ("col.max_at_most", {"max": 9})],
            ),
            ("integer", {"exclusiveMinimum": 3, "exclusiveMaximum": 10}, [("col.in_range", {"min": 4, "max": 9})]),
            ("integer", {"exclusiveMinimum": 0.5}, [("col.min_at_least", {"min": 1})]),
        ],
    )
    def test_bounds_map_to_range_checks(self, logical, options, calls):
        given = f"a {logical} property with {options}"
        should = f"map to {calls}"

        outcome = _option_rule(logical, "range", **options)

        assert (outcome.status, _calls(outcome)) == (Status.MAPPED, calls), f"{given}: {should}"

    @pytest.mark.parametrize(
        ("logical", "options"),
        [
            ("number", {"exclusiveMinimum": 2}),
            ("number", {"exclusiveMaximum": 2}),
            ("date", {"minimum": "2020-01-01"}),
            ("integer", {"minimum": 1, "exclusiveMinimum": 0}),
            ("integer", {"minimum": 5, "maximum": 1}),
        ],
    )
    def test_bounds_without_an_exact_check_are_skipped(self, logical, options):
        given = f"a {logical} property with {options}"
        should = "be skipped with a reason"

        outcome = _option_rule(logical, "range", **options)

        assert (outcome.status, bool(outcome.reason)) == (Status.SKIPPED, True), f"{given}: {should}"

    def test_bounds_keep_the_0_7_skip(self):
        given = "numeric bounds under the 0.7 catalog"
        should = "keep the single planned logicalTypeOptions skip"

        out = _outcomes(_table(prop("a", "number", logicalTypeOptions={"minimum": 0})), "0.7")

        assert ("T.a.range" in out, out["T.a.logicalTypeOptions"].status) == (
            False,
            Status.SKIPPED,
        ), f"{given}: {should}"

    def test_options_with_no_check_are_reported_not_dropped(self):
        given = "a property with multipleOf"
        should = "report it as skipped instead of dropping it"

        outcome = _option_rule("integer", "logicalTypeOptions", multipleOf=5)

        assert "multipleOf has no PQL.Assert check" in outcome.reason, f"{given}: {should}"


class TestTextLength:
    @pytest.mark.parametrize(
        ("options", "args"),
        [
            ({"minLength": 2, "maxLength": 8}, {"minLen": 2, "maxLen": 8}),
            ({"maxLength": 8}, {"minLen": 0, "maxLen": 8}),
            ({"minLength": 3}, {"minLen": 3, "maxLen": 2147483647}),
        ],
    )
    def test_lengths_map_to_one_range_call(self, options, args):
        given = f"a string property with {options}"
        should = f"call TextLengthShouldBeInRange with {args}"

        outcome = _option_rule("string", "length", **options)

        assert _calls(outcome) == [("col.text_length_in_range", args)], f"{given}: {should}"


class TestAllowedValues:
    def test_enum_maps_to_values_in_set(self):
        given = "an ODCS 3.2 enum of numbers"
        should = "map to Col.ValuesShouldBeInSet with those values"
        schema = _table(prop("a", "integer", enum=[{"value": 1}, {"value": 2}]))

        outcome = _outcomes(schema, api_version="v3.2.0")["T.a.enum"]

        assert (outcome.status, _calls(outcome)) == (
            Status.MAPPED,
            [("col.values_in_set", {"values": [1, 2]})],
        ), f"{given}: {should}"

    def test_text_values_are_approximated_for_case(self):
        given = "an allowed-value list of text with letters"
        should = "be approximated, because DAX compares text without regard to case"

        outcome = _column_rule(
            {"metric": "invalidValues", "mustBe": 0, "arguments": {"validValues": ["open", "closed"]}}
        )

        assert (outcome.status, "without regard to case" in outcome.reason) == (
            Status.APPROXIMATED,
            True,
        ), f"{given}: {should}"

    def test_values_render_as_an_escaped_table_constructor(self):
        given = "an allowed value containing a double quote"
        should = "render it doubled inside a table constructor"
        schema = _table(
            prop(
                "a", quality=[{"metric": "invalidValues", "mustBe": 0, "arguments": {"validValues": ['say "hi"', "x"]}}]
            )
        )

        assert '{"say ""hi""", "x"}, [Value])' in _dax(schema), f"{given}: {should}"

    def test_invalid_value_threshold_counts_rows_outside_the_list(self):
        given = "invalidValues with validValues and a 5 percent ceiling"
        should = "compare the share of non-null rows outside the list with Tbl.RowRateShouldBeAtMost"
        rule = {
            "metric": "invalidValues",
            "mustBeLessOrEqualTo": 5,
            "unit": "percent",
            "arguments": {"validValues": [1, 2]},
        }

        outcome = _column_rule(rule, "integer")

        assert (outcome.status, _calls(outcome)) == (
            Status.MAPPED,
            [("tbl.matching_rate_at_most", {"values": [1, 2], "negate": True, "maxPct": 5})],
        ), f"{given}: {should}"

    @pytest.mark.parametrize(
        ("rule", "logical"),
        [
            ({"metric": "invalidValues", "mustBe": 0, "arguments": {"validValues": ["x"]}}, "integer"),
            ({"metric": "invalidValues", "mustBe": 0, "arguments": {"validValues": ["2020-01-01"]}}, "date"),
            ({"metric": "invalidValues", "mustBe": 0}, "string"),
            ({"metric": "invalidValues", "mustBeGreaterThan": 1, "arguments": {"validValues": ["x"]}}, "string"),
        ],
    )
    def test_unmappable_value_lists_are_skipped(self, rule, logical):
        given = f"{rule} on a {logical} column"
        should = "be skipped with a reason"

        outcome = _column_rule(rule, logical)

        assert (outcome.status, bool(outcome.reason)) == (Status.SKIPPED, True), f"{given}: {should}"


class TestMissingValues:
    def test_default_missing_values_on_text_are_null_and_empty(self):
        given = "missingValues with no list on a string column and a zero ceiling"
        should = "count rows that are null or empty, at most 0"

        outcome = _column_rule({"metric": "missingValues", "mustBe": 0})

        assert (outcome.status, _calls(outcome)) == (
            Status.MAPPED,
            [("tbl.matching_rows_at_most", {"values": [""], "matchNull": True, "maxCount": 0})],
        ), f"{given}: {should}"

    def test_default_missing_values_on_numbers_are_null_only(self):
        given = "missingValues with no list on an integer column and a 10 percent ceiling"
        should = "compare the share of null rows with Tbl.RowRateShouldBeAtMost"
        rule = {"metric": "missingValues", "mustBeLessOrEqualTo": 10, "unit": "percent"}

        outcome = _column_rule(rule, "integer")

        assert _calls(outcome) == [
            ("tbl.matching_rate_at_most", {"values": [], "matchNull": True, "maxPct": 10})
        ], f"{given}: {should}"

    def test_listed_values_without_null_render_a_non_null_filter(self):
        given = "missingValues listing n/a and the empty string, but not null"
        should = "match only non-null rows holding a listed value"
        rule = {"metric": "missingValues", "mustBe": 0, "arguments": {"missingValues": ["n/a", ""]}}

        text = _dax(_table(prop("a", quality=[rule])))

        assert "FILTER('T', NOT ISBLANK('T'[a]) && 'T'[a] IN {\"n/a\", \"\"})" in text, f"{given}: {should}"

    def test_missing_values_keep_the_0_7_skip(self):
        given = "missingValues under the 0.7 catalog"
        should = "keep the planned skip"

        outcome = _column_rule({"metric": "missingValues", "mustBe": 0}, version="0.7")

        assert outcome.status is Status.SKIPPED, f"{given}: {should}"


class TestRelationships:
    def _schema(self, relationship: dict, where: str = "property") -> list:
        fk = prop("customer_id", "integer", customProperties=custom(pbiColumn="CustomerKey"))
        if where == "property":
            fk["relationships"] = [relationship]
        orders = schema_object("orders", [fk], customProperties=custom(pbiTable="Orders"))
        if where == "schema":
            orders["relationships"] = [relationship]
        customers = schema_object("customers", [prop("id", "integer")], customProperties=custom(pbiTable="Customer"))
        return [orders, customers]

    @pytest.mark.parametrize(
        ("relationship", "where", "rule_id"),
        [
            ({"to": "customers.id"}, "property", "orders.customer_id.relationships[0]"),
            ({"from": "orders.customer_id", "to": "customers.id"}, "schema", "orders.relationships[0]"),
        ],
    )
    def test_relationship_maps_with_model_names(self, relationship, where, rule_id):
        given = f"a {where}-level foreign key"
        should = "map to Relationship.ShouldExist with the model's table and column names"

        outcome = _outcomes(self._schema(relationship, where))[rule_id]

        assert (outcome.status, outcome.assertions[0].suite, _calls(outcome)) == (
            Status.MAPPED,
            "Schema",
            [
                (
                    "rel.exists",
                    {"fromTable": "Orders", "fromColumn": "CustomerKey", "toTable": "Customer", "toColumn": "id"},
                )
            ],
        ), f"{given}: {should}"

    @pytest.mark.parametrize(
        "relationship",
        [{"to": "customers.nope"}, {"to": "elsewhere.id"}, {"to": ["customers.id", "customers.id"]}],
    )
    def test_unresolvable_relationships_are_skipped(self, relationship):
        given = f"the relationship {relationship}"
        should = "be skipped with a reason"

        outcome = _outcomes(self._schema(relationship))["orders.customer_id.relationships[0]"]

        assert (outcome.status, bool(outcome.reason)) == (Status.SKIPPED, True), f"{given}: {should}"

    def test_relationships_keep_the_0_7_skip(self):
        given = "a relationship under the 0.7 catalog"
        should = "keep the planned skip"

        outcome = _outcomes(self._schema({"to": "customers.id"}), "0.7")["orders.customer_id.relationships[0]"]

        assert outcome.status is Status.SKIPPED, f"{given}: {should}"

    def test_relationship_renders_target_and_names(self):
        given = "a mapped relationship"
        should = "render Relationship.ShouldExist with four quoted names"

        text = _dax(self._schema({"to": "customers.id"}))

        assert (
            'PQL.Assert.Relationship.ShouldExist("ODCS marvel-contract orders.customer_id.relationships[0]: '
            'orders.customer_id relationship to customers.id", "Orders", "CustomerKey", "Customer", "id")' in text
        ), f"{given}: {should}"


def test_target_of_a_column_rule_is_the_column():
    given = "a mapped allowed-value rule"
    should = "target the resolved model column"

    outcome = _column_rule({"metric": "invalidValues", "mustBe": 0, "arguments": {"validValues": [1]}}, "integer")

    assert outcome.assertions[0].target == Target("T", "a"), f"{given}: {should}"
