# SPDX-License-Identifier: AGPL-3.0-only
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
    "DEFAULT_WATERMARKS",
    "CoverageSummary",
    "category_counts",
    "coverage_percent",
    "coverage_report_to_dict",
    "coverage_status",
    "summarize_coverage",
]

# (low, high) watermarks used to grade a percentage when no --min-coverage
# threshold is set -- the same defaults Istanbul/nyc/Jest use: below 50% is
# FAIL (red), 50% up to 80% is SKIP (yellow), 80% and above is PASS (green).
DEFAULT_WATERMARKS = (50.0, 80.0)


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


def coverage_percent(covered: int, eligible: int, *, data_unavailable: bool = False) -> float:
    """Percentage rounded to 2 decimals; zero eligible objects reports 100%.

    Like coverage.py's ``fail_under`` handling, the rounded value is what gets
    displayed *and* compared against ``--min-coverage``, but a percentage
    only rounds to 100 when every eligible object is covered -- 99,999 of
    100,000 reports 99.99%, not 100.0%, so ``--min-coverage 100`` still fails.

    ``data_unavailable=True`` means zero eligible objects is NOT a genuinely
    empty model -- every category was dropped from scope because its XMLA
    metadata source failed, not because nothing exists to cover. Reporting
    that as 100% would let ``--min-coverage 100`` pass on a report that
    collected no evidence at all, so this returns 0.0 instead.
    """
    if not eligible:
        return 0.0 if data_unavailable else 100.0
    percent = round(covered / eligible * 100, 2)
    if percent >= 100 and covered < eligible:
        return 99.99
    return percent


def coverage_status(percent: float, min_coverage: float | None = None) -> str:
    """Grade *percent* as a ``STATUS_COLORS`` key: ``"PASS"``, ``"SKIP"``, or ``"FAIL"``.

    With a ``--min-coverage`` threshold the grade is binary and matches the
    exit code: at/above the threshold is PASS, below is FAIL. Without one,
    ``DEFAULT_WATERMARKS`` grade it: below low is FAIL, below high is SKIP
    (partial), otherwise PASS.
    """
    if min_coverage is not None:
        return "PASS" if percent >= min_coverage else "FAIL"
    low, high = DEFAULT_WATERMARKS
    if percent < low:
        return "FAIL"
    if percent < high:
        return "SKIP"
    return "PASS"


def summarize_coverage(report: CoverageReport) -> CoverageSummary:
    """Overall covered/eligible/percent. A model with zero eligible objects reports 100%
    -- unless every category was dropped because its metadata source was unavailable,
    in which case zero eligible is unknown data, not "nothing to cover", and reports 0%.
    """
    counts = category_counts(report)
    total_covered = sum(c for c, _ in counts.values())
    total_eligible = sum(e for _, e in counts.values())
    return CoverageSummary(
        covered=total_covered,
        eligible=total_eligible,
        percent=coverage_percent(
            total_covered, total_eligible, data_unavailable=bool(report.unavailable)
        ),
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
