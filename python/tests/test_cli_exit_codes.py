# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for `pql-test run-tests` exit-code semantics.

The CLI's exit code is what CI uses to mark a matrix job as green/red.
Today it only goes non-zero on hard test failures, which means
"discovered tests but couldn't run any" silently succeeds — e.g. a CI
matrix entry whose `.SemanticModel` directory has no matching deployed
dataset.  This module pins the contract that an all-skipped run is a
failure, while preserving exit-0 for legitimately empty models and the
existing pass/fail signal.
"""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner

from pql_test.cli import cli
from pql_test.runner import PqlTest, TestResult, TestSuite


def _make_suite(*, passed: int = 0, failed: int = 0, skipped: int = 0) -> TestSuite:
    results: list[TestResult] = []
    for _ in range(passed):
        results.append(TestResult(test_name="p", passed=True, message=""))
    for _ in range(failed):
        results.append(TestResult(test_name="f", passed=False, message=""))
    for _ in range(skipped):
        results.append(
            TestResult(test_name="s", passed=False, skipped=True, message="no conn")
        )
    return TestSuite(
        model_path="/fake/path/Model.SemanticModel",
        tests=[PqlTest(name="x", file_path="", source="EVALUATE x()")],
        results=results,
        passed=passed,
        failed=failed,
        skipped=skipped,
        total=len(results),
    )


def _invoke(suite: TestSuite, *, model_path: str = "examples/SampleModel.SemanticModel"):
    """Invoke `pql-test run-tests <path>` with run_tests_from_model mocked."""
    runner = CliRunner()
    with (
        patch("pql_test.cli.Path") as mock_path,
        patch("pql_test.cli.resolve_xmla_connection", return_value=None),
        patch("pql_test.cli.run_tests_from_model", return_value=suite),
    ):
        # Pretend the model_path exists so cmd_run_tests doesn't sys.exit(1)
        # on the "not found" check.  Real Path semantics for str() and .resolve().
        mock_path.side_effect = lambda *a, **k: _PathStub(model_path)
        return runner.invoke(cli, ["run-tests", model_path], catch_exceptions=False)


class _PathStub:
    def __init__(self, raw: str):
        self._raw = str(raw)
        self.name = raw.split("/")[-1]
    def resolve(self):
        return self
    def exists(self):
        return True
    def __str__(self):
        return self._raw
    def __fspath__(self):
        return self._raw


def test_all_skipped_run_exits_non_zero():
    """Tests discovered but none executed → CI must see a failure."""
    suite = _make_suite(skipped=4)
    result = _invoke(suite)
    assert result.exit_code != 0, (
        "expected non-zero exit when all results were skipped (no connection),"
        f" got exit_code={result.exit_code}"
    )


def test_partial_skip_with_at_least_one_pass_exits_zero():
    """Some tests ran successfully, others skipped — green."""
    suite = _make_suite(passed=2, skipped=1)
    result = _invoke(suite)
    assert result.exit_code == 0


def test_any_failure_exits_non_zero():
    """Existing behavior preserved — hard failures still fail the run."""
    suite = _make_suite(passed=5, failed=1)
    result = _invoke(suite)
    assert result.exit_code != 0


def test_empty_model_exits_zero():
    """A model that legitimately has no tests should not be reported as failed."""
    suite = _make_suite()  # zero tests discovered, zero results
    result = _invoke(suite)
    assert result.exit_code == 0
