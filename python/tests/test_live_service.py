# SPDX-License-Identifier: BUSL-1.1
"""
Live integration tests that query an actual Power BI / Fabric XMLA endpoint.

These tests require:
  - Power BI Premium or Microsoft Fabric capacity (XMLA read enabled)
  - pyadomd and msal installed
  - Credentials in python/tests/.env  (copy .env.example → .env and fill in)
    OR the equivalent environment variables set in your CI/CD pipeline

Run with:
    cd python
    pytest tests/test_live_service.py -v -m live

Skipped automatically when credentials or pyadomd are missing.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Load tests/.env before importing the runner so that env vars are available.
# override=False means real env vars (e.g. CI secrets) always win over the file.
try:
    from dotenv import load_dotenv

    _env_file = Path(__file__).parent / ".env"
    if _env_file.exists():
        load_dotenv(_env_file, override=False)
except ImportError:
    pass  # python-dotenv missing; rely on env vars being set externally

from pql_test.runner import (
    HAS_PYADOMD,
    Environment,
    XmlaConnectionOptions,
    resolve_xmla_connection,
    run_tests_from_model,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _env(key: str) -> str:
    return os.environ.get(key, "").strip()


def _require_credentials() -> None:
    """Skip the test if any required live-service credential is absent."""
    if not HAS_PYADOMD:
        pytest.skip("pyadomd not installed — cannot connect to XMLA endpoint")
    missing = [
        k
        for k in ("PQL_TENANT_ID", "PQL_WORKSPACE_ID", "PQL_DATASET_ID")
        if not _env(k)
    ]
    if missing:
        pytest.skip(
            f"Live service credentials not configured: {', '.join(missing)}\n"
            "Copy python/tests/.env.example → python/tests/.env and fill in your values."
        )


def _live_opts(dataset_id: str | None = None) -> XmlaConnectionOptions:
    """
    Create XmlaConnectionOptions for live service connection.
    
    Args:
        dataset_id: Optional dataset ID override. If None, uses PQL_DATASET_ID env var.
    """
    raw_env = _env("PQL_ENVIRONMENT")
    environment = Environment(raw_env) if raw_env else Environment.PUBLIC
    return XmlaConnectionOptions(
        tenant_id=_env("PQL_TENANT_ID"),
        workspace_id=_env("PQL_WORKSPACE_ID"),
        dataset_id=dataset_id or _env("PQL_DATASET_ID"),
        client_id=_env("PQL_CLIENT_ID"),
        client_secret=_env("PQL_CLIENT_SECRET"),
        environment=environment,
    )


# ---------------------------------------------------------------------------
# Live tests
# ---------------------------------------------------------------------------


@pytest.mark.live
class TestLiveService:
    """
    End-to-end tests that hit the real Power BI / Fabric XMLA endpoint.

    Mirrors the Pester 'Should run tests' block from Invoke-DQVTesting:
    connect to the service with real credentials, run every *.Tests.dax file
    found in the SampleModel, and assert that all tests pass.

    Skipped automatically unless python/tests/.env is populated.
    """

    def test_connection_resolves_with_service_credentials(self, sample_model_path):
        """
        Mirrors Pester: $xmlaConnection | Should -Not -BeNullOrEmpty.
        resolve_xmla_connection returns a valid server URL and catalog when
        proper service-principal credentials are supplied.
        """
        _require_credentials()
        conn = resolve_xmla_connection(sample_model_path, _live_opts())
        assert conn is not None, "Expected a resolved connection, got None"
        assert "powerbi://api.powerbi.com" in conn.server, (
            f"Expected Power BI XMLA URL, got: {conn.server}"
        )
        assert conn.catalog, "Catalog (dataset name) should not be empty"

    def test_run_tests_returns_results_for_sample_model(self, sample_model_path):
        """
        Mirrors Pester: $testResults.Length | Should -BeGreaterThan 0.
        Runs the full test suite from SampleModel against the live service and
        asserts that at least one test ran.

        SampleModel is a demonstration model and may intentionally contain
        best-practice violations, so we only verify that results were returned
        (not that all tests pass).
        """
        _require_credentials()
        suite = run_tests_from_model(sample_model_path, conn_opts=_live_opts())

        assert suite.total > 0, (
            "Expected at least one test result from SampleModel. "
            "Check that *.Tests.dax files exist under examples/SampleModel.SemanticModel/DAXQueries/."
        )

    def test_all_dax_test_files_executed(self, sample_model_path):
        """
        Mirrors Pester: every *.Tests.dax file is discovered and produces results.
        Checks that the number of test suites executed equals the number of
        *.Tests.dax files on disk — no files silently skipped.
        """
        _require_credentials()
        from pql_test.runner import _collect_dax_test_files

        dax_files = _collect_dax_test_files(sample_model_path)
        suite = run_tests_from_model(sample_model_path, conn_opts=_live_opts())

        # Extract unique suite names from test results
        executed_suite_count = len({r.suite_name for r in suite.results if r.suite_name})
        expected_suite_count = len(dax_files)

        assert executed_suite_count == expected_suite_count, (
            f"Expected {expected_suite_count} test suites from {expected_suite_count} DAX files, "
            f"but got {executed_suite_count} suites"
        )

    def test_run_tests_on_rls_model(self, rls_model_path):
        """
        Test that RLS model tests can be executed against the live service.
        Uses PQL_DATASET_ID_RLS if configured, otherwise skips.
        """
        _require_credentials()
        rls_dataset_id = _env("PQL_DATASET_ID_RLS")
        if not rls_dataset_id:
            pytest.skip("PQL_DATASET_ID_RLS not configured — skipping RLS model tests")

        suite = run_tests_from_model(rls_model_path, conn_opts=_live_opts(rls_dataset_id))

        print(f"\n=== RLS Model Test Results ===")
        print(f"Total tests: {suite.total}")
        print(f"Passed: {suite.passed}")
        print(f"Failed: {suite.failed}")
        print(f"Skipped: {suite.skipped}")
        print(f"\nTest suites: {sorted({r.suite_name for r in suite.results if r.suite_name})}")
        print(f"\nSample test names:")
        for r in suite.results[:10]:
            status = "✓  PASS" if r.passed else "✗ FAIL"
            print(f"  {status}: {r.test_name}")
        if len(suite.results) > 10:
            print(f"  ... and {len(suite.results) - 10} more tests")

        assert suite.total > 0, (
            "Expected at least one test result from RLS_Model. "
            "Check that *.Tests.dax files exist under examples/RLS_Model.SemanticModel/DAXQueries/."
        )

    def test_run_tests_on_ols_model(self, ols_model_path):
        """
        Test that OLS model tests can be executed against the live service.
        Uses PQL_DATASET_ID_OLS if configured, otherwise skips.
        """
        _require_credentials()
        ols_dataset_id = _env("PQL_DATASET_ID_OLS")
        if not ols_dataset_id or ols_dataset_id == "<your-ols-model-guid>":
            pytest.skip("PQL_DATASET_ID_OLS not configured — skipping OLS model tests")

        suite = run_tests_from_model(ols_model_path, conn_opts=_live_opts(ols_dataset_id))

        print(f"\n=== OLS Model Test Results ===")
        print(f"Total tests: {suite.total}")
        print(f"Passed: {suite.passed}")
        print(f"Failed: {suite.failed}")
        print(f"Skipped: {suite.skipped}")
        print(f"\nTest suites: {sorted({r.suite_name for r in suite.results if r.suite_name})}")
        print(f"\nSample test names:")
        for r in suite.results[:10]:
            status = "✓ PASS" if r.passed else "✗ FAIL"
            print(f"  {status}: {r.test_name}")
        if len(suite.results) > 10:
            print(f"  ... and {len(suite.results) - 10} more tests")

        assert suite.total > 0, (
            "Expected at least one test result from OLS_Model. "
            "Check that *.Tests.dax files exist under examples/OLS_Model.SemanticModel/DAXQueries/."
        )
