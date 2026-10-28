# SPDX-License-Identifier: AGPL-3.0-only
"""
Live integration test pinning direct test-UDF coverage evidence for
SampleModel against tasks/direct-udf-code-coverage-metadata-contract.md.

Requires the same python/tests/.env service-principal credentials as
test_live_service.py. Skipped automatically when they aren't configured.

Run with:
    cd python
    pytest tests/test_coverage_live.py -v -m live
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

try:
    from dotenv import load_dotenv

    _env_file = Path(__file__).parent / ".env"
    if _env_file.exists():
        load_dotenv(_env_file, override=False)
except ImportError:
    pass

from pql_test.runner import HAS_PYADOMD, Environment, XmlaConnectionOptions
from pql_test.runner.coverage import CoverageObjectType
from pql_test.runner.coverage_collector import collect_coverage


def _env(key: str) -> str:
    return os.environ.get(key, "").strip()


def _require_credentials() -> None:
    if not HAS_PYADOMD:
        pytest.skip("pyadomd not installed — cannot connect to XMLA endpoint")
    missing = [
        k for k in ("PQL_TENANT_ID", "PQL_WORKSPACE_ID", "PQL_DATASET_ID") if not _env(k)
    ]
    if missing:
        pytest.skip(
            f"Live service credentials not configured: {', '.join(missing)}\n"
            "Copy python/tests/.env.example → python/tests/.env and fill in your values."
        )


def _live_opts() -> XmlaConnectionOptions:
    raw_env = _env("PQL_ENVIRONMENT")
    environment = Environment(raw_env) if raw_env else Environment.PUBLIC
    return XmlaConnectionOptions(
        tenant_id=_env("PQL_TENANT_ID"),
        workspace_id=_env("PQL_WORKSPACE_ID"),
        dataset_id=_env("PQL_DATASET_ID"),
        client_id=_env("PQL_CLIENT_ID"),
        client_secret=_env("PQL_CLIENT_SECRET"),
        environment=environment,
    )


@pytest.mark.live
class TestSampleModelCoverageMatchesMetadataContract:
    """
    Pins the live evidence recorded in
    tasks/direct-udf-code-coverage-metadata-contract.md so a future change
    to INFO.CALCDEPENDENCY()'s shape, PQL.Assert's function names, or the
    collector's parsing is caught immediately rather than silently drifting.
    """

    def test_marvelfact_table_is_covered_via_direct_calcdependency_edge(
        self, sample_model_path
    ):
        _require_credentials()
        report = collect_coverage(sample_model_path, conn_opts=_live_opts())

        assert report is not None
        covered = {
            (e.object_type, e.identifier): e.test_names for e in report.result.covered
        }
        assert (CoverageObjectType.TABLE, "MarvelFact") in covered

    def test_number_of_characters_measure_is_covered_by_calcs_dev_tests(
        self, sample_model_path
    ):
        _require_credentials()
        report = collect_coverage(sample_model_path, conn_opts=_live_opts())

        covered = {
            (e.object_type, e.identifier): e.test_names for e in report.result.covered
        }
        key = (CoverageObjectType.MEASURE, "MarvelFact[Number of Characters]")
        assert key in covered
        assert "Calcs.DEV.Tests" in covered[key]

    def test_marvelfact_datedim_relationship_is_covered_via_parsed_expression(
        self, sample_model_path
    ):
        """Regression guard for the indirect (non-CALCDEPENDENCY) relationship
        evidence path documented in the metadata contract: parsing
        PQL.Assert.Relationship.ShouldExist(...) out of the test UDF's own
        DAX expression text."""
        _require_credentials()
        report = collect_coverage(sample_model_path, conn_opts=_live_opts())

        covered = {
            (e.object_type, e.identifier): e.test_names for e in report.result.covered
        }
        key = (CoverageObjectType.RELATIONSHIP, "MarvelFact[DateID]->DateDim[DateID]")
        assert key in covered
        assert "Schema.DEV.Tests" in covered[key]

    def test_partitions_are_always_excluded_never_covered_or_a_gap(
        self, sample_model_path
    ):
        """Regression guard for the metadata contract's partition-exclusion
        decision: no PQL.Assert helper targets partitions, so live evidence
        must never show a partition as covered or as a gap."""
        _require_credentials()
        report = collect_coverage(sample_model_path, conn_opts=_live_opts())

        assert not any(
            e.object_type == CoverageObjectType.PARTITION for e in report.result.covered
        )
        assert not any(
            g.object_type == CoverageObjectType.PARTITION for g in report.result.gaps
        )
        assert any(
            ex.object_type == CoverageObjectType.PARTITION for ex in report.result.excluded
        )

    def test_no_category_is_reported_unavailable_against_a_healthy_connection(
        self, sample_model_path
    ):
        _require_credentials()
        report = collect_coverage(sample_model_path, conn_opts=_live_opts())

        assert report.unavailable == ()
        assert report.test_count >= 4
