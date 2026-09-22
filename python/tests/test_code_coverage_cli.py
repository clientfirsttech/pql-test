"""
CLI tests for the `code-coverage` command.

`collect_coverage` is mocked via monkeypatch on the `pql_test.cli` module
namespace (same pattern as TestLocalEnumerationReuse in
test_pql_test_cli.py) so these run in-process against a
Click ``CliRunner`` -- no live XMLA connection required.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from click.testing import CliRunner

from pql_test import cli as cli_module
from pql_test.runner.coverage import (
    ClassificationResult,
    CoverageEvidence,
    CoverageGap,
    CoverageObjectType,
    ExclusionRecord,
)
from pql_test.runner.coverage_collector import CoverageReport, UnavailableCategory


def _report():
    return CoverageReport(
        model_path="local/SampleModel",
        test_count=2,
        result=ClassificationResult(
            covered=(CoverageEvidence(CoverageObjectType.TABLE, "MarvelFact", ("T1", "T2")),),
            gaps=(CoverageGap(CoverageObjectType.MEASURE, "MarvelFact[X]", "Add a test"),),
            excluded=(ExclusionRecord(CoverageObjectType.PARTITION, "P1", "no assertion surface"),),
        ),
        unavailable=(UnavailableCategory(CoverageObjectType.RELATIONSHIP, "query failed"),),
    )


class TestCodeCoverageTextOutput:
    def test_terse_output_shows_overall_percentage_and_category_counts(self, monkeypatch):
        monkeypatch.setattr(cli_module, "collect_coverage", MagicMock(return_value=_report()))

        result = CliRunner().invoke(cli_module.cli, ["code-coverage", "local/SampleModel"])

        assert result.exit_code == 0
        assert "Overall: 1/2 covered (50.0%)" in result.output
        assert "TABLE" in result.output
        assert "MEASURE" in result.output
        assert "Unavailable categories" in result.output
        # Terse mode must not list individual objects
        assert "tested by" not in result.output

    def test_verbose_lists_covered_evidence_and_uncovered_hints(self, monkeypatch):
        monkeypatch.setattr(cli_module, "collect_coverage", MagicMock(return_value=_report()))

        result = CliRunner().invoke(
            cli_module.cli, ["code-coverage", "local/SampleModel", "--verbose"]
        )

        assert result.exit_code == 0
        assert "MarvelFact — tested by: T1, T2" in result.output
        assert "MarvelFact[X] — Add a test" in result.output


class TestCodeCoverageJsonOutput:
    def test_format_json_prints_stable_report_to_stdout(self, monkeypatch):
        monkeypatch.setattr(cli_module, "collect_coverage", MagicMock(return_value=_report()))

        result = CliRunner().invoke(
            cli_module.cli, ["code-coverage", "local/SampleModel", "--format", "json"]
        )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        for key in ("summary", "categories", "evidence", "gaps", "exclusions", "unavailable"):
            assert key in payload
        assert payload["summary"] == {"covered": 1, "eligible": 2, "percent": 50.0}

    def test_format_json_with_output_writes_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr(cli_module, "collect_coverage", MagicMock(return_value=_report()))
        out_file = tmp_path / "coverage.json"

        result = CliRunner().invoke(
            cli_module.cli,
            ["code-coverage", "local/SampleModel", "--format", "json", "--output", str(out_file)],
        )

        assert result.exit_code == 0
        payload = json.loads(out_file.read_text(encoding="utf-8"))
        assert payload["summary"]["covered"] == 1

    def test_output_without_format_json_fails_before_any_xmla_query(self, monkeypatch):
        spy = MagicMock(return_value=_report())
        monkeypatch.setattr(cli_module, "collect_coverage", spy)

        result = CliRunner().invoke(
            cli_module.cli, ["code-coverage", "local/SampleModel", "--output", "out.json"]
        )

        assert result.exit_code != 0
        assert "--output requires --format json" in result.output
        spy.assert_not_called()


class TestCodeCoverageMinThreshold:
    def test_min_coverage_below_actual_exits_non_zero(self, monkeypatch):
        monkeypatch.setattr(cli_module, "collect_coverage", MagicMock(return_value=_report()))

        result = CliRunner().invoke(
            cli_module.cli, ["code-coverage", "local/SampleModel", "--min-coverage", "90"]
        )

        assert result.exit_code != 0

    def test_min_coverage_at_or_below_actual_exits_zero(self, monkeypatch):
        monkeypatch.setattr(cli_module, "collect_coverage", MagicMock(return_value=_report()))

        result = CliRunner().invoke(
            cli_module.cli, ["code-coverage", "local/SampleModel", "--min-coverage", "50"]
        )

        assert result.exit_code == 0

    def test_malformed_min_coverage_fails_before_any_xmla_query(self, monkeypatch):
        spy = MagicMock(return_value=_report())
        monkeypatch.setattr(cli_module, "collect_coverage", spy)

        result = CliRunner().invoke(
            cli_module.cli, ["code-coverage", "local/SampleModel", "--min-coverage", "150"]
        )

        assert result.exit_code != 0
        spy.assert_not_called()


class TestCodeCoverageNoConnection:
    def test_no_connection_reports_error_and_exits_non_zero(self, monkeypatch):
        monkeypatch.setattr(cli_module, "collect_coverage", MagicMock(return_value=None))

        result = CliRunner().invoke(cli_module.cli, ["code-coverage", "local/NoSuchModel"])

        assert result.exit_code != 0
        assert "No XMLA connection detected" in result.output
