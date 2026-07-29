"""Tests for filtering live test discovery by local model ownership.

When ``retrieve_tests`` is called with both an XMLA connection **and** a
filesystem ``model_path``, the local repository is the source of truth for
which test functions belong to that model.  Test functions returned by
``PQL.Assert.RetrieveTestsV2()`` that are not declared either in the local
``definition/functions.tmdl`` or as a ``DAXQueries/*.Tests.dax`` file are
filtered out so cross-model contamination on the deployed dataset does not
leak into a model's job.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from pql_test.runner import (
    PqlTest,
    ResolvedXmlaConnection,
    retrieve_tests,
)


def _make_local_model(
    tmp_path: Path,
    *,
    daxqueries_test_names: list[str] | None = None,
    functions_tmdl_test_names: list[str] | None = None,
) -> str:
    """Create a minimal PBIP model on disk and return its root path."""
    model_dir = tmp_path / "Sample.SemanticModel"
    daxqueries = model_dir / "DAXQueries"
    daxqueries.mkdir(parents=True, exist_ok=True)
    for name in daxqueries_test_names or []:
        (daxqueries / f"{name}.dax").write_text(
            f"EVALUATE {name}()", encoding="utf-8"
        )
    definition = model_dir / "definition"
    definition.mkdir(parents=True, exist_ok=True)
    if functions_tmdl_test_names is not None:
        lines = []
        for name in functions_tmdl_test_names:
            lines.append(f"function '{name}' =")
            lines.append("\t() => ROW(\"TestName\", \"x\", \"Expected\", 0, \"Actual\", 0, \"Passed\", TRUE)")
            lines.append("")
        (definition / "functions.tmdl").write_text(
            "\n".join(lines), encoding="utf-8"
        )
    return str(tmp_path)


def _conn() -> ResolvedXmlaConnection:
    return ResolvedXmlaConnection(server="powerbi://test/v1.0/myorg/ws", catalog="ds")


def test_live_tests_outside_local_files_are_filtered_out(tmp_path):
    """Given a deployed dataset that includes a foreign test, should not run it."""
    model_path = _make_local_model(
        tmp_path,
        daxqueries_test_names=["Calculations.DEV.Tests", "Schema.DEV.Tests"],
        functions_tmdl_test_names=["Calcs.DEV.Tests"],
    )
    live = [
        PqlTest(name="Calcs.DEV.Tests", file_path="", source="EVALUATE Calcs.DEV.Tests()"),
        PqlTest(name="Calculations.DEV.Tests", file_path="", source="EVALUATE Calculations.DEV.Tests()"),
        PqlTest(name="Schema.DEV.Tests", file_path="", source="EVALUATE Schema.DEV.Tests()"),
        PqlTest(name="RLS.ANY.Tests", file_path="", source="EVALUATE RLS.ANY.Tests()"),
    ]
    with patch("pql_test.runner._retrieve_tests_via_dax", return_value=live):
        result = retrieve_tests(model_path, connection=_conn())

    names = {t.name for t in result}
    assert "RLS.ANY.Tests" not in names, "foreign test must be filtered out"
    assert names == {"Calcs.DEV.Tests", "Calculations.DEV.Tests", "Schema.DEV.Tests"}


def test_filter_warns_about_extras_on_server(tmp_path, capsys):
    """Given a deployed dataset with foreign tests, should warn naming them."""
    model_path = _make_local_model(
        tmp_path,
        daxqueries_test_names=["Calcs.DEV.Tests"],
    )
    live = [
        PqlTest(name="Calcs.DEV.Tests", file_path="", source="EVALUATE Calcs.DEV.Tests()"),
        PqlTest(name="RLS.ANY.Tests", file_path="", source="EVALUATE RLS.ANY.Tests()"),
        PqlTest(name="ShouldFail.TEST.Tests", file_path="", source="EVALUATE ShouldFail.TEST.Tests()"),
    ]
    with patch("pql_test.runner._retrieve_tests_via_dax", return_value=live):
        retrieve_tests(model_path, connection=_conn())

    captured = capsys.readouterr()
    assert "RLS.ANY.Tests" in captured.err
    assert "ShouldFail.TEST.Tests" in captured.err


def test_filter_warns_about_local_tests_missing_from_server(tmp_path, capsys):
    """Given a local test that the deployed dataset doesn't have, should warn but continue."""
    model_path = _make_local_model(
        tmp_path,
        daxqueries_test_names=["Calcs.DEV.Tests", "NewSuite.DEV.Tests"],
    )
    live = [
        PqlTest(name="Calcs.DEV.Tests", file_path="", source="EVALUATE Calcs.DEV.Tests()"),
    ]
    with patch("pql_test.runner._retrieve_tests_via_dax", return_value=live):
        result = retrieve_tests(model_path, connection=_conn())

    captured = capsys.readouterr()
    assert "NewSuite.DEV.Tests" in captured.err
    # Continue running what is available.
    assert {t.name for t in result} == {"Calcs.DEV.Tests"}


def test_no_local_files_passthrough_keeps_all_live_tests(tmp_path):
    """Given no local source of truth, should keep all live tests (no filter applied)."""
    # Model directory exists but has no DAXQueries and no functions.tmdl.
    model_dir = tmp_path / "NoSource.SemanticModel"
    model_dir.mkdir(parents=True)
    live = [
        PqlTest(name="A.Tests", file_path="", source="EVALUATE A.Tests()"),
        PqlTest(name="B.Tests", file_path="", source="EVALUATE B.Tests()"),
    ]
    with patch("pql_test.runner._retrieve_tests_via_dax", return_value=live):
        result = retrieve_tests(str(tmp_path), connection=_conn())

    assert {t.name for t in result} == {"A.Tests", "B.Tests"}


def test_functions_tmdl_only_ownership_filters_correctly(tmp_path):
    """Given tests declared only in functions.tmdl, should still own them."""
    model_path = _make_local_model(
        tmp_path,
        functions_tmdl_test_names=["Server.ANY.Tests"],
    )
    live = [
        PqlTest(name="Server.ANY.Tests", file_path="", source="EVALUATE Server.ANY.Tests()"),
        PqlTest(name="Intruder.ANY.Tests", file_path="", source="EVALUATE Intruder.ANY.Tests()"),
    ]
    with patch("pql_test.runner._retrieve_tests_via_dax", return_value=live):
        result = retrieve_tests(model_path, connection=_conn())

    assert {t.name for t in result} == {"Server.ANY.Tests"}


def test_filter_skipped_for_local_model_identifier(tmp_path):
    """Given a `local/<name>` identifier with no resolvable filesystem path, should not filter."""
    live = [
        PqlTest(name="A.Tests", file_path="", source="EVALUATE A.Tests()"),
        PqlTest(name="B.Tests", file_path="", source="EVALUATE B.Tests()"),
    ]
    with patch("pql_test.runner._retrieve_tests_via_dax", return_value=live):
        result = retrieve_tests("local/SomeModel", connection=_conn())

    assert {t.name for t in result} == {"A.Tests", "B.Tests"}
