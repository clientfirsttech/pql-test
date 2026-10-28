# SPDX-License-Identifier: AGPL-3.0-only
"""pql_test package — DAX test runner for PBIP semantic models."""

from __future__ import annotations

__version__ = "0.1.0"

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
