# SPDX-License-Identifier: BUSL-1.1
"""Tests for `pql-test contract run` (pql_test.contract_run)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import click
import pytest
from click.testing import CliRunner
from pql_test.contract_run import exit_code, extend_contract_group
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
        assert (
            result.exit_code,
            written,
            "NOT EXECUTED" in result.output,
            json.loads(out.read_text(encoding="utf-8"))["skipped"] > 0,
        ) == (1, ["Marvel.DataQuality.DEV.Tests.dax", "Marvel.Schema.DEV.Tests.dax"], True, True), (
            f"{given}: {should}\n{result.output}"
        )

    def test_invalid_contract_exits_1(self, tmp_path):
        given = "a contract with an unsupported apiVersion"
        should = "exit 1 before generating anything"
        bad = tmp_path / "bad.odcs.yaml"
        bad.write_text("apiVersion: v9.0.0\nkind: DataContract\nid: x\nversion: '1'\nstatus: active\n", encoding="utf-8")
        from pql_test.cli import cli

        result = CliRunner().invoke(cli, ["contract", "run", str(bad), str(tmp_path), "--env", "DEV"])

        assert (result.exit_code, "v3.0.x and v3.1.x" in result.output) == (1, True), f"{given}: {should}"
