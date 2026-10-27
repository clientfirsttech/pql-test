# SPDX-License-Identifier: BUSL-1.1
"""Tests for `pql-test contract run` (pql_test.contract_run)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import click
import pytest
from click.testing import CliRunner
from pql_test.contract_run import detect_pql_assert, exit_code, extend_contract_group
from pql_test.runner import TestResult

pytest.importorskip("pql_odcs")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES = REPO_ROOT / "packages" / "pql-odcs" / "tests" / "fixtures"


def _result(suite: str, passed: bool = True, skipped: bool = False) -> TestResult:
    return TestResult(test_name=f"{suite}: t", passed=passed, message="", skipped=skipped, suite_name=suite)


class TestExitCode:
    def test_warning_suite_failures_do_not_fail_the_run(self):
        given = "a failure only in a DEVWARN suite"
        should = "exit 0, because warning-severity rules are non-blocking"
        results = [_result("M.DataQuality.DEV.Tests"), _result("M.DataQuality.DEVWARN.Tests", passed=False)]

        assert exit_code(results, {"M.DataQuality.DEV.Tests"}) == 0, f"{given}: {should}"

    def test_blocking_suite_failure_fails_the_run(self):
        given = "a failure in a DEV suite"
        should = "exit 1"
        results = [_result("M.DataQuality.DEV.Tests", passed=False)]

        assert exit_code(results, {"M.DataQuality.DEV.Tests"}) == 1, f"{given}: {should}"

    def test_nothing_executed_fails_the_run(self):
        given = "every result skipped (no XMLA connection)"
        should = "exit 1, matching run-tests, so CI misconfiguration is not a silent pass"
        results = [_result("M.Schema.DEV.Tests", skipped=True)]

        assert exit_code(results, {"M.Schema.DEV.Tests"}) == 1, f"{given}: {should}"


class TestDetectPqlAssert:
    @pytest.mark.parametrize("reported, expected", [("0.8.0", "0.8"), ("0.10.2", "0.8"), ("1.0.0", "0.8"), ("0.7.9", "0.7")])
    def test_version_reported_by_the_model_picks_the_catalog(self, monkeypatch, reported, expected):
        given = f"a model whose PQL.Assert.LibraryVersion() returns {reported}"
        should = f"select the {expected} catalog"
        monkeypatch.setattr("pql_test.contract_run._execute_dax_query", lambda *_a: [{"[Value]": reported}])

        assert detect_pql_assert(object()) == expected, f"{given}: {should}"

    def test_model_without_the_function_means_0_7(self, monkeypatch):
        given = "a model where EVALUATE PQL.Assert.LibraryVersion() raises (PQL.Assert 0.7.x)"
        should = "select the 0.7 catalog instead of failing the run"

        def boom(*_a):
            raise RuntimeError("function not found")

        monkeypatch.setattr("pql_test.contract_run._execute_dax_query", boom)

        assert detect_pql_assert(object()) == "0.7", f"{given}: {should}"

    def test_no_connection_means_0_7(self):
        given = "no XMLA connection"
        should = "select the 0.7 catalog without querying"

        assert detect_pql_assert(None) == "0.7", f"{given}: {should}"


class TestExtendContractGroup:
    def test_adds_run_without_mutating_the_plugin_group(self):
        given = "pql-odcs's contract group"
        should = "get a copy with `run` added and leave the original (used by `pql-odcs`) unchanged"
        from pql_odcs.cli import contract

        extended = extend_contract_group(contract, click.Command("run"))

        assert ("run" in extended.commands, "run" in contract.commands) == (True, False), f"{given}: {should}"


class TestContractRunCommand:
    def test_generates_runs_and_traces_without_a_connection(self, tmp_path, monkeypatch):
        given = "contract run against a PBIP copy with no XMLA connection available"
        should = "write the suites, report every mapped rule as not executed, write --output, and exit 1"
        model = tmp_path / "Sample.SemanticModel"
        (model / "definition").mkdir(parents=True)
        shutil.copy(FIXTURES / "marvel.odcs.yaml", tmp_path / "marvel.odcs.yaml")
        # No Power BI in CI: stub only the external XMLA resolution.
        monkeypatch.setattr("pql_test.contract_run.resolve_xmla_connection", lambda *_a, **_k: None)
        from pql_test.cli import cli

        out = tmp_path / "results.json"
        result = CliRunner().invoke(
            cli, ["contract", "run", str(tmp_path / "marvel.odcs.yaml"), str(model), "--env", "DEV", "--output", str(out)]
        )

        written = sorted(p.name for p in (model / "DAXQueries").iterdir())
        saved = json.loads(out.read_text(encoding="utf-8"))
        assert (
            result.exit_code,
            written,
            "NOT EXECUTED" in result.output,
            saved["skipped"] > 0,
            saved["contract"]["summary"]["not_executed"] > 0,
        ) == (1, ["Marvel.DataQuality.DEV.Tests.dax", "Marvel.Schema.DEV.Tests.dax"], True, True, True), (
            f"{given}: {should}\n{result.output}"
        )

    @pytest.mark.parametrize(
        "args, reported, expected",
        [
            ([], "0.8.0", "Col.NullCountShouldBeAtMost"),
            ([], None, "Col.NullRateShouldBeAtMost"),
            (["--pql-assert", "0.7"], "0.8.0", "Col.NullRateShouldBeAtMost"),
            (["--pql-assert", "0.8"], None, "Col.NullCountShouldBeAtMost"),
        ],
    )
    def test_catalog_follows_the_option_then_the_model(self, tmp_path, monkeypatch, args, reported, expected):
        given = f"contract run {args or 'with the default --pql-assert auto'} on a model reporting {reported}"
        should = f"generate calls containing {expected}"
        from types import SimpleNamespace

        model = tmp_path / "Sample.SemanticModel"
        (model / "definition").mkdir(parents=True)
        contract = tmp_path / "c.odcs.yaml"
        contract.write_text(
            "apiVersion: v3.1.0\nkind: DataContract\nid: c\nversion: '1'\nstatus: active\nschema:\n  - name: T\n    properties:\n      - name: a\n        logicalType: integer\n        required: true\n",
            encoding="utf-8",
        )
        monkeypatch.setattr("pql_test.contract_run.resolve_xmla_connection", lambda *_a, **_k: SimpleNamespace(server="s", catalog="c"))
        monkeypatch.setattr("pql_test.contract_run.run_tests", lambda *_a, **_k: [])

        def library_version(*_a):
            if reported is None:
                raise RuntimeError("function not found")
            return [{"[Value]": reported}]

        monkeypatch.setattr("pql_test.contract_run._execute_dax_query", library_version)
        from pql_test.cli import cli

        result = CliRunner().invoke(cli, ["contract", "run", str(contract), str(model), "--env", "DEV", *args])

        text = "".join(p.read_text(encoding="utf-8") for p in (model / "DAXQueries").iterdir())
        assert expected in text, f"{given}: {should}\n{result.output}"

    def test_invalid_contract_exits_1(self, tmp_path):
        given = "a contract with an unsupported apiVersion"
        should = "exit 1 before generating anything"
        bad = tmp_path / "bad.odcs.yaml"
        bad.write_text("apiVersion: v9.0.0\nkind: DataContract\nid: x\nversion: '1'\nstatus: active\n", encoding="utf-8")
        from pql_test.cli import cli

        result = CliRunner().invoke(cli, ["contract", "run", str(bad), str(tmp_path), "--env", "DEV"])

        assert (result.exit_code, "v3.2.x" in result.output) == (1, True), f"{given}: {should}"


class TestTraceAnnotations:
    def _report(self):
        from pql_odcs.api import plan_contract
        from pql_odcs.results import read_results, trace

        plan = plan_contract(FIXTURES / "marvel-must-fail.odcs.yaml")
        return trace(plan, read_results(FIXTURES / "results-marvel-must-fail.json"))

    def test_github_format_emits_one_error_per_failed_rule(self, capsys):
        given = "--log-format github and five failed contract rules"
        should = "emit one ::error annotation per failed rule, titled with the rule id"
        from pql_test.contract_run import print_trace_annotations

        print_trace_annotations(self._report(), "github")
        lines = capsys.readouterr().out.splitlines()

        assert (len(lines), all(line.startswith("::error title=ODCS rule ") for line in lines)) == (5, True), (
            f"{given}: {should}"
        )

    def test_azuredevops_format_uses_logissue(self, capsys):
        given = "--log-format azuredevops"
        should = "emit ##vso[task.logissue] lines"
        from pql_test.contract_run import print_trace_annotations

        print_trace_annotations(self._report(), "azuredevops")

        assert capsys.readouterr().out.startswith("##vso[task.logissue type=error]ODCS rule "), f"{given}: {should}"
