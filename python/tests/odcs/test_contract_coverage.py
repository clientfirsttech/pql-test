# SPDX-License-Identifier: AGPL-3.0-only
"""`pql-test contract coverage CONTRACT MODEL_PATH`: which model objects a contract covers, from files."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

import pytest
from click.testing import CliRunner
from jsonschema import Draft202012Validator

from pql_test.odcs.coverage import (
    NOT_COUNTED,
    SCHEMA_VERSION,
    Evidence,
    Inventory,
    Kind,
    Level,
    ModelObject,
    classify,
)

REPO = Path(__file__).resolve().parents[3]
SAMPLE = REPO / "examples" / "SampleModel.SemanticModel"
STARTER = REPO / "examples" / "contracts" / "starter.odcs.yaml"
SCENARIOS = REPO / "examples" / "contracts" / "scenario-tests.odcs.yaml"


@pytest.fixture(autouse=True)
def _never_connect(monkeypatch):
    """Without --live, coverage reads files only: any attempt to reach a model fails the test."""

    def refuse(*_args, **_kwargs):
        raise AssertionError("contract coverage tried to connect without --live")

    monkeypatch.setattr("pql_test.contract_run.resolve_xmla_connection", refuse)
    monkeypatch.setenv("PQL_TEST_HERMETIC", "1")


@pytest.fixture
def full_starter(tmp_path) -> Path:
    """The starter contract `init` writes for the whole of SampleModel (examples/contracts/ has a two-table one)."""
    from pql_test.odcs.scaffold import render_starter, starter_contract

    path = tmp_path / "full-starter.odcs.yaml"
    path.write_text(render_starter(starter_contract(SAMPLE), SAMPLE.name), encoding="utf-8")
    return path


def _run(*args):
    from pql_test.cli import cli

    return CliRunner().invoke(cli, ["contract", "coverage", *(str(a) for a in args)])


def _json(*args) -> dict:
    result = _run(*args, "--format", "json")
    assert result.exit_code in (0, 1), result.output
    return json.loads(result.stdout)


def _by_id(report: dict) -> dict[str, dict]:
    return {o["identifier"]: o for o in report["objects"]}


class TestClassify:
    def test_an_object_takes_its_strongest_level_and_its_rules(self):
        given = "a column listed by one rule and values tested by two others"
        should = "be values tested, with the two rules that test its values"
        inventory = Inventory((ModelObject(Kind.COLUMN, "T[c]"),), ())
        evidence = [
            Evidence(Kind.COLUMN, "T[c]", Level.LISTED, "T.c.type"),
            Evidence(Kind.COLUMN, "t[C]", Level.VALUES_TESTED, "T.c.required"),
            Evidence(Kind.COLUMN, "T[c]", Level.VALUES_TESTED, "T.c.range"),
        ]

        (found,) = classify(inventory, evidence)

        assert (found.level, found.rules) == (Level.VALUES_TESTED, ("T.c.required", "T.c.range")), f"{given}: {should}"

    def test_an_object_with_no_evidence_is_not_covered(self):
        given = "a measure no rule names"
        should = "be not covered, with no rules"
        inventory = Inventory((ModelObject(Kind.MEASURE, "T[m]"),), ())

        (found,) = classify(inventory, [Evidence(Kind.MEASURE, "T[other]", Level.VALUES_TESTED, "r")])

        assert (found.level, found.rules) == (Level.NOT_COVERED, ()), f"{given}: {should}"


class TestCoverageCommand:
    def test_reads_only_files_and_reports_every_category(self):
        given = "the starter contract and SampleModel's PBIP folder, with no --live"
        should = "exit 0 without connecting and show the four categories with their levels"

        result = _run(STARTER, SAMPLE)

        assert result.exit_code == 0, f"{given}: {should}\n{result.output}"
        assert all(k.value in result.output for k in Kind), f"{given}: {should}\n{result.output}"
        assert "not covered" in result.output.lower(), f"{given}: {should}\n{result.output}"

    def test_json_matches_the_packaged_schema(self):
        given = "coverage --format json"
        should = "print JSON on stdout that validates against contract-coverage.schema.json, with schemaVersion 1"
        schema = json.loads(files("pql_test.odcs").joinpath("contract-coverage.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)

        report = _json(SCENARIOS, SAMPLE)

        assert list(Draft202012Validator(schema).iter_errors(report)) == [], f"{given}: {should}"
        assert report["schemaVersion"] == SCHEMA_VERSION == 1, f"{given}: {should}"

    def test_a_measure_is_never_listed_only(self):
        given = "the starter contract, which lists every table and column but writes no DAX"
        should = "show every measure as not covered: an ODCS schema has no place to list a measure"

        report = _json(STARTER, SAMPLE)

        levels = {o["level"] for o in report["objects"] if o["kind"] == "MEASURE"}
        assert levels == {"not_covered"}, f"{given}: {should}"

    def test_starter_lists_every_table_and_column(self, full_starter):
        given = "the starter contract init writes for the whole of SampleModel"
        should = "cover every table and column, at least as listed"

        report = _json(full_starter, SAMPLE)

        weak = [o["identifier"] for o in report["objects"] if o["kind"] in ("TABLE", "COLUMN") and o["level"] in ("not_covered", "listed_not_enforced")]
        assert weak == [], f"{given}: {should}"

    def test_contract_dax_credits_what_it_references(self):
        given = "the scenario-tests contract, whose DAX references measures and a column"
        should = "show those measures and the column as values tested, found by the text scan"

        objects = _by_id(_json(SCENARIOS, SAMPLE))

        assert {
            name: (objects[name]["level"], objects[name]["sources"])
            for name in ("MarvelFact[Number of Characters]", "MarvelFact[Appearances]")
        } == {
            "MarvelFact[Number of Characters]": ("values_tested", ["scan"]),
            "MarvelFact[Appearances]": ("values_tested", ["scan"]),
        }, f"{given}: {should}"

    def test_calculated_column_without_a_value_rule_is_its_own_gap(self, full_starter):
        given = "a full starter contract: SampleModel's calculated columns are listed but have no value rule"
        should = "list them as calculated columns whose DAX no rule checks"

        report = _json(full_starter, SAMPLE)

        assert {"DateDim[Month Year]", "MarvelFact[Test Change]"} <= set(report["calculatedColumnsWithoutValueRule"]), (
            f"{given}: {should}"
        )

    def test_says_what_is_never_counted(self):
        given = "SampleModel, which has a measure table"
        should = "say roles, partitions, and calculation groups are not counted, and why the measure table is left out"

        result = _run(STARTER, SAMPLE, "--verbose")

        assert (NOT_COUNTED in result.output, "_Measures" in result.output) == (True, True), f"{given}: {should}"

    @pytest.mark.parametrize(("threshold", "code"), [("100", 1), ("1", 0)])
    def test_min_coverage(self, threshold, code):
        given = f"--min-coverage {threshold} with the starter contract (measures and relationships uncovered)"
        should = f"exit {code}"

        result = _run(STARTER, SAMPLE, "--min-coverage", threshold)

        assert result.exit_code == code, f"{given}: {should}\n{result.output}"


class TestLiveOption:
    def test_without_adomd_live_fails_with_the_reason_and_files_still_work(self, monkeypatch):
        given = "a machine without ADOMD.NET"
        should = "fail --live with exit 1 and the reason, and still run from the PBIP folder without it"
        monkeypatch.setattr("pql_test.contract_run.xmla_unavailable", lambda: "ADOMD.NET is not available here")

        live = _run(SCENARIOS, SAMPLE, "--live")
        files = _run(SCENARIOS, SAMPLE)

        assert (live.exit_code, "ADOMD.NET is not available here" in live.output, files.exit_code) == (1, True, 0), (
            f"{given}: {should}\n{live.output}"
        )

    def test_no_connection_is_an_error_not_an_empty_report(self, monkeypatch):
        given = "--live when no model can be reached"
        should = "exit 1 and say how to connect, instead of reporting 0% coverage"
        monkeypatch.setattr("pql_test.contract_run.xmla_unavailable", lambda: None)
        monkeypatch.setattr("pql_test.contract_run.resolve_xmla_connection", lambda *_a, **_k: None)

        result = _run(SCENARIOS, SAMPLE, "--live")

        assert (result.exit_code, "--workspace-id" in result.output, "covered" in result.stdout) == (1, True, False), (
            f"{given}: {should}\n{result.output}"
        )

    def test_a_model_that_refuses_info_queries_falls_back_to_the_files(self, monkeypatch):
        given = "--live with an identity the model refuses INFO queries to (no write permission), and a PBIP folder"
        should = "count from the PBIP folder and the text scan, exit 0, and say why the model was not read"
        from types import SimpleNamespace

        def refused(_conn, _dax):
            raise RuntimeError("The user does not have permission to run this query.")

        monkeypatch.setattr("pql_test.contract_run.xmla_unavailable", lambda: None)
        monkeypatch.setattr(
            "pql_test.contract_run.resolve_xmla_connection", lambda *_a, **_k: SimpleNamespace(server="srv", catalog="SampleModel")
        )
        monkeypatch.setattr("pql_test.contract_run._execute_dax_query", refused)

        result = _run(SCENARIOS, SAMPLE, "--live", "--format", "json")

        report = json.loads(result.stdout)
        assert (
            result.exit_code,
            report["source"],
            report["summary"]["eligible"] > 0,
            any("write permission" in u for u in report["unavailable"]),
        ) == (0, "files", True, True), f"{given}: {should}\n{result.output}"


@pytest.mark.parametrize("flag", ["--fail-on-skipped", "--closed-schema"])
def test_the_rule_reports_old_flags_point_to_mapping(flag):
    given = f"contract coverage CONTRACT MODEL_PATH {flag} (a flag of the rule report, now `contract mapping`)"
    should = "fail as a usage error that names `contract mapping`, not as an unknown option"

    result = _run(STARTER, SAMPLE, flag)

    assert (result.exit_code, "pql-test contract mapping" in result.output) == (2, True), f"{given}: {should}\n{result.output}"
