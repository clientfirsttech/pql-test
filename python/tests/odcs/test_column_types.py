# SPDX-License-Identifier: AGPL-3.0-only
"""Column type rules: ODCS logicalType (or pbiDataType) -> Tbl.ColumnDataTypeShouldBe."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from pql_test.odcs.api import plan_contract, render
from pql_test.odcs.cli import contract
from pql_test.odcs.ir import SCHEMA_SUITE, Status, Target
from pql_test.odcs.pbip import model_columns
from tests.odcs.factories import contract_dict, custom, prop, schema_object

EXAMPLES = Path(__file__).resolve().parents[3] / "examples"


def _type_rule(p: dict, pql_assert: str = "0.7"):
    plan = plan_contract(contract_dict(schema=[schema_object("T", [p])]), pql_assert=pql_assert)
    return {o.rule_id: o for o in plan.outcomes}[f"T.{p['name']}.type"]


class TestMapping:
    @pytest.mark.parametrize(
        ("logical", "types"),
        [("string", ["Text"]), ("integer", ["Integer"]), ("boolean", ["True/False"]), ("date", ["Date"])],
    )
    @pytest.mark.parametrize("pql_assert", ["0.7", "0.8"])
    def test_logical_types_map_to_one_model_type(self, logical, types, pql_assert):
        given = f"logicalType {logical} on the {pql_assert} catalog"
        should = f"map to one Schema-suite column type check for {types}"

        outcome = _type_rule(prop("c", logical), pql_assert)

        a = outcome.assertions[0]
        assert (outcome.status, a.suite, a.op, a.target, a.args) == (
            Status.MAPPED,
            SCHEMA_SUITE,
            "tbl.column_type",
            Target("T", "c"),
            {"types": types},
        ), f"{given}: {should}"

    def test_number_accepts_number_or_currency(self):
        given = "logicalType number"
        should = "map to one check that accepts Number or Currency"

        outcome = _type_rule(prop("c", "number"))

        assert (outcome.status, outcome.assertions[0].args) == (Status.MAPPED, {"types": ["Number", "Currency"]}), (
            f"{given}: {should}"
        )

    @pytest.mark.parametrize("logical", ["timestamp", "time"])
    def test_date_time_types_are_approximated(self, logical):
        given = f"logicalType {logical}"
        should = "check Date, approximated: the model has one date/time type"

        outcome = _type_rule(prop("c", logical))

        assert (outcome.status, outcome.assertions[0].args, "one date/time type" in outcome.reason) == (
            Status.APPROXIMATED,
            {"types": ["Date"]},
            True,
        ), f"{given}: {should}"

    def test_pbi_data_type_pins_the_model_type(self):
        given = "logicalType number with customProperties pbiDataType currency (any case)"
        should = "check exactly Currency"

        outcome = _type_rule(prop("c", "number", customProperties=custom(pbiDataType="currency")))

        assert (outcome.status, outcome.assertions[0].args) == (Status.MAPPED, {"types": ["Currency"]}), (
            f"{given}: {should}"
        )

    def test_unknown_pbi_data_type_is_skipped_with_the_valid_names(self):
        given = "pbiDataType Decimal (not a model type name)"
        should = "skip the rule and list the valid names"

        outcome = _type_rule(prop("c", "number", customProperties=custom(pbiDataType="Decimal")))

        assert (outcome.status, "Currency" in outcome.reason, "True/False" in outcome.reason) == (
            Status.SKIPPED,
            True,
            True,
        ), f"{given}: {should}"

    def test_physical_type_alone_is_skipped(self):
        given = "a property with only physicalType DECIMAL(10,2)"
        should = "skip: the source system's type is not the model's; say to add logicalType or pbiDataType"
        p = {"name": "c", "physicalType": "DECIMAL(10,2)"}

        outcome = _type_rule(p)

        assert (outcome.status, "physicalType DECIMAL(10,2)" in outcome.reason, "pbiDataType" in outcome.reason) == (
            Status.SKIPPED,
            True,
            True,
        ), f"{given}: {should}"

    def test_logical_type_wins_over_physical_type(self):
        given = "logicalType integer and physicalType BIGINT"
        should = "check the logicalType's model type"

        outcome = _type_rule(prop("c", "integer", physicalType="BIGINT"))

        assert outcome.assertions[0].args == {"types": ["Integer"]}, f"{given}: {should}"


class TestRendering:
    def _schema_dax(self, p: dict) -> str:
        plan = plan_contract(contract_dict(name="M", schema=[schema_object("T", [p])]))
        return render(plan, env="DEV", version="GOLDEN")[0].content

    def test_one_type_is_a_string_argument(self):
        given = "a check for one model type"
        should = 'pass the type name as the expected type: ..., "T", "c", "Integer")'

        assert '"T", "c", "Integer")' in self._schema_dax(prop("c", "integer")), f"{given}: {should}"

    def test_several_types_expect_the_columns_own_type_when_allowed(self):
        given = "a check that accepts Number or Currency"
        should = "expect Currency when the column is Currency, else Number, so a failure names both types"

        dax = self._schema_dax(prop("c", "number"))

        assert (
            'SWITCH(MAXX(FILTER(INFO.VIEW.COLUMNS(), [Table] = "T" && [Name] = "c"), [DataType]), '
            '"Currency", "Currency", "Number"))'
        ) in dax, f"{given}: {should}\n{dax}"


class TestModelColumns:
    def test_reads_each_columns_tmdl_data_type(self):
        given = "examples/SampleModel's DataTypes and DateDim tables"
        should = "read every column's dataType, and None for a calculated column without one"

        columns = model_columns(EXAMPLES / "SampleModel.SemanticModel")

        assert (columns["DataTypes"], columns["DateDim"]["Month Year"]) == (
            {
                "Whole Number": "int64",
                "Decimal Number": "double",
                "Boolean": "boolean",
                "Text": "string",
                "Date": "dateTime",
                "Currency": "decimal",
            },
            None,
        ), f"{given}: {should}"


class TestLint:
    def _lint(self, tmp_path, p: dict, table: str = "DataTypes"):
        path = tmp_path / "c.odcs.yaml"
        import yaml

        data = contract_dict(schema=[schema_object(table, [p])])
        path.write_text(yaml.safe_dump(data), encoding="utf-8")
        return CliRunner().invoke(contract, ["lint", str(path), str(EXAMPLES / "SampleModel.SemanticModel")])

    @pytest.mark.parametrize(
        ("column", "logical"),
        [("Whole Number", "integer"), ("Decimal Number", "number"), ("Currency", "number"), ("Date", "date")],
    )
    def test_matching_types_pass(self, tmp_path, column, logical):
        given = f"DataTypes[{column}] declared as {logical}"
        should = "lint cleanly"

        result = self._lint(tmp_path, prop(column, logical))

        assert result.exit_code == 0, f"{given}: {should}\n{result.output}"

    def test_mismatch_names_both_types_and_pbi_data_type(self, tmp_path):
        given = "DataTypes[Text] declared as integer"
        should = "exit 1 with a problem naming Text, Integer, and pbiDataType"

        result = self._lint(tmp_path, prop("Text", "integer"))

        assert (result.exit_code, "is Text in the model" in result.output, "expects Integer" in result.output) == (
            1,
            True,
            True,
        ), f"{given}: {should}\n{result.output}"

    def test_column_without_a_tmdl_type_is_not_a_type_problem(self, tmp_path):
        given = "DateDim[Month Year], a calculated column with no dataType line, declared as integer"
        should = "lint cleanly: the type is only known in the deployed model"

        result = self._lint(tmp_path, prop("Month Year", "integer"), table="DateDim")

        assert result.exit_code == 0, f"{given}: {should}\n{result.output}"

