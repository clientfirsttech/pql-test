"""
Text/JSON presentation for direct test-UDF coverage reports.

Pure functions over ``CoverageReport`` / ``ClassificationResult`` -- no
Click, no XMLA. Kept separate from ``coverage_collector.py`` so collection
stays uncoupled from presentation, and separate from ``cli.py`` so the
summary math and JSON shape are unit-testable without invoking the CLI.
"""

from __future__ import annotations

from dataclasses import dataclass

from pql_test.runner.coverage import CoverageObjectType
from pql_test.runner.coverage_collector import CoverageReport

__all__ = [
    "CoverageSummary",
    "category_counts",
    "coverage_report_to_dict",
    "summarize_coverage",
]


@dataclass(frozen=True)
class CoverageSummary:
    """Overall covered/eligible counts and percentage, excluded objects omitted."""

    covered: int
    eligible: int
    percent: float


def category_counts(
    report: CoverageReport,
) -> dict[CoverageObjectType, tuple[int, int]]:
    """Return ``{object_type: (covered_count, eligible_count)}`` for every category present."""
    covered: dict[CoverageObjectType, int] = {}
    eligible: dict[CoverageObjectType, int] = {}
    for evidence in report.result.covered:
        covered[evidence.object_type] = covered.get(evidence.object_type, 0) + 1
        eligible[evidence.object_type] = eligible.get(evidence.object_type, 0) + 1
    for gap in report.result.gaps:
        eligible[gap.object_type] = eligible.get(gap.object_type, 0) + 1
    all_types = sorted(set(covered) | set(eligible), key=lambda t: t.value)
    return {t: (covered.get(t, 0), eligible.get(t, 0)) for t in all_types}


def summarize_coverage(report: CoverageReport) -> CoverageSummary:
    """Overall covered/eligible/percent. A model with zero eligible objects reports 100%."""
    counts = category_counts(report)
    total_covered = sum(c for c, _ in counts.values())
    total_eligible = sum(e for _, e in counts.values())
    percent = (total_covered / total_eligible * 100) if total_eligible else 100.0
    return CoverageSummary(
        covered=total_covered, eligible=total_eligible, percent=round(percent, 2)
    )


def coverage_report_to_dict(report: CoverageReport) -> dict:
    """Stable JSON-able shape: summary, category counts, evidence, gaps, exclusions, unavailable."""
    summary = summarize_coverage(report)
    counts = category_counts(report)
    return {
        "model_path": report.model_path,
        "test_count": report.test_count,
        "summary": {
            "covered": summary.covered,
            "eligible": summary.eligible,
            "percent": summary.percent,
        },
        "categories": {
            object_type.value: {"covered": covered, "eligible": eligible}
            for object_type, (covered, eligible) in counts.items()
        },
        "evidence": [
            {
                "object_type": e.object_type.value,
                "identifier": e.identifier,
                "test_names": list(e.test_names),
            }
            for e in report.result.covered
        ],
        "gaps": [
            {
                "object_type": g.object_type.value,
                "identifier": g.identifier,
                "test_target_hint": g.test_target_hint,
            }
            for g in report.result.gaps
        ],
        "exclusions": [
            {
                "object_type": ex.object_type.value,
                "identifier": ex.identifier,
                "reason": ex.reason,
            }
            for ex in report.result.excluded
        ],
        "unavailable": [
            {"object_type": u.object_type.value, "reason": u.reason}
            for u in report.unavailable
        ],
    }
