# SPDX-License-Identifier: AGPL-3.0-only
"""
Test execution - run DAX test suites and summarize results.

This module provides functions to:
- Execute single test suites with optional RLS/OLS impersonation
- Run multiple tests and collect results
- High-level run_tests_from_model() helper with discovery + execution
"""

from __future__ import annotations

import time
from dataclasses import replace as _dc_replace
from typing import TYPE_CHECKING, Optional

from pql_test.runner.discovery import retrieve_test_by_name, retrieve_tests
from pql_test.runner.models import (
    PqlTest,
    ResolvedXmlaConnection,
    TestResult,
    TestSuite,
    XmlaConnectionOptions,
)
from pql_test.runner.resolver import resolve_xmla_connection

if TYPE_CHECKING:
    from pql_test import runner
    from pql_test.runner.xmla import _execute_dax_query, _get_col
else:
    # Import at runtime through runner package to enable test mocking
    from pql_test import runner
    _execute_dax_query = lambda *args: runner._execute_dax_query(*args)
    _get_col = lambda *args: runner._get_col(*args)

__all__ = [
    "run_test",
    "run_tests",
    "run_tests_from_model",
]

_DEFAULT_SKIP_MESSAGE = (
    "No XMLA connection available. "
    "Open the model in Power BI Desktop or supply "
    "--tenant-id, --workspace-id, and --dataset-id."
)


def run_test(
    test: PqlTest,
    connection: Optional[ResolvedXmlaConnection] = None,
    skip_message: str = _DEFAULT_SKIP_MESSAGE,
) -> list[TestResult]:
    """
    Execute a single DAX test suite via ADOMD.NET / XMLA.

    Returns one TestResult per assertion row in the EVALUATE result set.
    When no connection is available a single failed/skipped result is
    returned so callers can still report the suite without throwing.
    """
    start = time.monotonic()

    if not connection:
        return [
            TestResult(
                test_name=test.name,
                passed=False,
                skipped=True,
                message=skip_message,
                duration_ms=(time.monotonic() - start) * 1000.0,
                suite_name=test.name,
            )
        ]

    # When the test declares RLS/OLS metadata (from RetrieveTestsV2), create
    # a per-test connection that applies the correct impersonation.
    #
    # Roles= is preferred over EffectiveUserName= whenever a role_name is
    # available, regardless of whether the connection is local or service:
    #   • Local AS doesn't accept AAD UPNs for EffectiveUserName.
    #   • Service principals can NEVER use EffectiveUserName= against the
    #     Power BI XMLA endpoint (Microsoft enforces this even for workspace
    #     admins — the resulting error message misleadingly says "not a
    #     workspace administrator").  Roles= works because the SPN can be
    #     granted role membership in the dataset.
    # EffectiveUserName= is still used as a fallback for service connections
    # that only carry an impersonated_user_name annotation — that path
    # requires the calling identity to be a real user that's a workspace
    # admin (i.e. not a service principal).
    effective_connection = connection
    if connection:
        _is_local = connection.server.lower().startswith("localhost:")
        if test.role_name:
            effective_connection = _dc_replace(connection, roles=test.role_name)
        elif not _is_local and test.impersonated_user_name:
            effective_connection = _dc_replace(
                connection, effective_user_name=test.impersonated_user_name
            )

    try:
        rows = _execute_dax_query(effective_connection, test.source)

        if not rows:
            return [
                TestResult(
                    test_name=test.name,
                    passed=False,
                    message=(
                        "Query returned no rows — "
                        "ensure the EVALUATE expression is correct."
                    ),
                    duration_ms=(time.monotonic() - start) * 1000.0,
                    suite_name=test.name,
                )
            ]

        results: list[TestResult] = []
        for row in rows:
            row_test_name = _get_col(row, "TestName") or test.name
            passed_val = _get_col(row, "Passed").lower()
            passed = passed_val in ("true", "1")
            row_expected = _get_col(row, "Expected")
            row_actual = _get_col(row, "Actual")
            rule_desc = _get_col(row, "RuleDescription")

            parts = [f"Expected: {row_expected}", f"Actual: {row_actual}"]
            if rule_desc:
                parts.append(f"Rule: {rule_desc}")

            results.append(
                TestResult(
                    test_name=row_test_name,
                    passed=passed,
                    message=" | ".join(parts),
                    actual=row_actual,
                    expected=row_expected,
                    suite_name=test.name,
                    duration_ms=(time.monotonic() - start) * 1000.0,
                )
            )
        return results

    except Exception as exc:  # noqa: BLE001
        return [
            TestResult(
                test_name=test.name,
                passed=False,
                message="Test execution failed",
                error=str(exc),
                duration_ms=(time.monotonic() - start) * 1000.0,
                suite_name=test.name,
            )
        ]


def run_tests(
    tests: list[PqlTest],
    connection: Optional[ResolvedXmlaConnection] = None,
    skip_message: str = _DEFAULT_SKIP_MESSAGE,
) -> list[TestResult]:
    """Execute all DAX test suites and return the flat list of assertion results."""
    results: list[TestResult] = []
    for t in tests:
        results.extend(run_test(t, connection, skip_message=skip_message))
    return results


def run_tests_from_model(
    model_path: str,
    test_name: Optional[str] = None,
    conn_opts: Optional[XmlaConnectionOptions] = None,
    connection: Optional[ResolvedXmlaConnection] = None,
    skip_message: str = _DEFAULT_SKIP_MESSAGE,
    environment: Optional[str] = None,
    *,
    connection_pre_resolved: bool = False,
) -> TestSuite:
    """
    High-level helper: discover tests, optionally filter, execute, and summarise.

    Parameters
    ----------
    model_path:
        Root directory of the PBIP model.
    test_name:
        Optional. When supplied only that test suite is executed.
    conn_opts:
        XMLA connection options. Defaults to local auto-detection only.
    environment:
        Optional environment name (e.g. ``DEV``, ``PROD``, ``ANY``, ``BKUP``).
        When supplied, only suites targeting that environment are discovered
        and executed (see :func:`retrieve_tests`).
    connection_pre_resolved:
        Keyword-only.  When ``True`` the caller asserts that *connection*
        already reflects a completed resolution attempt (including a
        deliberate ``None`` for the miss case), so the helper must not
        re-run ``resolve_xmla_connection`` — that redundant call caused
        the local Power BI Desktop scan to run twice per invocation.

    Returns
    -------
    TestSuite with discovery info and execution results.
    """
    if conn_opts is None:
        conn_opts = XmlaConnectionOptions()

    if connection is None and not connection_pre_resolved:
        # Route through the runner package so tests can patch
        # ``pql_test.runner.resolve_xmla_connection``.
        connection = runner.resolve_xmla_connection(model_path, conn_opts)

    if test_name:
        found = runner.retrieve_test_by_name(
            model_path, test_name, connection=connection, environment=environment
        )
        tests: list[PqlTest] = [found] if found else []
    else:
        tests = runner.retrieve_tests(model_path, connection=connection, environment=environment)
    results = run_tests(tests, connection, skip_message=skip_message)
    passed = sum(1 for r in results if r.passed)
    skipped = sum(1 for r in results if r.skipped)
    failed = sum(1 for r in results if not r.passed and not r.skipped)

    return TestSuite(
        model_path=model_path,
        tests=tests,
        results=results,
        passed=passed,
        failed=failed,
        skipped=skipped,
        total=len(results),
    )
