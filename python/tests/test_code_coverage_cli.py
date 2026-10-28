# SPDX-License-Identifier: AGPL-3.0-only
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
from pql_test.runner.models import ResolvedXmlaConnection


def _report(connection=None, test_count=2):
    return CoverageReport(
        model_path="local/SampleModel",
        test_count=test_count,
        result=ClassificationResult(
            covered=(CoverageEvidence(CoverageObjectType.TABLE, "MarvelFact", ("T1", "T2")),),
            gaps=(CoverageGap(CoverageObjectType.MEASURE, "MarvelFact[X]", "Add a test"),),
            excluded=(ExclusionRecord(CoverageObjectType.PARTITION, "P1", "no assertion surface"),),
        ),
        unavailable=(UnavailableCategory(CoverageObjectType.RELATIONSHIP, "query failed"),),
        connection=connection,
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

    def test_shows_connection_line_and_session_banner_matching_run_tests(self, monkeypatch):
        given = "a report carrying the resolved XMLA connection collect_coverage used"
        should = (
            "the text output shows the same 'Local XMLA connection: server / catalog:' "
            "diagnostic and 'session starts' banner that run-tests shows, for CLI consistency"
        )
        conn = ResolvedXmlaConnection(server="localhost:56622", catalog="")
        monkeypatch.setattr(
            cli_module, "collect_coverage", MagicMock(return_value=_report(connection=conn))
        )

        result = CliRunner().invoke(cli_module.cli, ["code-coverage", "local/SampleModel"])

        assert result.exit_code == 0
        assert "Local XMLA connection: localhost:56622 / catalog:" in result.output, f"{given}: {should}"
        assert "coverage session starts" in result.output, f"{given}: {should}"
        assert "model: local/SampleModel" in result.output, f"{given}: {should}"

    def test_no_connection_line_when_report_has_no_connection(self, monkeypatch):
        given = "a report with no connection attached (e.g. a test double built without one)"
        should = "no connection-diagnostic line is printed, rather than crashing or printing 'None'"
        monkeypatch.setattr(cli_module, "collect_coverage", MagicMock(return_value=_report()))

        result = CliRunner().invoke(cli_module.cli, ["code-coverage", "local/SampleModel"])

        assert result.exit_code == 0
        assert "XMLA connection" not in result.output, f"{given}: {should}"

    def test_zero_tests_discovered_shows_pql_assert_install_hint(self, monkeypatch):
        given = "collect_coverage returns a report with test_count == 0"
        should = (
            "the text output prints a hint that coverage can't be measured "
            "until PQL.Assert is installed, so the user isn't left reading "
            "a bare 0% table with no explanation"
        )
        monkeypatch.setattr(
            cli_module, "collect_coverage", MagicMock(return_value=_report(test_count=0))
        )

        result = CliRunner().invoke(cli_module.cli, ["code-coverage", "local/SampleModel"])

        assert result.exit_code == 0
        assert "Tests discovered: 0" in result.output, f"{given}: {should}"
        assert "PQL.Assert" in result.output, f"{given}: {should}"

    def test_no_pql_assert_hint_when_tests_were_discovered(self, monkeypatch):
        given = "collect_coverage returns a report with test_count > 0"
        should = "no install hint is printed since tests were actually found"
        monkeypatch.setattr(
            cli_module, "collect_coverage", MagicMock(return_value=_report(test_count=2))
        )

        result = CliRunner().invoke(cli_module.cli, ["code-coverage", "local/SampleModel"])

        assert result.exit_code == 0
        assert "PQL.Assert" not in result.output, f"{given}: {should}"

    def test_category_table_colors_full_coverage_green_and_zero_coverage_red(self, monkeypatch):
        given = "a category at 100% coverage and one at 0% coverage"
        should = (
            "the table colors the fully-covered row's percent green (like a PASS) and the "
            "zero-covered row's percent red (like a FAIL) -- the same vocabulary run-tests uses"
        )
        monkeypatch.setattr(cli_module, "collect_coverage", MagicMock(return_value=_report()))

        result = CliRunner().invoke(
            cli_module.cli, ["code-coverage", "local/SampleModel"], color=True
        )
        lines = result.output.splitlines()
        green_line = next(line for line in lines if "TABLE" in line)
        red_line = next(line for line in lines if "MEASURE" in line)

        assert result.exit_code == 0
        assert "\x1b[32m" in green_line, f"{given}: {should}"  # ANSI green (STATUS_COLORS['PASS'])
        assert "\x1b[31m" in red_line, f"{given}: {should}"  # ANSI red (STATUS_COLORS['FAIL'])


    def test_category_colors_follow_min_coverage_threshold(self, monkeypatch):
        given = "a 50% overall report run with --min-coverage 40"
        should = (
            "the 50% overall line is green (at/above the threshold) instead of the "
            "default-watermark yellow, so color agrees with the exit code"
        )
        monkeypatch.setattr(cli_module, "collect_coverage", MagicMock(return_value=_report()))

        result = CliRunner().invoke(
            cli_module.cli,
            ["code-coverage", "local/SampleModel", "--min-coverage", "40"],
            color=True,
        )
        overall_line = next(line for line in result.output.splitlines() if "Overall:" in line)

        assert result.exit_code == 0
        assert "[32m" in overall_line, f"{given}: {should}"

    def test_overall_colored_by_default_watermarks_without_threshold(self, monkeypatch):
        given = "a 50% overall report with no --min-coverage"
        should = "the overall line is yellow (50% is between the 50/80 default watermarks)"
        monkeypatch.setattr(cli_module, "collect_coverage", MagicMock(return_value=_report()))

        result = CliRunner().invoke(
            cli_module.cli, ["code-coverage", "local/SampleModel"], color=True
        )
        overall_line = next(line for line in result.output.splitlines() if "Overall:" in line)

        assert "[33m" in overall_line, f"{given}: {should}"


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

    def test_output_with_text_format_writes_json_and_prints_the_report(self, monkeypatch, tmp_path):
        # --output always writes the JSON report; the screen shows the --format report (text here).
        monkeypatch.setattr(cli_module, "collect_coverage", MagicMock(return_value=_report()))
        out_file = tmp_path / "coverage.json"

        result = CliRunner().invoke(cli_module.cli, ["code-coverage", "local/SampleModel", "-o", str(out_file)])

        assert result.exit_code == 0
        assert json.loads(out_file.read_text(encoding="utf-8"))["summary"]["covered"] == 1
        assert "Overall:" in result.output


class TestCodeCoverageMinThreshold:
    def test_min_coverage_below_actual_exits_non_zero(self, monkeypatch):
        monkeypatch.setattr(cli_module, "collect_coverage", MagicMock(return_value=_report()))

        result = CliRunner().invoke(
            cli_module.cli, ["code-coverage", "local/SampleModel", "--min-coverage", "90"]
        )

        assert result.exit_code == 1
        assert "below the required 90.0% threshold" in result.output

    def test_min_coverage_at_or_below_actual_exits_zero(self, monkeypatch):
        monkeypatch.setattr(cli_module, "collect_coverage", MagicMock(return_value=_report()))

        result = CliRunner().invoke(
            cli_module.cli, ["code-coverage", "local/SampleModel", "--min-coverage", "50"]
        )

        assert result.exit_code == 0
        assert "Required coverage of 50.0% reached. Total coverage: 50.0%" in result.output

    def test_pass_message_keeps_json_stdout_parseable(self, monkeypatch):
        given = "--format json on stdout with a met --min-coverage"
        should = "the pass message goes to stderr so stdout stays valid JSON"
        monkeypatch.setattr(cli_module, "collect_coverage", MagicMock(return_value=_report()))

        try:
            runner = CliRunner(mix_stderr=False)  # Click < 8.2
        except TypeError:
            runner = CliRunner()  # Click >= 8.2 always separates stderr
        result = runner.invoke(
            cli_module.cli,
            ["code-coverage", "local/SampleModel", "--format", "json", "--min-coverage", "50"],
        )

        assert result.exit_code == 0
        json.loads(result.stdout)
        assert "Required coverage of 50.0% reached" in result.stderr, f"{given}: {should}"

    def test_json_output_file_still_written_when_below_threshold(self, monkeypatch, tmp_path):
        given = "--format json --output with coverage below --min-coverage"
        should = "write the report and then exit 1, like pytest-cov reports before failing"
        monkeypatch.setattr(cli_module, "collect_coverage", MagicMock(return_value=_report()))
        out_file = tmp_path / "coverage.json"

        result = CliRunner().invoke(
            cli_module.cli,
            [
                "code-coverage", "local/SampleModel", "--format", "json",
                "--output", str(out_file), "--min-coverage", "90",
            ],
        )

        assert result.exit_code == 1, f"{given}: {should}"
        assert json.loads(out_file.read_text(encoding="utf-8"))["summary"]["percent"] == 50.0

    def test_malformed_min_coverage_fails_before_any_xmla_query(self, monkeypatch):
        spy = MagicMock(return_value=_report())
        monkeypatch.setattr(cli_module, "collect_coverage", spy)

        result = CliRunner().invoke(
            cli_module.cli, ["code-coverage", "local/SampleModel", "--min-coverage", "150"]
        )

        assert result.exit_code != 0
        spy.assert_not_called()

    def test_nan_min_coverage_fails_before_any_xmla_query(self, monkeypatch):
        given = "click.FloatRange(0, 100) alone accepts nan (comparisons against the bounds are false)"
        should = "an explicit finite-value check rejects it as a usage error, same as an out-of-range value"
        spy = MagicMock(return_value=_report())
        monkeypatch.setattr(cli_module, "collect_coverage", spy)

        result = CliRunner().invoke(
            cli_module.cli, ["code-coverage", "local/SampleModel", "--min-coverage", "nan"]
        )

        assert result.exit_code != 0, f"{given}: {should}"
        spy.assert_not_called()


class TestCodeCoverageNoConnection:
    def test_no_connection_reports_error_and_exits_non_zero(self, monkeypatch):
        monkeypatch.setattr(cli_module, "collect_coverage", MagicMock(return_value=None))

        result = CliRunner().invoke(cli_module.cli, ["code-coverage", "local/NoSuchModel"])

        assert result.exit_code != 0
        assert "No XMLA connection detected" in result.output

    def test_missing_filesystem_path_reports_clear_error(self, monkeypatch):
        given = "a filesystem MODEL_PATH that does not exist on disk"
        should = "report 'Model path not found', matching run-tests/retrieve-tests, not the generic no-connection message"
        spy = MagicMock(return_value=_report())
        monkeypatch.setattr(cli_module, "collect_coverage", spy)

        result = CliRunner().invoke(
            cli_module.cli, ["code-coverage", "./no/such/path.SemanticModel"]
        )

        assert result.exit_code != 0, f"{given}: {should}"
        assert "Model path not found" in result.output, f"{given}: {should}"
        spy.assert_not_called()
