"""
Unit tests for [python/pql_test/runner/coverage.py](../pql_test/runner/coverage.py).

Exercises the normalized coverage evidence shapes and the pure
classify_coverage() rule against synthetic inventory/evidence/exclusion
data. No XMLA connection involved -- see
tasks/direct-udf-code-coverage-metadata-contract.md for the live-model
evidence this contract is built from, and the "Implement Coverage
Collection" task for the XMLA-backed collector that will produce these
inputs from a real model.
"""

from __future__ import annotations

from pql_test.runner.coverage import (
    CoverageEvidence,
    CoverageGap,
    CoverageObjectType,
    EligibleObject,
    ExclusionRecord,
    classify_coverage,
)


class TestClassifyCoverage:
    def test_given_direct_evidence_for_a_table_should_mark_it_covered(self):
        eligible = [EligibleObject(CoverageObjectType.TABLE, "MarvelFact")]
        evidence = [
            CoverageEvidence(
                CoverageObjectType.TABLE, "MarvelFact", ("DataQuality.DEV.Tests",)
            )
        ]

        result = classify_coverage(eligible, evidence, exclusions=[])

        assert result.covered == tuple(evidence)
        assert result.gaps == ()
        assert result.excluded == ()

    def test_given_a_measure_with_no_evidence_should_produce_an_uncovered_gap(self):
        eligible = [
            EligibleObject(CoverageObjectType.MEASURE, "MarvelFact[Number of Characters]")
        ]

        result = classify_coverage(eligible, evidence=[], exclusions=[])

        assert result.covered == ()
        assert result.excluded == ()
        assert len(result.gaps) == 1
        gap = result.gaps[0]
        assert gap.object_type == CoverageObjectType.MEASURE
        assert gap.identifier == "MarvelFact[Number of Characters]"
        assert "MarvelFact[Number of Characters]" in gap.test_target_hint

    def test_given_an_excluded_object_should_retain_reason_and_omit_from_covered_and_gaps(
        self,
    ):
        eligible = [EligibleObject(CoverageObjectType.PARTITION, "MarvelFact-partition-0")]
        exclusions = [
            ExclusionRecord(
                CoverageObjectType.PARTITION,
                "MarvelFact-partition-0",
                "no PQL.Assert helper targets partitions",
            )
        ]

        result = classify_coverage(eligible, evidence=[], exclusions=exclusions)

        assert result.covered == ()
        assert result.gaps == ()
        assert result.excluded == tuple(exclusions)

    def test_given_an_object_with_both_evidence_and_an_exclusion_should_still_exclude_it(
        self,
    ):
        eligible = [EligibleObject(CoverageObjectType.ROLE, "West")]
        evidence = [CoverageEvidence(CoverageObjectType.ROLE, "West", ("RLS.ANY.Tests",))]
        exclusions = [
            ExclusionRecord(
                CoverageObjectType.ROLE, "West", "role coverage policy disabled for this run"
            )
        ]

        result = classify_coverage(eligible, evidence, exclusions)

        assert result.covered == ()
        assert result.gaps == ()
        assert result.excluded == tuple(exclusions)

    def test_given_evidence_for_an_identifier_outside_the_eligible_inventory_should_ignore_it(
        self,
    ):
        eligible = [EligibleObject(CoverageObjectType.TABLE, "MarvelFact")]
        evidence = [
            CoverageEvidence(CoverageObjectType.TABLE, "SomeOtherTable", ("Calcs.DEV.Tests",))
        ]

        result = classify_coverage(eligible, evidence, exclusions=[])

        assert result.covered == ()
        assert len(result.gaps) == 1
        assert result.gaps[0].identifier == "MarvelFact"

    def test_given_evidence_with_no_contributing_test_names_should_not_count_as_covered(
        self,
    ):
        eligible = [EligibleObject(CoverageObjectType.CALC_COLUMN, "DateDim[Month Year]")]
        evidence = [CoverageEvidence(CoverageObjectType.CALC_COLUMN, "DateDim[Month Year]", ())]

        result = classify_coverage(eligible, evidence, exclusions=[])

        assert result.covered == ()
        assert len(result.gaps) == 1

    def test_given_a_relationship_or_role_with_attributable_evidence_should_mark_it_covered(
        self,
    ):
        eligible = [
            EligibleObject(
                CoverageObjectType.RELATIONSHIP,
                "MarvelFact[DateID]->DateDim[DateID]",
            ),
            EligibleObject(CoverageObjectType.ROLE, "West"),
        ]
        evidence = [
            CoverageEvidence(
                CoverageObjectType.RELATIONSHIP,
                "MarvelFact[DateID]->DateDim[DateID]",
                ("Schema.DEV.Tests",),
            ),
            CoverageEvidence(CoverageObjectType.ROLE, "West", ("RLS.ANY.Tests",)),
        ]

        result = classify_coverage(eligible, evidence, exclusions=[])

        assert {e.identifier for e in result.covered} == {
            "MarvelFact[DateID]->DateDim[DateID]",
            "West",
        }
        assert result.gaps == ()


class TestCoverageGapHint:
    def test_test_target_hint_names_the_object_type_and_identifier(self):
        eligible = [EligibleObject(CoverageObjectType.RELATIONSHIP, "A[X]->B[Y]")]

        result = classify_coverage(eligible, evidence=[], exclusions=[])

        gap = result.gaps[0]
        assert isinstance(gap, CoverageGap)
        assert "RELATIONSHIP" in gap.test_target_hint
        assert "A[X]->B[Y]" in gap.test_target_hint
