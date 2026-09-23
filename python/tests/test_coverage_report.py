"""
Unit tests for [python/pql_test/runner/coverage_report.py](../pql_test/runner/coverage_report.py).

Pure summarization/serialization tests against synthetic CoverageReport
data -- no Click, no XMLA.
"""

from __future__ import annotations

import json

from pql_test.runner.coverage import (
    ClassificationResult,
    CoverageEvidence,
    CoverageGap,
    CoverageObjectType,
    ExclusionRecord,
)
from pql_test.runner.coverage_collector import CoverageReport, UnavailableCategory
from pql_test.runner.coverage_report import (
    category_counts,
    coverage_percent,
    coverage_report_to_dict,
    coverage_status,
    summarize_coverage,
)


def _report(covered=(), gaps=(), excluded=(), unavailable=(), test_count=0):
    return CoverageReport(
        model_path="local/SampleModel",
        test_count=test_count,
        result=ClassificationResult(covered=tuple(covered), gaps=tuple(gaps), excluded=tuple(excluded)),
        unavailable=tuple(unavailable),
    )


class TestSummarizeCoverage:
    def test_given_a_mix_of_covered_and_gap_objects_should_compute_the_overall_percentage(self):
        report = _report(
            covered=[CoverageEvidence(CoverageObjectType.TABLE, "MarvelFact", ("T1",))],
            gaps=[CoverageGap(CoverageObjectType.MEASURE, "MarvelFact[X]", "hint")],
        )

        summary = summarize_coverage(report)

        assert summary.covered == 1
        assert summary.eligible == 2
        assert summary.percent == 50.0

    def test_given_zero_eligible_objects_should_report_100_percent(self):
        report = _report()

        summary = summarize_coverage(report)

        assert summary.eligible == 0
        assert summary.percent == 100.0

    def test_excluded_objects_never_count_toward_eligible(self):
        report = _report(
            covered=[CoverageEvidence(CoverageObjectType.TABLE, "MarvelFact", ("T1",))],
            excluded=[ExclusionRecord(CoverageObjectType.PARTITION, "P1", "no assertion surface")],
        )

        summary = summarize_coverage(report)

        assert summary.covered == 1
        assert summary.eligible == 1


class TestCategoryCounts:
    def test_groups_covered_and_gap_counts_per_object_type(self):
        report = _report(
            covered=[
                CoverageEvidence(CoverageObjectType.TABLE, "MarvelFact", ("T1",)),
                CoverageEvidence(CoverageObjectType.TABLE, "DateDim", ("T1",)),
            ],
            gaps=[
                CoverageGap(CoverageObjectType.TABLE, "EyeColorDim", "hint"),
                CoverageGap(CoverageObjectType.MEASURE, "MarvelFact[X]", "hint"),
            ],
        )

        counts = category_counts(report)

        assert counts[CoverageObjectType.TABLE] == (2, 3)
        assert counts[CoverageObjectType.MEASURE] == (0, 1)


class TestCoverageReportToDict:
    def test_includes_every_required_top_level_section(self):
        report = _report(
            covered=[CoverageEvidence(CoverageObjectType.TABLE, "MarvelFact", ("T1", "T2"))],
            gaps=[CoverageGap(CoverageObjectType.MEASURE, "MarvelFact[X]", "Add a test")],
            excluded=[ExclusionRecord(CoverageObjectType.PARTITION, "P1", "no assertion surface")],
            unavailable=[UnavailableCategory(CoverageObjectType.RELATIONSHIP, "query failed")],
            test_count=2,
        )

        payload = coverage_report_to_dict(report)

        for key in ("model_path", "test_count", "summary", "categories", "evidence", "gaps", "exclusions", "unavailable"):
            assert key in payload
        assert payload["evidence"][0]["test_names"] == ["T1", "T2"]
        assert payload["gaps"][0]["test_target_hint"] == "Add a test"
        assert payload["exclusions"][0]["reason"] == "no assertion surface"
        assert payload["unavailable"][0] == {
            "object_type": "RELATIONSHIP",
            "reason": "query failed",
        }

    def test_is_json_serializable(self):
        report = _report(
            covered=[CoverageEvidence(CoverageObjectType.TABLE, "MarvelFact", ("T1",))],
        )

        json.dumps(coverage_report_to_dict(report))  # must not raise


class TestCoveragePercent:
    def test_given_zero_eligible_objects_should_report_100(self):
        assert coverage_percent(0, 0) == 100.0

    def test_given_full_coverage_should_report_100(self):
        assert coverage_percent(7, 7) == 100.0

    def test_given_a_gap_that_would_round_to_100_should_report_99_99(self):
        given = "99,999 of 100,000 eligible objects covered (99.999%, rounds to 100.0)"
        should = "report 99.99% so --min-coverage 100 still fails, like coverage.py"
        assert coverage_percent(99_999, 100_000) == 99.99, f"{given}: {should}"

    def test_rounds_to_two_decimals(self):
        assert coverage_percent(2, 3) == 66.67


class TestCoverageStatus:
    def test_without_threshold_uses_default_watermarks(self):
        given = "no --min-coverage threshold"
        should = "grade with Istanbul/Jest default watermarks: <50 FAIL, 50-<80 SKIP, >=80 PASS"
        assert coverage_status(0.0) == "FAIL", f"{given}: {should}"
        assert coverage_status(49.99) == "FAIL", f"{given}: {should}"
        assert coverage_status(50.0) == "SKIP", f"{given}: {should}"
        assert coverage_status(79.99) == "SKIP", f"{given}: {should}"
        assert coverage_status(80.0) == "PASS", f"{given}: {should}"
        assert coverage_status(100.0) == "PASS", f"{given}: {should}"

    def test_with_threshold_is_binary_and_matches_the_exit_code(self):
        given = "a --min-coverage threshold of 60"
        should = "PASS at/above the threshold, FAIL below -- no yellow band"
        assert coverage_status(59.99, 60) == "FAIL", f"{given}: {should}"
        assert coverage_status(60.0, 60) == "PASS", f"{given}: {should}"
        assert coverage_status(30.0, 20) == "PASS", f"{given}: {should}"

    def test_with_zero_threshold_everything_passes(self):
        assert coverage_status(0.0, 0) == "PASS"
