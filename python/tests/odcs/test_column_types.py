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
        [("string", ["Text"]), ("integer", ["Integer"]), ("boolean", ["True/False"])],
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

    @pytest.mark.parametrize("logical", ["date", "timestamp", "time"])
    def test_date_time_types_are_approximated(self, logical):
        given = f"logicalType {logical}"
        should = "check Date, approximated: the model has one date/time type for all three"

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

        assert (
            result.exit_code,
            "is Text in the model" in result.output,
            "expects Integer" in result.output,
            "pbiDataType" in result.output,
        ) == (1, True, True, True), f"{given}: {should}\n{result.output}"

    def test_column_without_a_tmdl_type_is_not_a_type_problem(self, tmp_path):
        given = "DateDim[Month Year], a calculated column with no dataType line, declared as integer"
        should = "lint cleanly: the type is only known in the deployed model"

        result = self._lint(tmp_path, prop("Month Year", "integer"), table="DateDim")

        assert result.exit_code == 0, f"{given}: {should}\n{result.output}"



class TestReviewEdgeCases:
    def test_pbi_data_type_alone_maps(self):
        given = "a property with pbiDataType Binary and no logicalType"
        should = "check exactly Binary"
        p = {"name": "c", "customProperties": custom(pbiDataType="Binary")}

        outcome = _type_rule(p)

        assert (outcome.status, outcome.assertions[0].args) == (Status.MAPPED, {"types": ["Binary"]}), f"{given}: {should}"

    @pytest.mark.parametrize(("alias", "expected"), [("int64", "Integer"), ("dateTime", "Date"), ("double", "Number")])
    def test_pbi_data_type_accepts_tmdl_names(self, alias, expected):
        given = f"pbiDataType {alias} (the TMDL name)"
        should = f"check {expected}"

        outcome = _type_rule(prop("c", "number", customProperties=custom(pbiDataType=alias)))

        assert outcome.assertions[0].args == {"types": [expected]}, f"{given}: {should}"

    def test_tmdl_decimal_is_not_an_alias(self):
        given = "pbiDataType decimal (TMDL's name for Currency, which reads like Decimal Number)"
        should = "be skipped as unknown rather than guessed"

        assert _type_rule(prop("c", "number", customProperties=custom(pbiDataType="decimal"))).status == Status.SKIPPED, (
            f"{given}: {should}"
        )

    def test_pbi_data_type_on_a_nested_property_is_reported(self):
        given = "pbiDataType on an object property (no model column)"
        should = "appear as a skipped type rule, not be dropped"
        p = {"name": "addr", "logicalType": "object", "customProperties": custom(pbiDataType="Text")}
        plan = plan_contract(contract_dict(schema=[schema_object("T", [p])]))

        outcome = {o.rule_id: o for o in plan.outcomes}["T.addr.type"]

        assert outcome.status == Status.SKIPPED, f"{given}: {should}"

    def test_type_check_without_a_column_is_an_emit_error(self):
        given = "a column type assertion whose target has no column"
        should = "raise EmitError instead of rendering an empty name"
        from pql_test.odcs.catalog import load_catalog
        from pql_test.odcs.emit.dax import EmitError, render_call
        from pql_test.odcs.ir import Assertion

        bad = Assertion("r", SCHEMA_SUITE, "tbl.column_type", Target("T"), {"types": ["Text"]}, "d")

        with pytest.raises(EmitError, match="needs a column target"):
            render_call(bad, "t", load_catalog("pql_assert_0_7"))
        assert bad.target.column is None, f"{given}: {should}"

    def test_names_are_escaped_in_both_arguments(self):
        given = 'table It\'s "T" and column Col "A" with a number type'
        should = "double the quotes in the name arguments and inside the SWITCH"
        p = prop('Col "A"', "number")
        plan = plan_contract(contract_dict(name="M", schema=[schema_object('It\'s "T"', [p])]))

        dax = render(plan, env="DEV", version="GOLDEN")[0].content

        assert (
            '"It\'s ""T""", "Col ""A""", SWITCH(' in dax,
            '[Table] = "It\'s ""T""" && [Name] = "Col ""A"""' in dax,
        ) == (True, True), f"{given}: {should}\n{dax}"


class TestLintPbiDataType:
    def test_unknown_pbi_data_type_is_a_lint_problem(self, tmp_path):
        given = "pbiDataType int (not a model type), with no MODEL_PATH"
        should = "exit 1: the type check would silently be skipped"
        import yaml

        p = prop("c", "number", customProperties=custom(pbiDataType="int"))
        path = tmp_path / "c.odcs.yaml"
        path.write_text(yaml.safe_dump(contract_dict(schema=[schema_object("T", [p])])), encoding="utf-8")

        result = CliRunner().invoke(contract, ["lint", str(path)])

        assert (result.exit_code, "T.c.type: pbiDataType 'int'" in result.output) == (1, True), (
            f"{given}: {should}\n{result.output}"
        )


class TestModelColumnsParsing:
    def _model(self, tmp_path, text: str, newline: str = "\n") -> Path:
        tables = tmp_path / "M.SemanticModel" / "definition" / "tables"
        tables.mkdir(parents=True)
        (tables / "T.tmdl").write_bytes(text.replace("\n", newline).encode("utf-8"))
        return tmp_path / "M.SemanticModel"

    TMDL = (
        "table T\n"
        "\tlineageTag: x\n"
        "\n"
        "\tmeasure 'Total' = SUM(T[a])\n"
        "\t\tdataType: double\n"
        "\n"
        "\tcolumn 'a = b'\n"
        "\t\tlineageTag: y\n"
        "\t\tdataType: int64\n"
        "\n"
        "\tcolumn 'Bob''s' = 1 + 1\n"
        "\t\tdataType: string\n"
        "\n"
        "\tpartition T = m\n"
        "\t\tmode: import\n"
    )

    @pytest.mark.parametrize("newline", ["\n", "\r\n"])
    def test_quoted_names_measures_and_partitions(self, tmp_path, newline):
        given = f"a table with a measure, a quoted name with '=', an escaped quote, and a partition ({newline!r})"
        should = "read each column's type, and ignore the measure's"

        columns = model_columns(self._model(tmp_path, self.TMDL, newline))

        assert columns == {"T": {"a = b": "int64", "Bob's": "string"}}, f"{given}: {should}"
