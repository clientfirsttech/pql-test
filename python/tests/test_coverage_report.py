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
    coverage_report_to_dict,
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
