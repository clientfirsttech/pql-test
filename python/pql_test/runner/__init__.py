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

# During refactoring: import from appropriate submodules as they're created
# This maintains backward compatibility while we migrate code module-by-module

# Import data models from models.py
from pql_test.runner.models import (
    Environment,
    Endpoints,
    ModelIdentifier,
    PqlTest,
    TestResult,
    TestSuite,
    XmlaConnectionOptions,
    ResolvedXmlaConnection,
    LocalPbiInstance,
    get_api_endpoints,
)

# Import ADOMD.NET loading from adomd.py
from pql_test.runner.adomd import (
    HAS_PYADOMD,
    get_adomd_connection_class,
    _discover_adomd_search_dirs,
)

# Import model path parsing from model_path.py
from pql_test.runner.model_path import (
    parse_model_identifier,
    _find_semantic_model_dir,
    _find_pbip_file,
    _collect_dax_test_files,
    _parse_dax_test_file,
    _discover_local_test_names,
    _has_local_ownership_sources,
)

# Import local PBI detection from local_pbi.py
from pql_test.runner.local_pbi import (
    HAS_PSUTIL,  # Module-level constant for psutil availability
    get_pbi_files_opened,
    resolve_local_xmla_connection,
    _detect_local_pbi_desktop_port,
    _get_pbi_process_window_titles,
    _get_catalog_from_local_port,
    _find_pbi_ancestor_pid,
    _psutil,  # For test mocking compatibility
)

# Import auth bridge from auth.py
from pql_test.runner.auth import (
    _resolve_authentication_with_stored_credentials,
)

# Import Power BI REST helpers from pbi_rest.py
from pql_test.runner.pbi_rest import (
    _resolve_pbi_workspace_and_dataset_names,
    _resolve_pbi_workspace_name,
    _verify_dataset_exists_in_workspace,
    _acquire_service_principal_token,
)

# Import connection resolution from resolver.py
from pql_test.runner.resolver import (
    resolve_xmla_connection,
    resolve_service_xmla_connection_by_name,
    resolve_local_xmla_connection_by_name,
    _resolve_service_xmla_connection,
)

# Import XMLA query execution from xmla.py
from pql_test.runner.xmla import (
    _build_connection_string,
    _get_col,
    _execute_dax_query,
)

# Import test discovery from discovery.py
from pql_test.runner.discovery import (
    _test_matches_environment,
    _retrieve_tests_via_dax,
    retrieve_tests,
    retrieve_test_by_name,
)

# Import test execution from execution.py
from pql_test.runner.execution import (
    run_test,
    run_tests,
    run_tests_from_model,
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
    # Re-exported from adomd
    "HAS_PYADOMD",
    "get_adomd_connection_class",
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
