# SPDX-License-Identifier: AGPL-3.0-only
"""`pql-test contract init`: a starter ODCS contract from a PBIP model's TMDL."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from pql_test.odcs.api import plan_contract
from pql_test.odcs.catalog import LATEST_PQL_ASSERT
from pql_test.odcs.cli import contract
from pql_test.odcs.datatypes import tmdl_model_type
from pql_test.odcs.loader import load_contract
from pql_test.odcs.scaffold import NO_TMDL_TYPE, starter_contract

REPO = Path(__file__).resolve().parents[3]
EXAMPLES = REPO / "examples"
MODELS = sorted(p.name[: -len(".SemanticModel")] for p in EXAMPLES.glob("*.SemanticModel"))


def _init(*args):
    return CliRunner().invoke(contract, ["init", *[str(a) for a in args]])


def _tmdl_model(tmp_path: Path, tables: dict[str, str]) -> Path:
    model = tmp_path / "M.SemanticModel"
    (model / "definition" / "tables").mkdir(parents=True)
    for name, body in tables.items():
        (model / "definition" / "tables" / f"{name}.tmdl").write_text(f"table {name}\n{body}", encoding="utf-8")
    return model


@pytest.mark.parametrize("model", MODELS)
def test_starter_for_each_example_is_valid_lints_and_skips_nothing(tmp_path, model):
    given = f"contract init on examples/{model}"
    should = "write a valid ODCS contract that lints clean against the model and has no skipped rules"
    out = tmp_path / "c.odcs.yaml"

    written = _init(EXAMPLES / f"{model}.SemanticModel", "--output", out)
    lint = CliRunner().invoke(contract, ["lint", str(out), str(EXAMPLES / f"{model}.SemanticModel")])
    # The newest catalog: --pql-assert 0.7 skips every relationship rule.
    plan = plan_contract(out, pql_assert=LATEST_PQL_ASSERT)

    assert (
        written.exit_code,
        lint.exit_code,
        [o.rule_id for o in plan.outcomes if o.status.value == "skipped"],
    ) == (0, 0, []), f"{given}: {should}\n{written.output}\n{lint.output}"


def test_every_starter_type_maps_back_to_the_columns_own_type():
    given = "the type rules of SampleModel's starter"
    should = "each accept the model type of the TMDL column it came from"
    from pql_test.odcs.pbip import model_columns

    model = EXAMPLES / "SampleModel.SemanticModel"
    columns = model_columns(model)
    plan = plan_contract(starter_contract(model))

    mismatches = [
        (a.target.table, a.target.column, a.args["types"])
        for o in plan.outcomes
        for a in o.assertions
        if a.op == "tbl.column_type"
        and tmdl_model_type(columns[a.target.table][a.target.column]) not in a.args["types"]
    ]
    assert mismatches == [], f"{given}: {should}"


class TestTypes:
    TABLE = (
        "\tcolumn s\n\t\tdataType: string\n"
        "\tcolumn i\n\t\tdataType: int64\n"
        "\tcolumn d\n\t\tdataType: double\n"
        "\tcolumn c\n\t\tdataType: decimal\n"
        "\tcolumn b\n\t\tdataType: boolean\n"
        "\tcolumn t\n\t\tdataType: dateTime\n"
        "\tcolumn bin\n\t\tdataType: binary\n"
        "\tcolumn calc = 1 + 1\n\t\tlineageTag: x\n"
    )

    def test_tmdl_types_become_logical_types(self, tmp_path):
        given = "one column of each TMDL type, plus a calculated column with no dataType"
        should = "set the inverse logicalType, pin Currency for decimal, and describe the untyped ones"

        props = starter_contract(_tmdl_model(tmp_path, {"T": self.TABLE}))["schema"][0]["properties"]

        by_name = {p["name"]: p for p in props}
        assert (
            [by_name[n].get("logicalType") for n in ("s", "i", "d", "c", "b", "t", "bin", "calc")],
            by_name["c"]["customProperties"],
            "binary" in by_name["bin"]["description"],
            by_name["calc"]["description"],
        ) == (
            ["string", "integer", "number", "number", "boolean", "date", None, None],
            [{"property": "pbiDataType", "value": "Currency"}],
            True,
            NO_TMDL_TYPE,
        ), f"{given}: {should}"


class TestTables:
    def test_measure_and_automatic_date_tables_are_left_out(self, tmp_path):
        given = "a model with a measure-only table and Power BI's automatic date tables"
        should = "describe only the tables with columns that someone wrote"
        model = _tmdl_model(
            tmp_path,
            {
                "Sales": "\tcolumn Amount\n\t\tdataType: double\n",
                "Measures": "\tmeasure Total = 1\n",
                "LocalDateTable_1a2b": "\tcolumn Date\n\t\tdataType: dateTime\n",
                "DateTableTemplate_3c4d": "\tcolumn Date\n\t\tdataType: dateTime\n",
            },
        )

        assert [o["name"] for o in starter_contract(model)["schema"]] == ["Sales"], f"{given}: {should}"

    def test_table_option_picks_tables_in_any_case(self):
        given = "init --table datedim --table MarvelFact on SampleModel"
        should = "describe only those two tables, in the given order, with their model names"

        result = _init(EXAMPLES / "SampleModel.SemanticModel", "--table", "datedim", "--table", "MarvelFact")

        assert [o["name"] for o in yaml.safe_load(result.output)["schema"]] == ["DateDim", "MarvelFact"], (
            f"{given}: {should}\n{result.output}"
        )

    def test_unknown_table_is_a_usage_error_listing_the_tables(self):
        given = "init --table Nope"
        should = "exit 2 and list the tables the model has"

        result = _init(EXAMPLES / "SampleModel.SemanticModel", "--table", "Nope")

        assert (result.exit_code, "MarvelFact" in result.output) == (2, True), f"{given}: {should}\n{result.output}"


class TestOutput:
    def test_stdout_by_default_with_id_override_and_stable_output(self):
        given = "init twice on SampleModel with --id marvel"
        should = "print the same contract both times, with id marvel and the model name"
        model = EXAMPLES / "SampleModel.SemanticModel"

        first, second = _init(model, "--id", "marvel"), _init(model, "--id", "marvel")

        data = load_contract(yaml.safe_load(first.output)).data
        assert (first.output == second.output, data["id"], data["name"], data["status"]) == (
            True,
            "marvel",
            "SampleModel",
            "draft",
        ), f"{given}: {should}"

    def test_output_refuses_an_existing_file_unless_force(self, tmp_path):
        given = "init --output to a file that exists, then with --force"
        should = "exit 2 and keep the file, then overwrite it"
        out = tmp_path / "c.odcs.yaml"
        out.write_text("mine", encoding="utf-8")
        model = EXAMPLES / "SampleModel.SemanticModel"

        refused = _init(model, "--output", out)
        kept = out.read_text(encoding="utf-8")
        forced = _init(model, "--output", out, "--force")

        assert (refused.exit_code, kept, forced.exit_code, out.read_text(encoding="utf-8").startswith("# Starter")) == (
            2,
            "mine",
            0,
            True,
        ), f"{given}: {should}\n{refused.output}"

    def test_force_without_output_is_a_usage_error(self):
        given = "init --force with no --output"
        should = "exit 2: there is no file to overwrite"

        result = _init(EXAMPLES / "SampleModel.SemanticModel", "--force")

        assert (result.exit_code, "--force goes with --output" in result.output) == (2, True), f"{given}: {should}"

    def test_local_model_name_finds_the_repository_folder(self, monkeypatch):
        given = "init local/SampleModel from the repository's docs/ folder"
        should = "describe examples/SampleModel.SemanticModel"
        monkeypatch.chdir(REPO / "docs")

        result = _init("local/SampleModel")

        assert (result.exit_code, yaml.safe_load(result.output)["name"]) == (0, "SampleModel"), (
            f"{given}: {should}\n{result.output}"
        )


def test_the_skill_template_is_a_valid_contract_that_maps_every_rule():
    given = "the annotated template in the contract skill's 'Writing a contract' section"
    should = "be a valid ODCS contract whose every rule maps on --pql-assert 0.8"
    import re

    skill = (REPO / "skills" / "contract" / "SKILL.md").read_text(encoding="utf-8")
    template = yaml.safe_load(re.search(r"```yaml\n(.*?)```", skill, re.DOTALL).group(1))

    statuses = {o.rule_id: o.status.value for o in plan_contract(template, pql_assert="0.8").outcomes}

    assert set(statuses.values()) == {"mapped"}, f"{given}: {should}\n{statuses}"


class TestReviewEdgeCases:
    def test_measure_table_with_a_hidden_placeholder_column_is_left_out(self, tmp_path):
        given = "a table with measures and one hidden placeholder column (SampleModel's _Measures pattern)"
        should = "be left out like a measure-only table"
        model = _tmdl_model(
            tmp_path,
            {
                "_Measures": "\tmeasure Total = 1\n\n\tcolumn 'Measure Group'\n\t\tisHidden\n",
                "Sales": "\tcolumn Amount\n\t\tdataType: double\n\t\tisHidden\n",
            },
        )

        assert [o["name"] for o in starter_contract(model)["schema"]] == ["Sales"], f"{given}: {should}"

    def test_tables_come_in_case_insensitive_order(self, tmp_path):
        given = "tables b, A, and _c"
        should = "come in the same case-insensitive order on every OS"
        model = _tmdl_model(tmp_path, {n: "\tcolumn x\n\t\tdataType: int64\n" for n in ("b", "A", "_c")})

        assert [o["name"] for o in starter_contract(model)["schema"]] == ["_c", "A", "b"], f"{given}: {should}"

    def test_yaml_special_and_unicode_names_round_trip(self, tmp_path):
        given = "table and column names YAML or ODCS could mangle"
        should = "come back from the YAML unchanged, in a valid contract"
        names = ["yes", "null", "1", " lead", "a: #b", 'it"s', "Año ñ 日本"]
        body = "".join(f"\tcolumn '{n}'\n\t\tdataType: string\n" for n in names)
        model = _tmdl_model(tmp_path, {"T": body})

        result = _init(model)

        props = load_contract(yaml.safe_load(result.output)).data["schema"][0]["properties"]
        assert [p["name"] for p in props] == names, f"{given}: {should}\n{result.output}"

    def test_init_leaves_the_model_folder_unchanged(self, tmp_path):
        given = "init --output outside a copy of SampleModel"
        should = "leave every file in the model folder byte-identical"
        import shutil

        model = tmp_path / "SampleModel.SemanticModel"
        shutil.copytree(EXAMPLES / "SampleModel.SemanticModel", model)
        before = {p: p.read_bytes() for p in model.rglob("*") if p.is_file()}

        _init(model, "--output", tmp_path / "c.odcs.yaml")

        assert {p: p.read_bytes() for p in model.rglob("*") if p.is_file()} == before, f"{given}: {should}"

    @pytest.mark.parametrize(
        ("where", "message"),
        [("inside", "inside SampleModel.SemanticModel"), ("missing", "Cannot write")],
    )
    def test_bad_output_paths_are_usage_errors(self, tmp_path, where, message):
        given = f"init --output into a folder that is {where}"
        should = "exit 2 with a clear message, writing nothing"
        import shutil

        model = tmp_path / "SampleModel.SemanticModel"
        shutil.copytree(EXAMPLES / "SampleModel.SemanticModel", model)
        out = model / "DAXQueries" / "c.odcs.yaml" if where == "inside" else tmp_path / "nowhere" / "c.odcs.yaml"

        result = _init(model, "--output", out)

        assert (result.exit_code, message in result.output, out.exists()) == (2, True, False), (
            f"{given}: {should}\n{result.output}"
        )


class TestRelationships:
    """init writes each relationship between starter tables, with its settings (tasks/init-relationships-epic.md)."""

    def _model(self, tmp_path: Path, relationships: str, tables: dict[str, str] | None = None) -> Path:
        model = _tmdl_model(
            tmp_path,
            tables
            or {
                "Orders": "\tcolumn CustomerId\n\t\tdataType: int64\n",
                "Customer": "\tcolumn Id\n\t\tdataType: int64\n",
            },
        )
        (model / "definition" / "relationships.tmdl").write_text(relationships, encoding="utf-8")
        return model

    def test_relationship_is_written_with_its_settings(self, tmp_path):
        given = "an inactive, cross-filter Both relationship between names a reference can hold"
        should = "write a schema-level foreign key under the from table, by name, with all four settings"
        model = self._model(
            tmp_path,
            "relationship r1\n\tisActive: false\n\tcrossFilteringBehavior: bothDirections\n"
            "\tfromColumn: Orders.CustomerId\n\ttoColumn: Customer.Id\n",
        )

        schema = {o["name"]: o for o in starter_contract(model)["schema"]}

        assert (schema["Orders"]["relationships"], "relationships" in schema["Customer"]) == (
            [
                {
                    "type": "foreignKey",
                    "from": "Orders.CustomerId",
                    "to": "Customer.Id",
                    "customProperties": [
                        {"property": "pbiCardinality", "value": "manyToOne"},
                        {"property": "pbiCrossFilteringBehavior", "value": "both"},
                        {"property": "pbiIsActive", "value": False},
                        {"property": "pbiSecurityFilteringBehavior", "value": "oneDirection"},
                    ],
                }
            ],
            False,
        ), f"{given}: {should}"

    def test_names_with_spaces_are_referenced_by_id(self, tmp_path):
        given = "two relationships from 'Fact Table' to 'Date Dim'[Date ID], whose names have spaces"
        should = "reference both ends by id, give each element one id, and reuse it for the second relationship"
        model = self._model(
            tmp_path,
            "relationship a\n\tfromColumn: 'Fact Table'.'Order Date'\n\ttoColumn: 'Date Dim'.'Date ID'\n\n"
            "relationship b\n\tisActive: false\n\tfromColumn: 'Fact Table'.'Ship Date'\n\ttoColumn: 'Date Dim'.'Date ID'\n",
            {
                "'Fact Table'": "\tcolumn 'Order Date'\n\t\tdataType: int64\n\tcolumn 'Ship Date'\n\t\tdataType: int64\n",
                "'Date Dim'": "\tcolumn 'Date ID'\n\t\tdataType: int64\n",
            },
        )

        schema = {o["name"]: o for o in starter_contract(model)["schema"]}

        fact, date = schema["Fact Table"], schema["Date Dim"]
        assert (
            [(r["from"], r["to"]) for r in fact["relationships"]],
            fact["id"],
            [p.get("id") for p in fact["properties"]],
            date["id"],
            date["properties"][0]["id"],
        ) == (
            [
                ("schema/fact_table/properties/order_date", "schema/date_dim/properties/date_id"),
                ("schema/fact_table/properties/ship_date", "schema/date_dim/properties/date_id"),
            ],
            "fact_table",
            ["order_date", "ship_date"],
            "date_dim",
            "date_id",
        ), f"{given}: {should}"

    def test_relationship_to_a_left_out_table_is_not_written(self, tmp_path):
        given = "init --table Orders on a model whose Orders relates to Customer"
        should = "write no relationship, since Customer is not in the starter"
        model = self._model(tmp_path, "relationship r1\n\tfromColumn: Orders.CustomerId\n\ttoColumn: Customer.Id\n")

        (orders,) = starter_contract(model, tables=("Orders",))["schema"]

        assert "relationships" not in orders, f"{given}: {should}"

    def test_code_coverage_starter_pins_cross_filter_both(self):
        given = "init on examples/CodeCoverage, whose one relationship is cross-filter Both"
        should = "write that relationship by id with pbiCrossFilteringBehavior both"

        schema = {o["name"]: o for o in starter_contract(EXAMPLES / "CodeCoverage.SemanticModel")["schema"]}

        (rel,) = schema["Fact_Table"]["relationships"]
        settings = {c["property"]: c["value"] for c in rel["customProperties"]}
        assert (rel["to"], settings["pbiCrossFilteringBehavior"]) == (
            "schema/date_dim/properties/date_id",
            "both",
        ), f"{given}: {should}"

    def test_header_says_relationships(self):
        given = "the starter's header"
        should = "say it states the model's relationships too"

        result = _init(EXAMPLES / "SampleModel.SemanticModel")

        assert "relationships" in result.output.splitlines()[1], f"{given}: {should}"
