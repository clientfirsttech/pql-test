"""
PQL Test Runner Package — Core library for discovering and executing DAX tests.

This package provides the core functionality for pql-test, split into focused
modules with clear separation of concerns:

- models.py — Data classes (ModelIdentifier, PqlTest, TestResult, etc.)
- adomd.py — ADOMD.NET assembly loading and auto-install
- auth.py — MSAL token acquisition and authentication bridge
- pbi_rest.py — Power BI REST API helpers
- local_pbi.py — Local Power BI Desktop process detection
- model_path.py — Model identifier parsing (filesystem, local/, Fabric)
- resolver.py — XMLA connection resolution
- discovery.py — Test file discovery
- execution.py — Test execution engine
- coverage.py — Direct test-UDF coverage evidence model
- coverage_collector.py — XMLA-backed direct test-UDF coverage collection
- coverage_report.py — Text/JSON presentation for coverage reports

For backward compatibility, all public symbols are re-exported from this
__init__.py so existing imports continue to work:

    from pql_test.runner import HAS_PYADOMD, retrieve_tests, run_tests_from_model

Module Organization
-------------------
The split follows Single Responsibility Principle, keeping each module under
400 lines (soft budget) and 800 lines (hard budget). See the module budget
skill at ai/skills/aidd-module-budgets/SKILL.md for details.

Each module has minimal coupling to others, making the code easier to understand,
test, and maintain. The public API surface remains unchanged from the original
monolithic runner.py.
"""

from __future__ import annotations

# Import ADOMD.NET loading from adomd.py
from pql_test.runner.adomd import (
    _discover_adomd_search_dirs,
    get_adomd_connection_class,
    has_pyadomd,
)

# Import auth bridge from auth.py
from pql_test.runner.auth import (
    _resolve_authentication_with_stored_credentials,
)

# Import coverage evidence model from coverage.py
from pql_test.runner.coverage import (
    ClassificationResult,
    CoverageEvidence,
    CoverageGap,
    CoverageObjectType,
    EligibleObject,
    ExclusionRecord,
    classify_coverage,
)

# Import the coverage collector from coverage_collector.py
from pql_test.runner.coverage_collector import (
    CoverageReport,
    UnavailableCategory,
    collect_coverage,
)

# Import coverage report presentation from coverage_report.py
from pql_test.runner.coverage_report import (
    DEFAULT_WATERMARKS,
    CoverageSummary,
    category_counts,
    coverage_percent,
    coverage_report_to_dict,
    coverage_status,
    summarize_coverage,
)

# Import test discovery from discovery.py
from pql_test.runner.discovery import (
    _retrieve_tests_via_dax,
    _test_matches_environment,
    retrieve_test_by_name,
    retrieve_tests,
)

# Import test execution from execution.py
from pql_test.runner.execution import (
    run_test,
    run_tests,
    run_tests_from_model,
)

# Import local PBI detection from local_pbi.py
from pql_test.runner.local_pbi import (
    HAS_PSUTIL,  # Module-level constant for psutil availability
    _detect_local_pbi_desktop_port,
    _find_pbi_ancestor_pid,
    _get_catalog_from_local_port,
    _get_pbi_process_window_titles,
    _psutil,  # For test mocking compatibility
    get_pbi_files_opened,
    resolve_local_xmla_connection,
)

# Import model path parsing from model_path.py
from pql_test.runner.model_path import (
    _collect_dax_test_files,
    _discover_local_test_names,
    _find_pbip_file,
    _find_semantic_model_dir,
    _has_local_ownership_sources,
    _parse_dax_test_file,
    parse_model_identifier,
)

# During refactoring: import from appropriate submodules as they're created
# This maintains backward compatibility while we migrate code module-by-module
# Import data models from models.py
from pql_test.runner.models import (
    Endpoints,
    Environment,
    LocalPbiInstance,
    ModelIdentifier,
    PqlTest,
    ResolvedXmlaConnection,
    TestResult,
    TestSuite,
    XmlaConnectionOptions,
    get_api_endpoints,
)

# Import Power BI REST helpers from pbi_rest.py
from pql_test.runner.pbi_rest import (
    _acquire_service_principal_token,
    _resolve_pbi_workspace_and_dataset_names,
    _resolve_pbi_workspace_name,
    _verify_dataset_exists_in_workspace,
)

# Import connection resolution from resolver.py
from pql_test.runner.resolver import (
    _resolve_service_xmla_connection,
    resolve_local_xmla_connection_by_name,
    resolve_service_xmla_connection_by_name,
    resolve_xmla_connection,
)

# Import XMLA query execution from xmla.py
from pql_test.runner.xmla import (
    _build_connection_string,
    _execute_dax_query,
    _get_col,
)

# HAS_MSAL is needed by external modules
HAS_MSAL = False
try:
    import msal  # type: ignore[import-untyped]
    HAS_MSAL = True
except ImportError:
    pass

# HAS_PSUTIL is imported from local_pbi module above

__all__ = [
    # Re-exported from models
    "Environment",
    "Endpoints",
    "ModelIdentifier",
    "PqlTest",
    "TestResult",
    "TestSuite",
    "XmlaConnectionOptions",
    "ResolvedXmlaConnection",
    "LocalPbiInstance",
    "get_api_endpoints",
    # Re-exported from coverage
    "ClassificationResult",
    "CoverageEvidence",
    "CoverageGap",
    "CoverageObjectType",
    "EligibleObject",
    "ExclusionRecord",
    "classify_coverage",
    # Re-exported from coverage_collector
    "CoverageReport",
    "UnavailableCategory",
    "collect_coverage",
    # Re-exported from coverage_report
    "DEFAULT_WATERMARKS",
    "CoverageSummary",
    "category_counts",
    "coverage_percent",
    "coverage_report_to_dict",
    "coverage_status",
    "summarize_coverage",
    # Re-exported from adomd
    "HAS_PYADOMD",
    "get_adomd_connection_class",
    "has_pyadomd",
    # Re-exported from model_path
    "parse_model_identifier",
    # Re-exported from local_pbi
    "get_pbi_files_opened",
    # Re-exported from resolver
    "resolve_xmla_connection",
    "resolve_service_xmla_connection_by_name",
    "resolve_local_xmla_connection_by_name",
    # Re-exported from discovery
    "retrieve_tests",
    "retrieve_test_by_name",
    # Re-exported from execution
    "run_test",
    "run_tests",
    "run_tests_from_model",
    # Module-level constants
    "HAS_MSAL",
    "HAS_PSUTIL",
]


def __getattr__(name: str):
    """Lazily resolve ``HAS_PYADOMD`` so its current value reflects the
    deferred ADOMD.NET load state.  Preserves the historical
    ``from pql_test.runner import HAS_PYADOMD`` call pattern used by the
    live-service tests and any external consumer."""
    if name == "HAS_PYADOMD":
        return has_pyadomd()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
