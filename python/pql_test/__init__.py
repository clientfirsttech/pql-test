# SPDX-License-Identifier: AGPL-3.0-only
"""pql_test package — DAX test runner for PBIP semantic models."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:
    __version__ = _pkg_version("pql-test")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0.0.0"

# Expose main modules for easier imports
from pql_test.runner import (
    Environment,
    ModelIdentifier,
    PqlTest,
    TestResult,
    TestSuite,
    XmlaConnectionOptions,
    parse_model_identifier,
    retrieve_test_by_name,
    retrieve_tests,
    run_tests_from_model,
)

__all__ = [
    "Environment",
    "ModelIdentifier",
    "PqlTest",
    "TestResult",
    "TestSuite",
    "XmlaConnectionOptions",
    "__version__",
    "parse_model_identifier",
    "retrieve_test_by_name",
    "retrieve_tests",
    "run_tests_from_model",
]
