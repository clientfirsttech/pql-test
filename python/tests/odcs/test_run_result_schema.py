# SPDX-License-Identifier: AGPL-3.0-only
"""The JSON that `contract run --output` and `contract trace --format json` print is a published contract.

Other tools (datacontract-cli among them) read it, so these tests fail when the output stops
matching contract-run-result.schema.json, or when the schema and the code disagree.
"""

from __future__ import annotations

import json
import shutil
from importlib.resources import files
from pathlib import Path

import pytest
from click.testing import CliRunner
from jsonschema import Draft202012Validator

from pql_test.odcs.api import plan_contract
from pql_test.odcs.cli import contract as contract_cli
from pql_test.odcs.results import REPORT_SCHEMA_VERSION, STATUSES, read_results, trace

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="module")
def schema() -> dict:
    text = files("pql_test.odcs").joinpath("contract-run-result.schema.json").read_text(encoding="utf-8")
    return json.loads(text)


def _validator(schema: dict, ref: str | None = None) -> Draft202012Validator:
    if ref is None:
        return Draft202012Validator(schema)
    return Draft202012Validator({"$ref": ref, "$defs": schema["$defs"]})


def test_schema_is_valid_and_agrees_with_the_code(schema):
    given = "the packaged contract-run-result.schema.json"
    should = "be a valid 2020-12 schema whose version and statuses match the code"
    Draft202012Validator.check_schema(schema)
    report = schema["$defs"]["contractReport"]["properties"]

    assert report["schemaVersion"]["const"] == REPORT_SCHEMA_VERSION, f"{given}: {should}"
    assert tuple(report["rules"]["items"]["properties"]["status"]["enum"]) == STATUSES, f"{given}: {should}"
    assert set(report["summary"]["required"]) == set(STATUSES), f"{given}: {should}"


def test_trace_report_of_real_results_matches_the_schema(schema):
    given = "a trace of recorded results with failures"
    should = "validate against the contractReport definition, with the current schemaVersion"
    plan = plan_contract(FIXTURES / "marvel-must-fail.odcs.yaml")
    results = read_results(FIXTURES / "results-marvel-must-fail.json")

    report = trace(plan, results).to_json()

    assert list(_validator(schema, "#/$defs/contractReport").iter_errors(report)) == [], f"{given}: {should}"
    assert report["schemaVersion"] == REPORT_SCHEMA_VERSION, f"{given}: {should}"
    assert {r["status"] for r in report["rules"]} - {"passed"}, "the fixture should exercise a non-passing status"


def test_full_run_output_of_real_results_matches_the_schema(schema):
    given = "run-tests JSON plus a contract report"
    should = "validate against the top-level schema"
    plan = plan_contract(FIXTURES / "marvel-must-fail.odcs.yaml")
    results = read_results(FIXTURES / "results-marvel-must-fail.json")
    payload = {
        "model_path": "m",
        "passed": 1,
        "failed": 1,
        "skipped": 0,
        "total": 2,
        **results,
        "contract": trace(plan, results).to_json(),
    }

    assert list(_validator(schema).iter_errors(payload)) == [], f"{given}: {should}"


def test_trace_command_json_matches_the_schema(schema, tmp_path):
    given = "pql-test contract trace --format json"
    should = "print the contractReport shape"
    results = tmp_path / "r.json"
    shutil.copy(FIXTURES / "results-marvel-must-fail.json", results)

    result = CliRunner().invoke(
        contract_cli, ["trace", str(FIXTURES / "marvel-must-fail.odcs.yaml"), str(results), "--format", "json"]
    )

    errors = list(_validator(schema, "#/$defs/contractReport").iter_errors(json.loads(result.output)))
    assert (result.exit_code in (0, 1), errors) == (True, []), f"{given}: {should}\n{result.output}"


def test_run_command_output_matches_the_schema(schema, tmp_path, monkeypatch):
    given = "contract run with no XMLA connection, writing --output"
    should = "write JSON that validates against the schema"
    model = tmp_path / "Sample.SemanticModel"
    (model / "definition").mkdir(parents=True)
    shutil.copy(FIXTURES / "marvel.odcs.yaml", tmp_path / "marvel.odcs.yaml")
    monkeypatch.setattr("pql_test.contract_run.xmla_unavailable", lambda: None)
    monkeypatch.setattr("pql_test.contract_run.resolve_xmla_connection", lambda *_a, **_k: None)
    from pql_test.cli import cli

    out = tmp_path / "results.json"
    CliRunner().invoke(
        cli, ["contract", "run", str(tmp_path / "marvel.odcs.yaml"), str(model), "--env", "DEV", "--output", str(out)]
    )

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert list(_validator(schema).iter_errors(payload)) == [], f"{given}: {should}"
