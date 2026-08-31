"""
Test discovery - find DAX test suites via XMLA or filesystem.

This module provides functions to:
- Discover tests from live models via PQL.Assert.RetrieveTestsV2/V1
- Fall back to filesystem scan of DAXQueries/*.Tests.dax
- Filter tests by environment (DEV, PROD, ANY, etc.)
- Match local ownership (functions.tmdl + DAXQueries/) against live tests
"""

from __future__ import annotations

import sys
from typing import Optional, TYPE_CHECKING

from pql_test.runner.model_path import (
    _collect_dax_test_files,
    _discover_local_test_names,
    _find_semantic_model_dir,
    _has_local_ownership_sources,
    _parse_dax_test_file,
)
from pql_test.runner.models import PqlTest, ResolvedXmlaConnection

if TYPE_CHECKING:
    from pql_test.runner.xmla import _execute_dax_query, _get_col
else:
    # Import at runtime through runner package to enable test mocking
    from pql_test import runner
    _execute_dax_query = lambda *args: runner._execute_dax_query(*args)
    _get_col = lambda *args: runner._get_col(*args)

__all__ = [
    "_test_matches_environment",
    "_retrieve_tests_via_dax",
    "retrieve_tests",
    "retrieve_test_by_name",
]


def _test_matches_environment(test_name: str, environment: str) -> bool:
    """Return True when *test_name* targets *environment* by naming convention.

    Test suites encode their target environment as the second-to-last
    dot-separated segment: ``<Suite>.<ENV>.Tests`` (or ``.Test``), e.g.
    ``Calculations.DEV.Tests``, ``BestPractices.ANY.Tests``,
    ``ColumnTests.BKUP.Test``.  Matching is case-insensitive and exact —
    ``--env DEV`` selects only ``*.DEV.Tests`` suites; ``ANY`` is an ordinary
    environment token, not a wildcard.  Names without an environment segment
    (e.g. ``Calcs.Tests``) never match an environment filter.
    """
    parts = test_name.split(".")
    if len(parts) < 3 or parts[-1].lower() not in ("test", "tests"):
        return False
    return parts[-2].lower() == environment.lower()


def _retrieve_tests_via_dax(
    connection: ResolvedXmlaConnection,
    environment: Optional[str] = None,
) -> Optional[list[PqlTest]]:
    """
    Discover test functions from a live model using XMLA.

    Tries ``PQL.Assert.RetrieveTestsV2()`` first (returns Name, Description,
    PQLAssert_ImpersonatedUserName).  Falls back to ``PQL.Assert.RetrieveTests()``
    (returns Name only) when V2 is absent from the model.

    When *environment* is supplied, ``PQL.Assert.RetrieveTestsV2("<env>")``
    is tried first so the model's own UDF does the environment filtering
    server-side.  If that call fails (e.g. the installed V2 takes no
    arguments) discovery falls back to the parameterless queries and the
    environment filter is applied client-side against the
    ``<Suite>.<ENV>.Tests`` naming convention instead.

    Returns a (possibly empty) list of PqlTest objects when either query
    succeeds, or ``None`` when both queries fail (e.g. PQL.Assert is not
    installed in this model, OR an auth/permission/connectivity error
    occurred), signalling the caller to fall back to the file-based scan.

    When both queries fail, emits a one-line stderr warning with the verbatim
    exception so the user can distinguish "PQL.Assert isn't installed in
    this model" (legitimate fallback) from "I don't have access" /
    "authentication failed" (real problem).  See
    tasks/surface-silent-test-discovery-failures-epic.md.
    """
    rows: list[dict] | None = None
    has_v2_columns = False
    server_filtered = False

    if environment:
        env_literal = environment.replace('"', '""')
        try:
            rows = _execute_dax_query(
                connection,
                f'EVALUATE PQL.Assert.RetrieveTestsV2("{env_literal}")',
            )
            has_v2_columns = True
            server_filtered = True
        except Exception:  # noqa: BLE001
            pass

    if rows is None:
        try:
            rows = _execute_dax_query(connection, "EVALUATE PQL.Assert.RetrieveTestsV2()")
            has_v2_columns = True
        except Exception:  # noqa: BLE001
            pass

    if rows is None:
        try:
            rows = _execute_dax_query(connection, "EVALUATE PQL.Assert.RetrieveTests()")
        except Exception as exc:  # noqa: BLE001
            # Both discovery queries failed — surface the verbatim error so
            # the user knows whether it's "PQL.Assert not installed" or a
            # real auth/permissions/connectivity problem.
            target = (
                f"{connection.server} / {connection.catalog}"
                if connection
                else "<unknown>"
            )
            print(
                f"Warning: live test discovery failed against {target}: "
                f"{type(exc).__name__}: {str(exc)[:300]}",
                file=sys.stderr,
            )
            return None  # neither function available — fall back to file scan

    tests: list[PqlTest] = []
    for row in rows or []:
        name = _get_col(row, "Name")
        if not name:
            continue
        description = (_get_col(row, "Description") or None) if has_v2_columns else None
        impersonated_user = (
            (_get_col(row, "PQLAssert_ImpersonatedUserName") or None)
            if has_v2_columns
            else None
        )
        role_name = (
            (_get_col(row, "PQLAssert_RoleName") or None) if has_v2_columns else None
        )
        tests.append(
            PqlTest(
                name=name,
                file_path="",
                source=f"EVALUATE {name}()",
                description=description,
                impersonated_user_name=impersonated_user,
                role_name=role_name,
            )
        )
    if environment and not server_filtered:
        tests = [t for t in tests if _test_matches_environment(t.name, environment)]
    return tests


def retrieve_tests(
    model_path: str,
    connection: Optional[ResolvedXmlaConnection] = None,
    environment: Optional[str] = None,
) -> list[PqlTest]:
    """
    Retrieve all DAX test suites for a PBIP model.

    When *connection* is supplied the live model is queried first via
    ``PQL.Assert.RetrieveTestsV2()`` (falling back to
    ``PQL.Assert.RetrieveTests()``).  This returns the authoritative set of
    test functions actually registered in the model — including tests defined
    directly in the model's ``functions.tmdl``, not just those in
    ``DAXQueries/``.

    When no connection is available (or both DAX queries fail) the function
    falls back to scanning the SemanticModel's DAXQueries/ folder for
    ``*.Tests.dax`` files.

    Parameters
    ----------
    model_path:
        Root directory of the PBIP model (contains the .pbip file).
    connection:
        Optional live XMLA connection.  Pass to enable live discovery.
    environment:
        Optional environment name (e.g. ``DEV``, ``PROD``, ``ANY``, ``BKUP``).
        When supplied, only suites targeting that environment are returned:
        live discovery passes it to ``PQL.Assert.RetrieveTestsV2("<env>")``,
        and file-scan / fallback paths match the ``<Suite>.<ENV>.Tests``
        naming convention (case-insensitive, exact).

    Returns
    -------
    List of PqlTest descriptors; empty list when none are found.
    """
    if connection is not None:
        live = _retrieve_tests_via_dax(connection, environment=environment)
        if live is not None:  # None means both queries failed
            # When model_path declares ownership-tracking artifacts (a
            # DAXQueries/ folder or a functions.tmdl), the local repo is the
            # source of truth — even an empty ownership set is meaningful (the
            # model declares no tests), so live discovery is filtered strictly.
            # Otherwise an auto-detected local Power BI Desktop instance
            # unrelated to this model would silently leak its tests into the
            # result.  For local/<name>, Fabric workspace.model paths, and bare
            # PBIP skeletons with no declaration location, we pass live
            # discovery through unfiltered.
            if _has_local_ownership_sources(model_path):
                local_names = _discover_local_test_names(model_path)
                # Scope the ownership comparison to the requested environment
                # so suites for other environments don't trigger spurious
                # "missing on server" warnings or leak past the filter.
                if environment:
                    local_names = {
                        n
                        for n in local_names
                        if _test_matches_environment(n, environment)
                    }
                live_names = {t.name for t in live}
                if local_names:
                    extras_on_server = sorted(live_names - local_names)
                    missing_on_server = sorted(local_names - live_names)
                    if extras_on_server:
                        print(
                            "Warning: deployed dataset contains "
                            f"{len(extras_on_server)} test function(s) not declared "
                            f"locally — skipping: {', '.join(extras_on_server)}",
                            file=sys.stderr,
                        )
                    if missing_on_server:
                        print(
                            "Warning: "
                            f"{len(missing_on_server)} local test function(s) "
                            "are not registered in the deployed dataset — "
                            f"deployment may be out of date: "
                            f"{', '.join(missing_on_server)}",
                            file=sys.stderr,
                        )
                elif live_names:
                    print(
                        f"Warning: model at {model_path} declares no tests "
                        f"locally; ignoring {len(live_names)} test function(s) "
                        "found on the auto-detected XMLA connection (likely "
                        "an unrelated Power BI Desktop instance).",
                        file=sys.stderr,
                    )
                return [t for t in live if t.name in local_names]
            return live

    # Offline fallback: scan DAXQueries/ folder for *.Tests.dax files
    semantic_model_dir = _find_semantic_model_dir(model_path)
    if not semantic_model_dir:
        return []
    tests = [
        _parse_dax_test_file(f) for f in _collect_dax_test_files(semantic_model_dir)
    ]
    if environment:
        tests = [t for t in tests if _test_matches_environment(t.name, environment)]
    return tests


def retrieve_test_by_name(
    model_path: str,
    test_name: str,
    connection: Optional[ResolvedXmlaConnection] = None,
    environment: Optional[str] = None,
) -> Optional[PqlTest]:
    """
    Retrieve a single DAX test suite by name (case-insensitive).

    The name is matched against the function name (e.g. "Calcs.DEV.Tests").
    When *connection* is supplied live discovery is used; otherwise the
    DAXQueries/ folder is scanned.  When *environment* is supplied the name
    must also belong to that environment's suite set.
    """
    for t in retrieve_tests(model_path, connection=connection, environment=environment):
        if t.name.lower() == test_name.lower():
            return t
    return None
