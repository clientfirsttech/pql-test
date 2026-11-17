# SPDX-License-Identifier: AGPL-3.0-only
"""CLI tests for the file-only `pql-test contract` commands."""

from __future__ import annotations

import json

import pytest
import yaml
from click.testing import CliRunner

from pql_test.odcs.cli import contract
from tests.odcs.factories import contract_dict, prop, schema_object


def _write_contract(tmp_path, data=None):
    data = data or contract_dict(
        name="M",
        schema=[
            schema_object(
                "T",
                [prop("id", required=True)],
                quality=[
                    {"metric": "rowCount", "mustBeGreaterThan": 0},
                    {"type": "sql", "query": "SELECT 1", "mustBe": 1},
                ],
            )
        ],
    )
    path = tmp_path / "m.odcs.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _pbip(tmp_path, tables: dict | None = None):
    sm = tmp_path / "Model" / "Sample.SemanticModel"
    (sm / "definition" / "tables").mkdir(parents=True)
    for table, columns in (tables or {}).items():
        body = f"table {table}\n" + "".join(f"\tcolumn {c}\n" for c in columns)
        (sm / "definition" / "tables" / f"{table}.tmdl").write_text(body, encoding="utf-8")
    return sm.parent


def _run(*args):
    return CliRunner().invoke(contract, [str(a) for a in args])


class TestGenerate:
    def test_writes_suites_and_reports_coverage(self, tmp_path):
        given = "generate with a valid contract and a PBIP model"
        should = "exit 0, write the suites, and summarise how the rules map"
        model = _pbip(tmp_path)

        result = _run("generate", _write_contract(tmp_path), model, "--env", "DEV")

        written = sorted(p.name for p in (model / "Sample.SemanticModel" / "DAXQueries").iterdir())
        assert (result.exit_code, written, "1 skipped" in result.output) == (
            0,
            ["M.DataQuality.DEV.Tests.dax", "M.Schema.DEV.Tests.dax"],
            True,
        ), f"{given}: {should}\n{result.output}"

    def test_dry_run_prints_dax_and_writes_nothing(self, tmp_path):
        given = "generate --dry-run"
        should = "print the DAX to stdout and leave the model untouched"
        model = _pbip(tmp_path)

        result = _run("generate", _write_contract(tmp_path), model, "--env", "DEV", "--dry-run")

        assert (
            result.exit_code,
            "EVALUATE M.Schema.DEV.Tests()" in result.output,
            (model / "Sample.SemanticModel" / "DAXQueries").exists(),
        ) == (0, True, False), f"{given}: {should}"

    def test_suite_prefix_overrides_the_default(self, tmp_path):
        given = "generate --suite-prefix Contracts"
        should = "name the suites with that prefix"

        result = _run(
            "generate", _write_contract(tmp_path), tmp_path, "--env", "DEV", "--dry-run", "--suite-prefix", "Contracts"
        )

        assert "FUNCTION Contracts.Schema.DEV.Tests" in result.output, f"{given}: {should}"

    def test_non_pbip_model_path_is_a_usage_error(self, tmp_path):
        given = "a MODEL_PATH that is not a PBIP folder"
        should = "exit 2 and list the accepted MODEL_PATH forms"

        result = _run("generate", _write_contract(tmp_path), tmp_path / "nowhere", "--env", "DEV")

        assert (result.exit_code, "local/<name>" in result.output) == (2, True), f"{given}: {should}"

    def test_local_model_missing_from_the_repository_is_a_usage_error(self, tmp_path, monkeypatch):
        given = "lint CONTRACT local/Missing in a repository with no Missing.SemanticModel"
        should = "exit 2 and say to pass the folder instead"
        (tmp_path / ".git").mkdir()
        monkeypatch.chdir(tmp_path)

        result = _run("lint", _write_contract(tmp_path), "local/Missing")

        assert (result.exit_code, "pass the folder instead" in result.output) == (2, True), (
            f"{given}: {should}\n{result.output}"
        )

    def test_hand_written_target_is_a_usage_error_without_force(self, tmp_path):
        given = "a hand-written file at a generated suite's path"
        should = "exit 2 and suggest --force"
        model = _pbip(tmp_path)
        daxq = model / "Sample.SemanticModel" / "DAXQueries"
        daxq.mkdir()
        (daxq / "M.Schema.DEV.Tests.dax").write_text("// mine\n", encoding="utf-8")

        result = _run("generate", _write_contract(tmp_path), model, "--env", "DEV")

        assert (result.exit_code, "--force" in result.output) == (2, True), f"{given}: {should}"

    def test_invalid_contract_exits_1(self, tmp_path):
        given = "a contract that fails ODCS schema validation"
        should = "exit 1 and print the violation's JSON path"
        bad = contract_dict(schema=[schema_object("T", [prop("x", required="yes")])])

        result = _run("generate", _write_contract(tmp_path, bad), tmp_path, "--env", "DEV")

        assert (result.exit_code, "$.schema[0].properties[0].required" in result.output) == (1, True), (
            f"{given}: {should}"
        )

    def test_bad_environment_token_is_a_usage_error(self, tmp_path):
        given = "--env with a space"
        should = "exit 2"

        result = _run("generate", _write_contract(tmp_path), tmp_path, "--env", "DEV X", "--dry-run")

        assert result.exit_code == 2, f"{given}: {should}"

    def test_fail_on_skipped_exits_1_after_writing(self, tmp_path):
        given = "generate --fail-on-skipped with a skipped sql rule"
        should = "still write the suites, then exit 1 naming the skipped rule"
        model = _pbip(tmp_path)

        result = _run("generate", _write_contract(tmp_path), model, "--env", "DEV", "--fail-on-skipped")

        assert (
            result.exit_code,
            "T.quality[1]" in result.output,
            (model / "Sample.SemanticModel" / "DAXQueries" / "M.Schema.DEV.Tests.dax").exists(),
        ) == (1, True, True), f"{given}: {should}"


class TestMapping:
    def test_json_format_is_machine_readable(self, tmp_path):
        given = "mapping --format json"
        should = "print only the JSON report on stdout"

        result = _run("mapping", _write_contract(tmp_path), "--format", "json")

        assert (result.exit_code, json.loads(result.output)["summary"]["skipped"]) == (0, 1), f"{given}: {should}"

    def test_text_format_lists_rules(self, tmp_path):
        given = "mapping with default text format"
        should = "list each rule id"

        result = _run("mapping", _write_contract(tmp_path))

        assert all(r in result.output for r in ("T.exists", "T.id.required", "T.quality[1]")), f"{given}: {should}"

    def test_fail_on_skipped_exits_1_after_the_report(self, tmp_path):
        given = "mapping --fail-on-skipped with a skipped rule"
        should = "print the full report, then exit 1"

        result = _run("mapping", _write_contract(tmp_path), "--fail-on-skipped")

        assert (result.exit_code, "T.exists" in result.output) == (1, True), f"{given}: {should}"


class TestLint:
    def test_valid_contract_and_matching_model_pass(self, tmp_path):
        given = "a valid contract whose tables and columns exist in the model"
        should = "exit 0"
        model = _pbip(tmp_path, {"T": ["id"]})

        result = _run("lint", _write_contract(tmp_path), model)

        assert result.exit_code == 0, f"{given}: {should}\n{result.output}"

    def test_lists_every_unresolved_name(self, tmp_path):
        given = "a model missing one table's column, and a pbiTable naming a table the model lacks"
        should = "list every problem and exit 1"
        model = _pbip(tmp_path, {"T": ["other"]})
        data = contract_dict(
            name="M",
            schema=[
                schema_object("T", [prop("id")]),
                schema_object("u", [prop("x")], customProperties=[{"property": "pbiTable", "value": "Ghost"}]),
            ],
        )

        result = _run("lint", _write_contract(tmp_path, data), model)

        assert (
            result.exit_code,
            "T.id: column 'id' not found in model table 'T'" in result.output,
            "u: table 'Ghost' not found in model" in result.output,
        ) == (1, True, True), f"{given}: {should}\n{result.output}"

    def test_sidecar_mapping_option_no_longer_exists(self, tmp_path):
        given = "--mapping (removed: names come only from the contract's customProperties)"
        should = "be rejected as a usage error"

        assert _run("mapping", _write_contract(tmp_path), "--mapping", "x.yaml").exit_code == 2, f"{given}: {should}"

    def test_schema_violations_are_listed(self, tmp_path):
        given = "a contract with two schema violations"
        should = "list both and exit 1"
        bad = contract_dict(schema=[schema_object("T", [prop("x", required="yes"), prop("y", unique=2)])])

        result = _run("lint", _write_contract(tmp_path, bad))

        assert (result.exit_code, result.output.count("$.schema[0]")) == (1, 2), f"{given}: {should}"

    def test_missing_contract_file_is_a_usage_error(self, tmp_path):
        given = "a CONTRACT path that does not exist"
        should = "exit 2"

        assert _run("lint", tmp_path / "nope.yaml").exit_code == 2, f"{given}: {should}"


def test_lint_model_names_are_case_insensitive(tmp_path):
    given = "a model table and column whose names differ from the contract only by case"
    should = "pass, because DAX object names are case-insensitive"
    model = _pbip(tmp_path, {"t": ["ID"]})

    result = _run("lint", _write_contract(tmp_path), model)

    assert result.exit_code == 0, f"{given}: {should}\n{result.output}"


class TestLintRelationships:
    def _contract(self, tmp_path):
        fk = prop("dim_id", "integer", relationships=[{"to": "dim.id"}])
        data = contract_dict(schema=[schema_object("Fact Table", [fk]), schema_object("dim", [prop("id", "integer")])])
        return _write_contract(tmp_path, data)

    def _model(self, tmp_path, relationship: str):
        model = _pbip(tmp_path, {"'Fact Table'": ["dim_id"], "dim": ["id"]})
        tmdl = model / "Sample.SemanticModel" / "definition" / "relationships.tmdl"
        tmdl.write_text(f"relationship 1a2b\n{relationship}", encoding="utf-8")
        return model

    def test_relationship_in_the_model_passes(self, tmp_path):
        given = "a contract foreign key the model defines (quoted table name)"
        should = "pass lint"
        model = self._model(tmp_path, "\tfromColumn: 'Fact Table'.dim_id\n\ttoColumn: dim.id\n")

        result = _run("lint", self._contract(tmp_path), model)

        assert result.exit_code == 0, f"{given}: {should}\n{result.output}"

    def test_reversed_relationship_is_reported(self, tmp_path):
        given = "a contract foreign key the model defines from the key side"
        should = "fail lint, saying the model defines it from the key side"
        model = self._model(tmp_path, "\tfromColumn: dim.id\n\ttoColumn: 'Fact Table'.dim_id\n")

        result = _run("lint", self._contract(tmp_path), model)

        assert (result.exit_code, "is defined from the key side in the model" in result.output) == (
            1,
            True,
        ), f"{given}: {should}\n{result.output}"

    def test_missing_relationship_is_reported(self, tmp_path):
        given = "a contract foreign key the model does not define"
        should = "fail lint, naming the relationship"
        model = _pbip(tmp_path, {"'Fact Table'": ["dim_id"], "dim": ["id"]})

        result = _run("lint", self._contract(tmp_path), model)

        assert (result.exit_code, "Fact Table[dim_id] -> dim[id] is not in the model" in result.output) == (
            1,
            True,
        ), f"{given}: {should}\n{result.output}"


class TestLintReferences:
    """ODCS has no escape syntax for a name a table.property reference cannot hold; the id form references it."""

    def _contract(self, tmp_path, to, **relationship):
        fk = prop("Date ID", "integer", id="date_id", relationships=[{"to": to, **relationship}])
        key = prop("Date ID", "integer", id="date_id")
        schema = [schema_object("Fact Table", [fk], id="fact"), schema_object("Date Dim", [key], id="date_dim")]
        return _write_contract(tmp_path, contract_dict(schema=schema))

    def _model(self, tmp_path):
        model = _pbip(tmp_path, {"'Fact Table'": ["'Date ID'"], "'Date Dim'": ["'Date ID'"]})
        tmdl = model / "Sample.SemanticModel" / "definition" / "relationships.tmdl"
        tmdl.write_text(
            "relationship 1a2b\n\tfromColumn: 'Fact Table'.'Date ID'\n\ttoColumn: 'Date Dim'.'Date ID'\n",
            encoding="utf-8",
        )
        return model

    def test_id_reference_to_names_with_spaces_passes(self, tmp_path):
        given = "a foreign key to a column with a space in its name, referenced by id"
        should = "pass lint against a model that defines the relationship"

        result = _run("lint", self._contract(tmp_path, "schema/date_dim/properties/date_id"), self._model(tmp_path))

        assert result.exit_code == 0, f"{given}: {should}\n{result.output}"

    @pytest.mark.parametrize(
        "reference",
        [
            "Date Dim.Date ID",
            '"Date Dim"."Date ID"',
            "[Date Dim].[Date ID]",
            "`Date Dim`.`Date ID`",
            r"Date_Dim.Date\ ID",
            "Date_Dim.Date%20ID",
        ],
    )
    @pytest.mark.parametrize("api_version", ["v3.1.0", "v3.2.0"])
    def test_escaped_name_fails_with_one_explanation(self, tmp_path, reference, api_version):
        given = f"the reference {reference!r} in an ODCS {api_version} contract"
        should = "fail lint with one problem that says there is no escape syntax and shows the id form"
        path = self._contract(tmp_path, reference)
        path.write_text(path.read_text(encoding="utf-8").replace("v3.1.0", api_version), encoding="utf-8")

        result = _run("lint", path)

        assert (
            result.exit_code,
            "1 problem(s)" in result.output,
            "no escape syntax" in result.output,
            "schema/<object id>/properties/<property id>" in result.output,
        ) == (1, True, True, True), f"{given}: {should}\n{result.output}"

    @pytest.mark.parametrize(
        ("reference", "says"),
        [
            ("schema/date_dim/properties/nope", "has no property with the id 'nope'"),
            ("schema/nope/properties/date_id", "no schema object has the id 'nope'"),
            ("Date_Dim.Date_ID", "names no column property"),
        ],
    )
    def test_reference_that_names_nothing_fails(self, tmp_path, reference, says):
        given = f"the well-formed reference {reference!r}, which names nothing in the contract"
        should = "fail lint, saying what is missing, because lint claims every name resolves"

        result = _run("lint", self._contract(tmp_path, reference))

        assert (result.exit_code, says in result.output) == (1, True), f"{given}: {should}\n{result.output}"

    @pytest.mark.parametrize(
        ("api_version", "target", "reference"),
        [
            ("v3.1.0", prop("y", "object", properties=[prop("z")]), "b.y"),
            ("v3.2.0", prop("y", "object", properties=[prop("z")]), "b.y.z"),
        ],
    )
    def test_reference_to_a_non_column_property_passes(self, tmp_path, api_version, target, reference):
        given = f"the valid {api_version} reference {reference!r} to an object property"
        should = "pass lint, because it names something; mapping reports the rule as skipped"
        a = schema_object("a", [prop("x", relationships=[{"to": reference}])])
        contract = contract_dict(api_version, schema=[a, schema_object("b", [target])])

        result = _run("lint", _write_contract(tmp_path, contract))

        assert result.exit_code == 0, f"{given}: {should}\n{result.output}"

    def test_a_typo_key_beside_a_rejected_reference_is_still_reported(self, tmp_path):
        given = "a relationship with a rejected reference and an unknown key 'too'"
        should = "report both: the reference explained, and the unknown key"
        a = schema_object("a", [prop("x", relationships=[{"to": "b.y z", "too": 1}])])
        contract = contract_dict(schema=[a, schema_object("b", [prop("y z")])])

        result = _run("lint", _write_contract(tmp_path, contract))

        assert ("no escape syntax" in result.output, "'too'" in result.output) == (True, True), (
            f"{given}: {should}\n{result.output}"
        )

    def test_a_rejected_reference_in_a_composite_is_explained(self, tmp_path):
        given = "a composite relationship with one rejected item"
        should = "explain that item by its index, instead of the schema's error for the whole list"
        rel = {"from": ["a.x", "a.y z"], "to": ["b.x", "b.y"]}
        a = schema_object("a", [prop("x"), prop("y z")], relationships=[rel])
        contract = contract_dict(schema=[a, schema_object("b", [prop("x"), prop("y")])])

        result = _run("lint", _write_contract(tmp_path, contract))

        assert (
            "relationships[0].from[1]: 'a.y z' is not a valid ODCS reference" in result.output,
            "is not valid under any of the given schemas" in result.output,
        ) == (True, False), f"{given}: {should}\n{result.output}"

    def test_composite_relationship_passes(self, tmp_path):
        given = "a valid composite (multi-column) relationship, which mapping reports as skipped"
        should = "pass lint, because it is valid ODCS that resolves"
        a = schema_object("a", [prop("x"), prop("y")])
        b = schema_object("b", [prop("x"), prop("y")], relationships=[{"from": ["b.x", "b.y"], "to": ["a.x", "a.y"]}])

        result = _run("lint", _write_contract(tmp_path, contract_dict(schema=[a, b])))

        assert result.exit_code == 0, f"{given}: {should}\n{result.output}"
