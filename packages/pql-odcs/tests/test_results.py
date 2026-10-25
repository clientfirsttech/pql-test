# SPDX-License-Identifier: MIT
"""Unit tests for pql_odcs.results (pql-test --output JSON -> contract rule ids)."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner
from factories import contract_dict, prop, schema_object

from pql_odcs.api import plan_contract
from pql_odcs.cli import contract as contract_cli
from pql_odcs.emit.dax import assign_test_names
from pql_odcs.results import ResultsError, format_text, read_results, trace


def _plan(**root):
    data = contract_dict(
        name="M",
        schema=[
            schema_object(
                "T",
                [prop("id", primaryKey=True, unique=True), prop("n", required=True)],
                quality=[
                    {"metric": "rowCount", "mustBeGreaterThan": 0, "severity": "warning"},
                    {"type": "sql", "query": "SELECT 1", "mustBe": 1},
                ],
            )
        ],
        **root,
    )
    return plan_contract(data)


def _name(plan, rule_id):
    names = assign_test_names(plan.contract, plan.outcomes)
    outcome = next(o for o in plan.outcomes if o.rule_id == rule_id)
    return names[id(outcome.assertions[0])]


def _row(test_name, passed=True, suite="M.DataQuality.DEV.Tests", **extra):
    """A result row in pql-test's documented --output shape."""
    row = {"test_name": test_name, "passed": passed, "skipped": False, "error": None, "suite_name": suite}
    row.update(extra)
    return row


def _statuses(report):
    return {r.rule_id: r.status for r in report.rules}


class TestTrace:
    def test_maps_each_result_to_its_rule(self):
        given = "a passing and a failing result for two generated tests"
        should = "mark those rules passed and failed"
        plan = _plan()
        results = {
            "results": [
                _row(_name(plan, "T.exists"), suite="M.Schema.DEV.Tests"),
                _row(_name(plan, "T.n.required"), False),
            ]
        }

        statuses = _statuses(trace(plan, results))

        assert (statuses["T.exists"], statuses["T.n.required"]) == ("passed", "failed"), f"{given}: {should}"

    def test_a_shared_assertion_reports_on_every_source_rule(self):
        given = "primaryKey and unique sharing one distinct check that failed"
        should = "mark both rules failed"
        plan = _plan()

        statuses = _statuses(trace(plan, {"results": [_row(_name(plan, "T.id.primaryKey"), False)]}))

        assert (statuses["T.id.primaryKey"], statuses["T.id.unique"]) == ("failed", "failed"), f"{given}: {should}"

    def test_rules_without_results_are_not_executed_and_skipped_rules_stay_skipped(self):
        given = "no results at all"
        should = "report mapped rules as not_executed and unmapped rules as skipped"
        statuses = _statuses(trace(_plan(), {"results": []}))

        assert (statuses["T.exists"], statuses["T.quality[1]"]) == ("not_executed", "skipped"), f"{given}: {should}"

    def test_foreign_results_are_listed_as_unmatched(self):
        given = "results from another contract and from a hand-written suite"
        should = "list both as unmatched rather than dropping them"
        plan = _plan()
        other = _row(_name(plan, "T.exists").replace("marvel-contract", "other-contract"))
        hand = _row("Calculations: X equals Y", suite="Calcs.DEV.Tests")

        report = trace(plan, {"results": [other, hand]})

        assert [u["test_name"] for u in report.unmatched] == [other["test_name"], hand["test_name"]], (
            f"{given}: {should}"
        )

    def test_suite_level_error_marks_every_rule_in_that_suite(self):
        given = "a suite that failed to execute (pql-test reports one error row named after the suite)"
        should = "mark that suite's rules as error, leaving other suites alone"
        plan = _plan()
        row = _row("M.DataQuality.DEV.Tests", False, error="Function not found")

        statuses = _statuses(trace(plan, {"results": [row]}))

        assert (statuses["T.n.required"], statuses["T.exists"], statuses["T.quality[0]"]) == (
            "error",
            "not_executed",
            "not_executed",
        ), f"{given}: {should}"

    def test_warning_rules_are_flagged_non_blocking(self):
        given = "a failing warning-severity rule"
        should = "report it failed with severity warning"
        plan = _plan()
        name = _name(plan, "T.quality[0]")

        rule = next(
            r
            for r in trace(plan, {"results": [_row(name, False, suite="M.DataQuality.DEVWARN.Tests")]}).rules
            if r.rule_id == "T.quality[0]"
        )

        assert (rule.status, rule.severity) == ("failed", "warning"), f"{given}: {should}"

    def test_text_report_groups_failures_by_rule(self):
        given = "a failing required rule"
        should = "print the rule id with the expected and actual values"
        plan = _plan()
        row = _row(_name(plan, "T.n.required"), False, expected="Null rate <= 0%", actual="5%")

        text = format_text(trace(plan, {"results": [row]}))

        line = next(line for line in text.splitlines() if "T.n.required" in line)
        assert ("failed" in line, "5%" in text) == (True, True), f"{given}: {should}"


class TestReadResults:
    def test_rejects_json_without_a_results_list(self, tmp_path):
        given = "a JSON file that is not pql-test --output"
        should = "raise ResultsError"
        path = tmp_path / "r.json"
        path.write_text(json.dumps({"tests": []}), encoding="utf-8")

        with pytest.raises(ResultsError) as exc:
            read_results(path)

        assert "results" in str(exc.value), f"{given}: {should}"


class TestTraceCommand:
    def test_json_output_lists_rules_and_unmatched(self, tmp_path):
        given = "pql-odcs trace --format json"
        should = "print a JSON report with rules and unmatched results"
        plan = _plan()
        contract_path = tmp_path / "m.odcs.yaml"
        import yaml

        contract_path.write_text(yaml.safe_dump(plan.contract.data), encoding="utf-8")
        results = tmp_path / "results.json"
        results.write_text(
            json.dumps({"results": [_row(_name(plan, "T.exists"), suite="M.Schema.DEV.Tests")]}), encoding="utf-8"
        )

        result = CliRunner().invoke(contract_cli, ["trace", str(contract_path), str(results), "--format", "json"])

        report = json.loads(result.output)
        assert (result.exit_code, report["summary"]["passed"], report["unmatched"]) == (0, 1, []), f"{given}: {should}"


class TestTraceByPrefix:
    def test_rule_id_prefix_still_matches_after_the_description_changed(self):
        given = "a result whose test name has the same contract and rule id but an older description"
        should = "map to the rule by parsing the ODCS <contractId> <ruleId>: prefix"
        plan = _plan()
        stale = "ODCS marvel-contract T.n.required: an older description"

        statuses = _statuses(trace(plan, {"results": [_row(stale, False)]}))

        assert statuses["T.n.required"] == "failed", f"{given}: {should}"

    def test_static_pql_test_output_fixture(self):
        given = "pql-test --output JSON captured from a live must-fail run against SampleModel"
        should = "trace exactly the planted failures to their rule ids"
        from pathlib import Path

        fixtures = Path(__file__).parent / "fixtures"
        plan = plan_contract(fixtures / "marvel-must-fail.odcs.yaml")
        results = read_results(fixtures / "results-marvel-must-fail.json")

        report = trace(plan, results)

        failed = {r.rule_id for r in report.rules if r.status == "failed"}
        assert (failed, report.unmatched) == (
            {
                "marvel_fact_exactly_one_row",
                "DateDim.Year.unique",
                "date_dim_fewer_than_one_row",
                "ghost.exists",
                "ghost.columns",
            },
            [],
        ), f"{given}: {should}"
