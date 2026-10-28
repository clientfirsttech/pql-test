# SPDX-License-Identifier: AGPL-3.0-only
"""
Direct test-UDF coverage evidence model.

Defines the normalized shapes for coverage inventory, evidence, exclusions,
and AI-ready gap records, plus the pure ``classify_coverage`` rule that
turns (eligible objects, evidence, exclusions) into covered / gap /
excluded buckets.

This module has no XMLA dependency. See
tasks/direct-udf-code-coverage-metadata-contract.md for which object
categories have a direct ``INFO.CALCDEPENDENCY()`` edge (TABLE, CALC_COLUMN,
MEASURE) versus an indirect or nonexistent evidence path (RELATIONSHIP,
PARTITION, ROLE). "Implement Coverage Collection" is responsible for
querying the live model and building the ``EligibleObject`` /
``CoverageEvidence`` / ``ExclusionRecord`` inputs this module classifies.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

__all__ = [
    "ClassificationResult",
    "CoverageEvidence",
    "CoverageGap",
    "CoverageObjectType",
    "EligibleObject",
    "ExclusionRecord",
    "classify_coverage",
]


class CoverageObjectType(str, Enum):
    """Object categories requested by the code-coverage command."""

    TABLE = "TABLE"
    CALC_COLUMN = "CALC_COLUMN"
    MEASURE = "MEASURE"
    RELATIONSHIP = "RELATIONSHIP"
    PARTITION = "PARTITION"
    ROLE = "ROLE"


@dataclass(frozen=True)
class EligibleObject:
    """A model object in coverage scope, before evidence is applied."""

    object_type: CoverageObjectType
    identifier: str
    """Stable model identifier, e.g. 'MarvelFact[Name]' or 'MarvelFact'."""


@dataclass(frozen=True)
class CoverageEvidence:
    """Direct or attributable test-UDF evidence for one eligible object.

    For TABLE/CALC_COLUMN/MEASURE this must come from a direct
    ``INFO.CALCDEPENDENCY()`` edge from a discovered test UDF. For
    RELATIONSHIP/PARTITION/ROLE it must come from the explicit indirect
    evidence paths documented in the metadata contract (DAX expression-text
    parsing, or the ``PQLAssert_RoleName`` -> ``ROWS_ALLOWED`` join) --
    never from transitive dependency inference.
    """

    object_type: CoverageObjectType
    identifier: str
    test_names: tuple[str, ...]
    """Discovered test-UDF names that produced this evidence."""


@dataclass(frozen=True)
class ExclusionRecord:
    """An eligible object removed from coverage scope by policy.

    Retains its identifier and reason without counting toward covered or
    uncovered totals.
    """

    object_type: CoverageObjectType
    identifier: str
    reason: str


@dataclass(frozen=True)
class CoverageGap:
    """An eligible, non-excluded object with no test-UDF evidence."""

    object_type: CoverageObjectType
    identifier: str
    test_target_hint: str
    """AI-ready hint describing what test to add."""


@dataclass(frozen=True)
class ClassificationResult:
    """The output of classify_coverage: three disjoint buckets."""

    covered: tuple[CoverageEvidence, ...]
    gaps: tuple[CoverageGap, ...]
    excluded: tuple[ExclusionRecord, ...]


def _default_test_target_hint(object_type: CoverageObjectType, identifier: str) -> str:
    return f"Add a PQL.Assert test asserting on {object_type.value} {identifier}"


def classify_coverage(
    eligible: list[EligibleObject],
    evidence: list[CoverageEvidence],
    exclusions: list[ExclusionRecord],
) -> ClassificationResult:
    """Classify each eligible object as covered, a gap, or excluded.

    Exclusion takes priority over evidence: an excluded object is retained
    in ``excluded`` and never appears in ``covered`` or ``gaps``, even when
    evidence exists for it. Evidence keyed to an identifier outside the
    eligible inventory is ignored. Evidence with no contributing test names
    does not count as coverage.
    """
    evidence_by_key = {(e.object_type, e.identifier): e for e in evidence}
    excluded_keys = {(e.object_type, e.identifier) for e in exclusions}

    covered: list[CoverageEvidence] = []
    gaps: list[CoverageGap] = []

    for obj in eligible:
        key = (obj.object_type, obj.identifier)
        if key in excluded_keys:
            continue
        found = evidence_by_key.get(key)
        if found is not None and found.test_names:
            covered.append(found)
        else:
            gaps.append(
                CoverageGap(
                    object_type=obj.object_type,
                    identifier=obj.identifier,
                    test_target_hint=_default_test_target_hint(
                        obj.object_type, obj.identifier
                    ),
                )
            )

    return ClassificationResult(
        covered=tuple(covered),
        gaps=tuple(gaps),
        excluded=tuple(exclusions),
    )
