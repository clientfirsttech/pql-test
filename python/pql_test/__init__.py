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
    retrieve_tests,
    retrieve_test_by_name,
    run_tests_from_model,
)

__all__ = [
    "__version__",
    "Environment",
    "ModelIdentifier",
    "PqlTest",
    "TestResult",
    "TestSuite",
    "XmlaConnectionOptions",
    "parse_model_identifier",
    "retrieve_tests",
    "retrieve_test_by_name",
    "run_tests_from_model",
]
