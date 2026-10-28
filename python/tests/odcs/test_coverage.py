# SPDX-License-Identifier: AGPL-3.0-only
"""Unit tests for pql_test.odcs.coverage (rule-by-rule coverage report)."""

from __future__ import annotations

import json

from pql_test.odcs.coverage import build_report, format_text
from pql_test.odcs.loader import load_contract
from pql_test.odcs.mapping import map_contract
from pql_test.odcs.naming import NameResolver
from tests.odcs.factories import contract_dict, prop, schema_object


def _report():
    contract = load_contract(
        contract_dict(
            schema=[
                schema_object(
                    "T",
                    [prop("id", primaryKey=True)],
                    quality=[{"type": "sql", "query": "SELECT 1", "mustBe": 1}],
                )
            ]
        )
    )
    return build_report(contract, map_contract(contract, NameResolver(contract)), version="9.9.9")


class TestBuildReport:
    def test_lists_every_rule_with_status_assertions_and_reason(self):
        given = "a contract with mapped and skipped rules"
        should = "list each rule with its id, status, assertion count, functions, and reason"
        rules = {r["ruleId"]: r for r in _report()["rules"]}

        assert (
            rules["T.id.primaryKey"]["status"],
            rules["T.id.primaryKey"]["assertions"],
            rules["T.id.primaryKey"]["functions"],
            rules["T.quality[0]"]["status"],
            bool(rules["T.quality[0]"]["reason"]),
        ) == ("approximated", 1, ["PQL.Assert.Col.ShouldBeDistinct"], "skipped", True), f"{given}: {should}"

    def test_summary_counts_match_the_rules(self):
        given = "a report"
        should = "summarise totals per status"

        assert _report()["summary"] == {"total": 5, "mapped": 3, "approximated": 1, "skipped": 1}, f"{given}: {should}"

    def test_is_json_serialisable_with_stable_top_level_keys(self):
        given = "a report"
        should = "serialise to JSON with the documented top-level keys"
        report = json.loads(json.dumps(_report()))

        assert list(report) == ["schemaVersion", "generator", "catalog", "contract", "summary", "rules"], (
            f"{given}: {should}"
        )


class TestFormatText:
    def test_shows_status_and_rule_on_each_line_and_reason_for_skips(self):
        given = "a report with a skipped sql rule"
        should = "print one line per rule, showing the skip reason"
        text = format_text(_report())

        skip_line = next(line for line in text.splitlines() if "T.quality[0]" in line)
        assert ("skipped" in skip_line and "type: sql" in skip_line, text.count("\n") >= 5) == (True, True), (
            f"{given}: {should}"
        )
