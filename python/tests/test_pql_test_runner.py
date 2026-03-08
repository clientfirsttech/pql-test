"""
Tests for pql_test_runner core library.

Run with:
    cd python
    pytest tests/test_pql_test_runner.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Allow running from the project root or from the python/ directory
sys.path.insert(0, str(Path(__file__).parent.parent))

from unittest.mock import MagicMock

from pql_test_runner import (
    HAS_PSUTIL,
    HAS_PYADOMD,
    Environment,
    LocalPbiInstance,
    PqlTest,
    ResolvedXmlaConnection,
    TestResult,
    XmlaConnectionOptions,
    _collect_dax_test_files,
    _detect_local_pbi_desktop_port,
    _find_pbip_file,
    _find_semantic_model_dir,
    get_pbi_files_opened,
    resolve_local_xmla_connection,
    resolve_xmla_connection,
    retrieve_test_by_name,
    retrieve_tests,
    run_test,
    run_tests,
    run_tests_from_model,
)
from tests.conftest import make_dax_source


# ---------------------------------------------------------------------------
# Test constants
# ---------------------------------------------------------------------------

# Arbitrary fake AS port used in tests that mock the entire process-detection
# stack. PBI Desktop assigns a random ephemeral port each session; tests must
# not assume any specific value — derive assertions from mock inputs instead.
_MOCK_AS_PORT_A = 50001   # first fake instance
_MOCK_AS_PORT_B = 50002   # second fake instance (multi-model tests)

# Fake server string returned by mocked _detect_local_pbi_desktop_port.
# Mirrors the 'port file' / legacy fallback path (pre-psutil).
_MOCK_PORTFILE_SERVER = f"localhost:{_MOCK_AS_PORT_A}"


# ---------------------------------------------------------------------------
# Helpers for mocking psutil processes / connections
# ---------------------------------------------------------------------------

def _make_mock_tcp_listen(port: int, ip: str = "127.0.0.1") -> MagicMock:
    """Return a MagicMock that looks like a psutil LISTEN TCP connection."""
    conn = MagicMock()
    conn.status = "LISTEN"
    conn.laddr = MagicMock()
    conn.laddr.ip = ip
    conn.laddr.port = port
    return conn


def _make_mock_process(pid: int, name: str, ppid: int, listen_port: int | None = None) -> MagicMock:
    """Return a MagicMock that looks like a psutil Process object."""
    proc = MagicMock()
    proc.info = {"pid": pid, "name": name, "ppid": ppid}
    if listen_port is not None:
        proc.net_connections.return_value = [_make_mock_tcp_listen(listen_port)]
    else:
        proc.net_connections.return_value = []
    return proc


# ---------------------------------------------------------------------------
# _find_semantic_model_dir
# ---------------------------------------------------------------------------

class TestFindSemanticModelDir:
    def test_returns_none_for_nonexistent_path(self):
        assert _find_semantic_model_dir("/nonexistent/path/xyz") is None

    def test_returns_none_when_no_semantic_model_dir(self, tmp_path):
        assert _find_semantic_model_dir(str(tmp_path)) is None

    def test_finds_semantic_model_dir(self, tmp_path):
        sem_dir = tmp_path / "Model.SemanticModel"
        sem_dir.mkdir()
        result = _find_semantic_model_dir(str(tmp_path))
        assert result == str(sem_dir)

    def test_ignores_non_directory_entries_ending_in_semantic_model(self, tmp_path):
        (tmp_path / "Model.SemanticModel").write_text("not a directory")
        assert _find_semantic_model_dir(str(tmp_path)) is None

    def test_returns_first_found_semantic_model_dir(self, tmp_path):
        (tmp_path / "A.SemanticModel").mkdir()
        (tmp_path / "B.SemanticModel").mkdir()
        result = _find_semantic_model_dir(str(tmp_path))
        assert result is not None
        assert result.endswith(".SemanticModel")


# ---------------------------------------------------------------------------
# _find_pbip_file
# ---------------------------------------------------------------------------

class TestFindPbipFile:
    def test_returns_none_for_nonexistent_path(self):
        assert _find_pbip_file("/nonexistent/path/xyz") is None

    def test_returns_none_when_no_pbip_file(self, tmp_path):
        assert _find_pbip_file(str(tmp_path)) is None

    def test_finds_pbip_file(self, tmp_path):
        pbip = tmp_path / "MyModel.pbip"
        pbip.write_text("{}")
        result = _find_pbip_file(str(tmp_path))
        assert result == str(pbip)

    def test_ignores_pbip_directories(self, tmp_path):
        (tmp_path / "FakeDir.pbip").mkdir()
        assert _find_pbip_file(str(tmp_path)) is None

    def test_finds_pbip_from_semantic_model_path(self, tmp_path):
        """When given the .SemanticModel subdirectory, finds the .pbip in the parent."""
        pbip = tmp_path / "MyModel.pbip"
        pbip.write_text("{}")
        semantic_dir = tmp_path / "MyModel.SemanticModel"
        semantic_dir.mkdir()
        result = _find_pbip_file(str(semantic_dir))
        assert result == str(pbip)


# ---------------------------------------------------------------------------
# retrieve_tests
# ---------------------------------------------------------------------------

class TestRetrieveTests:
    def test_returns_empty_when_model_path_does_not_exist(self):
        assert retrieve_tests("/nonexistent/path/xyz") == []

    def test_returns_empty_when_no_semantic_model_dir(self, tmp_path):
        assert retrieve_tests(str(tmp_path)) == []

    def test_returns_empty_when_daxqueries_folder_missing(self, tmp_path):
        (tmp_path / "model.SemanticModel").mkdir()
        assert retrieve_tests(str(tmp_path)) == []

    def test_returns_empty_when_no_tests_dax_files(self, tmp_model):
        model_dir = tmp_model([])
        assert retrieve_tests(model_dir) == []

    def test_discovers_single_test_suite(self, tmp_model):
        model_dir = tmp_model(
            [{"suite_name": "Calculations.DEV", "source": make_dax_source("Calcs")}]
        )
        tests = retrieve_tests(model_dir)
        assert len(tests) == 1
        assert tests[0].name == "Calculations.DEV.Tests"

    def test_discovers_multiple_test_suites(self, tmp_model):
        model_dir = tmp_model(
            [
                {"suite_name": "Calculations.DEV", "source": make_dax_source("Calcs")},
                {"suite_name": "DataQuality.DEV", "source": make_dax_source("DQ")},
                {"suite_name": "Schema.DEV", "source": make_dax_source("Schema")},
            ]
        )
        tests = retrieve_tests(model_dir)
        assert len(tests) == 3

    def test_ignores_non_tests_dax_files(self, tmp_path):
        dax_dir = tmp_path / "model.SemanticModel" / "DAXQueries"
        dax_dir.mkdir(parents=True)
        (dax_dir / "Query 1.dax").write_text("EVALUATE ROW(\"x\", 1)")
        assert retrieve_tests(str(tmp_path)) == []

    def test_only_tests_dax_suffix_matches(self, tmp_path):
        dax_dir = tmp_path / "model.SemanticModel" / "DAXQueries"
        dax_dir.mkdir(parents=True)
        # These should NOT be picked up
        (dax_dir / "BestPractices.dax").write_text("EVALUATE ROW(\"x\", 1)")
        (dax_dir / "Tests.txt").write_text("not dax")
        assert retrieve_tests(str(tmp_path)) == []

    def test_surfaces_function_name_as_description(self, tmp_model):
        source = make_dax_source("Calcs.DEV.Tests")
        model_dir = tmp_model([{"suite_name": "Calculations.DEV", "source": source}])
        tests = retrieve_tests(model_dir)
        assert tests[0].description is not None
        assert "Calcs.DEV.Tests" in tests[0].description

    def test_description_is_none_when_no_function_keyword(self, tmp_model):
        source = "EVALUATE ROW(\"x\", 1)"
        model_dir = tmp_model([{"suite_name": "Simple.Test", "source": source}])
        tests = retrieve_tests(model_dir)
        assert tests[0].description is None

    def test_test_has_correct_source(self, tmp_model):
        source = make_dax_source("MyFunc")
        model_dir = tmp_model([{"suite_name": "My.Test", "source": source}])
        tests = retrieve_tests(model_dir)
        assert tests[0].source == source

    def test_test_has_correct_file_path(self, tmp_model):
        model_dir = tmp_model(
            [{"suite_name": "Calculations.DEV", "source": "EVALUATE ROW(\"x\",1)"}]
        )
        tests = retrieve_tests(model_dir)
        assert tests[0].file_path.endswith("Calculations.DEV.Tests.dax")

    def test_discovers_suites_from_real_sample_model(self, sample_model_path):
        tests = retrieve_tests(sample_model_path)
        assert len(tests) >= 3, f"Expected >= 3 suites, got {len(tests)}"

    def test_includes_known_suite_from_sample_model(self, sample_model_path):
        tests = retrieve_tests(sample_model_path)
        names = [t.name for t in tests]
        assert any(
            "Calculations" in n or "DataQuality" in n or "Schema" in n
            for n in names
        ), f"Expected known suite names, got: {names}"


# ---------------------------------------------------------------------------
# retrieve_test_by_name
# ---------------------------------------------------------------------------

class TestRetrieveTestByName:
    def test_returns_none_for_nonexistent_model(self):
        assert retrieve_test_by_name("/nonexistent/path/xyz", "Any.Tests") is None

    def test_returns_none_when_suite_not_found(self, tmp_model):
        model_dir = tmp_model(
            [{"suite_name": "Existing", "source": make_dax_source("Existing")}]
        )
        assert retrieve_test_by_name(model_dir, "Missing.Tests") is None

    def test_finds_suite_by_exact_name(self, tmp_model):
        model_dir = tmp_model(
            [{"suite_name": "Calculations.DEV", "source": make_dax_source("Calcs")}]
        )
        test = retrieve_test_by_name(model_dir, "Calculations.DEV.Tests")
        assert test is not None
        assert test.name == "Calculations.DEV.Tests"

    def test_is_case_insensitive(self, tmp_model):
        model_dir = tmp_model(
            [{"suite_name": "Calculations.DEV", "source": make_dax_source("Calcs")}]
        )
        assert retrieve_test_by_name(model_dir, "CALCULATIONS.DEV.TESTS") is not None
        assert retrieve_test_by_name(model_dir, "calculations.dev.tests") is not None

    def test_returns_correct_pql_test_object(self, tmp_model):
        source = make_dax_source("Calcs")
        model_dir = tmp_model(
            [{"suite_name": "Calculations.DEV", "source": source}]
        )
        test = retrieve_test_by_name(model_dir, "Calculations.DEV.Tests")
        assert test is not None
        assert test.source == source
        assert test.file_path.endswith(".dax")


# ---------------------------------------------------------------------------
# resolve_xmla_connection
# ---------------------------------------------------------------------------

class TestResolveXmlaConnection:
    def test_returns_remote_connection_with_all_params(self, tmp_path):
        opts = XmlaConnectionOptions(
            tenant_id="tenant-1",
            workspace_id="ws-1",
            dataset_id="ds-1",
        )
        with (
            patch("pql_test_runner._acquire_service_principal_token", return_value="fake-token"),
            patch("pql_test_runner._resolve_pbi_workspace_and_dataset_names", return_value=("ws-1", "ds-1")),
        ):
            conn = resolve_xmla_connection(str(tmp_path), opts)
        assert conn is not None
        assert "myorg" in conn.server
        assert "ws-1" in conn.server
        assert conn.catalog == "ds-1"

    def test_remote_server_uses_powerbi_xmla_url(self, tmp_path):
        opts = XmlaConnectionOptions(
            tenant_id="t", workspace_id="w", dataset_id="d"
        )
        with (
            patch("pql_test_runner._acquire_service_principal_token", return_value="fake-token"),
            patch("pql_test_runner._resolve_pbi_workspace_and_dataset_names", return_value=("w", "d")),
        ):
            conn = resolve_xmla_connection(str(tmp_path), opts)
        assert conn is not None
        assert "powerbi://api.powerbi.com/v1.0/" in conn.server

    def test_remote_connection_includes_service_principal_creds(self, tmp_path):
        opts = XmlaConnectionOptions(
            tenant_id="tenant-1",
            workspace_id="ws-1",
            dataset_id="ds-1",
            client_id="client-1",
            client_secret="secret-1",
        )
        with (
            patch("pql_test_runner._acquire_service_principal_token", return_value="fake-token"),
            patch("pql_test_runner._resolve_pbi_workspace_and_dataset_names", return_value=("ws-1", "ds-1")),
        ):
            conn = resolve_xmla_connection(str(tmp_path), opts)
        assert conn is not None
        assert conn.client_id == "client-1"
        assert conn.client_secret == "secret-1"
        assert conn.tenant_id == "tenant-1"
        assert conn.access_token == "fake-token"

    def test_returns_none_without_params_and_no_local_pbi(self, tmp_path):
        opts = XmlaConnectionOptions()
        with (
            patch("pql_test_runner.get_pbi_files_opened", return_value=[]),
            patch("pql_test_runner._detect_local_pbi_desktop_port", return_value=None),
        ):
            conn = resolve_xmla_connection(str(tmp_path), opts)
        assert conn is None

    def test_returns_local_connection_when_pbi_desktop_running(self, tmp_path):
        (tmp_path / "MyModel.pbip").write_text("{}")
        opts = XmlaConnectionOptions()
        with (
            patch("pql_test_runner.get_pbi_files_opened", return_value=[]),
            patch(
                "pql_test_runner._detect_local_pbi_desktop_port",
                return_value=_MOCK_PORTFILE_SERVER,
            ),
        ):
            conn = resolve_xmla_connection(str(tmp_path), opts)
        assert conn is not None
        assert conn.server == _MOCK_PORTFILE_SERVER  # derives from mock, not a magic string
        assert conn.catalog == ""  # local: no Initial Catalog; AS auto-selects the database

    def test_local_catalog_derived_from_pbip_stem(self, tmp_path):
        """Local connections omit Initial Catalog regardless of pbip name."""
        (tmp_path / "SampleModel.pbip").write_text("{}")
        with (
            patch("pql_test_runner.get_pbi_files_opened", return_value=[]),
            patch(
                "pql_test_runner._detect_local_pbi_desktop_port",
                return_value=_MOCK_PORTFILE_SERVER,
            ),
        ):
            conn = resolve_xmla_connection(str(tmp_path), XmlaConnectionOptions())
        assert conn is not None
        assert conn.catalog == ""  # local: Initial Catalog omitted; AS auto-selects

    def test_remote_connection_takes_priority_over_local(self, tmp_path):
        (tmp_path / "MyModel.pbip").write_text("{}")
        opts = XmlaConnectionOptions(
            tenant_id="t", workspace_id="w", dataset_id="d"
        )
        with (
            patch("pql_test_runner._acquire_service_principal_token", return_value="fake-token"),
            patch("pql_test_runner._resolve_pbi_workspace_and_dataset_names", return_value=("w", "d")),
            patch(
                "pql_test_runner._detect_local_pbi_desktop_port",
                return_value=_MOCK_PORTFILE_SERVER,  # port is irrelevant; remote URL takes priority
            ),
        ):
            conn = resolve_xmla_connection(str(tmp_path), opts)
        assert conn is not None
        assert "powerbi://api.powerbi.com" in conn.server

    def test_requires_all_three_remote_params(self, tmp_path):
        # Missing dataset_id — should not produce a remote connection
        opts = XmlaConnectionOptions(tenant_id="t", workspace_id="w")
        with patch("pql_test_runner._detect_local_pbi_desktop_port", return_value=None):
            conn = resolve_xmla_connection(str(tmp_path), opts)
        assert conn is None


# ---------------------------------------------------------------------------
# run_test — no connection
# ---------------------------------------------------------------------------

class TestRunTestNoConnection:
    def _make_test(self, name: str = "My.Tests") -> PqlTest:
        return PqlTest(
            name=name,
            file_path=f"/fake/{name}.dax",
            source="EVALUATE ROW(\"x\", 1)",
        )

    def test_returns_single_failed_result_without_connection(self):
        results = run_test(self._make_test(), connection=None)
        assert len(results) == 1
        assert results[0].passed is False
        assert results[0].test_name == "My.Tests"

    def test_error_message_mentions_xmla(self):
        result = run_test(self._make_test(), connection=None)[0]
        assert "XMLA" in result.message or "connection" in result.message.lower()

    def test_result_has_non_negative_duration(self):
        result = run_test(self._make_test(), connection=None)[0]
        assert result.duration_ms is not None
        assert result.duration_ms >= 0

    def test_no_error_field_when_skipped(self):
        result = run_test(self._make_test(), connection=None)[0]
        assert result.error is None


# ---------------------------------------------------------------------------
# run_test — mocked XMLA execution
# ---------------------------------------------------------------------------

class TestRunTestWithMockedXmla:
    def _make_test(self) -> PqlTest:
        return PqlTest(
            name="Calculations.DEV.Tests",
            file_path="/fake/Calculations.DEV.Tests.dax",
            source="EVALUATE Calculations()",
        )

    def _make_conn(self) -> ResolvedXmlaConnection:
        # Port is irrelevant here; we are testing run_test result parsing, not port propagation
        return ResolvedXmlaConnection(server=_MOCK_PORTFILE_SERVER, catalog="Model")

    def test_passes_when_passed_column_is_true(self):
        rows = [{"TestName": "My test", "Expected": "1", "Actual": "1", "Passed": "true"}]
        with patch("pql_test_runner._execute_dax_query", return_value=rows):
            results = run_test(self._make_test(), self._make_conn())
        assert len(results) == 1
        assert results[0].passed is True

    def test_passes_when_passed_column_is_1(self):
        rows = [{"TestName": "t", "Expected": "x", "Actual": "x", "Passed": "1"}]
        with patch("pql_test_runner._execute_dax_query", return_value=rows):
            results = run_test(self._make_test(), self._make_conn())
        assert results[0].passed is True

    def test_fails_when_passed_column_is_false(self):
        rows = [{"TestName": "Bad test", "Expected": "1", "Actual": "2", "Passed": "false"}]
        with patch("pql_test_runner._execute_dax_query", return_value=rows):
            results = run_test(self._make_test(), self._make_conn())
        assert results[0].passed is False

    def test_test_name_used_from_row(self):
        rows = [{"TestName": "MyRowTest", "Expected": "1", "Actual": "1", "Passed": "true"}]
        with patch("pql_test_runner._execute_dax_query", return_value=rows):
            results = run_test(self._make_test(), self._make_conn())
        assert results[0].test_name == "MyRowTest"

    def test_falls_back_to_suite_name_when_test_name_empty(self):
        rows = [{"TestName": "", "Expected": "1", "Actual": "1", "Passed": "true"}]
        with patch("pql_test_runner._execute_dax_query", return_value=rows):
            results = run_test(self._make_test(), self._make_conn())
        assert results[0].test_name == "Calculations.DEV.Tests"

    def test_handles_multiple_assertion_rows(self):
        rows = [
            {"TestName": "t1", "Expected": "1", "Actual": "1", "Passed": "true"},
            {"TestName": "t2", "Expected": "2", "Actual": "3", "Passed": "false"},
        ]
        with patch("pql_test_runner._execute_dax_query", return_value=rows):
            results = run_test(self._make_test(), self._make_conn())
        assert len(results) == 2
        assert results[0].passed is True
        assert results[1].passed is False

    def test_message_includes_expected_and_actual(self):
        rows = [{"TestName": "t", "Expected": "42", "Actual": "99", "Passed": "false"}]
        with patch("pql_test_runner._execute_dax_query", return_value=rows):
            results = run_test(self._make_test(), self._make_conn())
        assert "42" in results[0].message
        assert "99" in results[0].message

    def test_handles_best_practice_rule_description(self):
        rows = [
            {
                "TestName": "bp1",
                "Expected": "0",
                "Actual": "0",
                "Passed": "true",
                "RuleDescription": "Avoid SELECT *",
            }
        ]
        with patch("pql_test_runner._execute_dax_query", return_value=rows):
            results = run_test(self._make_test(), self._make_conn())
        assert "Rule: Avoid SELECT *" in results[0].message

    def test_returns_failed_result_on_empty_rows(self):
        with patch("pql_test_runner._execute_dax_query", return_value=[]):
            results = run_test(self._make_test(), self._make_conn())
        assert len(results) == 1
        assert results[0].passed is False
        assert "no rows" in results[0].message.lower()

    def test_returns_failed_result_on_query_exception(self):
        with patch(
            "pql_test_runner._execute_dax_query",
            side_effect=RuntimeError("XMLA connection failed"),
        ):
            results = run_test(self._make_test(), self._make_conn())
        assert len(results) == 1
        assert results[0].passed is False
        assert results[0].error == "XMLA connection failed"
        assert results[0].message == "Test execution failed"

    def test_column_lookup_is_case_insensitive(self):
        # Column names may carry a table prefix from DAX
        rows = [
            {
                "Calculations[TestName]": "t1",
                "Calculations[Expected]": "1",
                "Calculations[Actual]": "1",
                "Calculations[Passed]": "true",
            }
        ]
        with patch("pql_test_runner._execute_dax_query", return_value=rows):
            results = run_test(self._make_test(), self._make_conn())
        assert results[0].passed is True
        assert results[0].test_name == "t1"


# ---------------------------------------------------------------------------
# run_tests (multiple tests)
# ---------------------------------------------------------------------------

class TestRunTests:
    def test_returns_empty_list_for_no_tests(self):
        assert run_tests([], connection=None) == []

    def test_returns_skipped_result_per_test_when_no_connection(self):
        tests = [
            PqlTest(name="A.Tests", file_path="/a", source="EVALUATE ROW(\"x\",1)"),
            PqlTest(name="B.Tests", file_path="/b", source="EVALUATE ROW(\"y\",2)"),
        ]
        results = run_tests(tests, connection=None)
        assert len(results) == 2
        assert all(not r.passed for r in results)
        assert all(r.skipped for r in results)
    def test_flattens_multiple_row_results(self):
        tests = [PqlTest(name="T", file_path="/t", source="EVALUATE T()")]
        rows = [
            {"TestName": "r1", "Expected": "1", "Actual": "1", "Passed": "true"},
            {"TestName": "r2", "Expected": "2", "Actual": "2", "Passed": "true"},
        ]
        conn = ResolvedXmlaConnection(server=_MOCK_PORTFILE_SERVER, catalog="M")
        with patch("pql_test_runner._execute_dax_query", return_value=rows):
            results = run_tests(tests, connection=conn)
        assert len(results) == 2


# ---------------------------------------------------------------------------
# run_tests_from_model
# ---------------------------------------------------------------------------

class TestRunTestsFromModel:
    def test_returns_empty_suite_for_nonexistent_model(self):
        suite = run_tests_from_model("/nonexistent/path/xyz")
        assert suite.total == 0
        assert suite.passed == 0
        assert suite.failed == 0
        assert suite.skipped == 0
        assert suite.tests == []

    def test_suite_model_path_preserved(self, tmp_model):
        model_dir = tmp_model([])
        suite = run_tests_from_model(model_dir)
        assert suite.model_path == model_dir

    def test_suite_counts_match_results(self, tmp_model):
        model_dir = tmp_model(
            [{"suite_name": "Suite.A", "source": "EVALUATE ROW(\"x\", 1)"}]
        )
        conn = ResolvedXmlaConnection(server=_MOCK_PORTFILE_SERVER, catalog="M")
        rows = [{"TestName": "t1", "Expected": "1", "Actual": "1", "Passed": "true"}]
        with patch("pql_test_runner._execute_dax_query", return_value=rows):
            with patch(
                "pql_test_runner.resolve_xmla_connection", return_value=conn
            ):
                suite = run_tests_from_model(model_dir)
        assert suite.total == len(suite.results)
        assert suite.total == suite.passed + suite.failed

    def test_filters_to_named_test(self, tmp_model):
        model_dir = tmp_model(
            [
                {"suite_name": "Suite.A", "source": "EVALUATE ROW(\"x\",1)"},
                {"suite_name": "Suite.B", "source": "EVALUATE ROW(\"y\",2)"},
            ]
        )
        conn = ResolvedXmlaConnection(server=_MOCK_PORTFILE_SERVER, catalog="M")
        rows = [{"TestName": "t1", "Expected": "1", "Actual": "1", "Passed": "true"}]
        with patch("pql_test_runner._execute_dax_query", return_value=rows):
            with patch(
                "pql_test_runner.resolve_xmla_connection", return_value=conn
            ):
                suite = run_tests_from_model(model_dir, test_name="Suite.A.Tests")
        assert len(suite.tests) == 1
        assert suite.tests[0].name == "Suite.A.Tests"

    def test_returns_failed_suite_when_named_test_not_found(self, tmp_model):
        model_dir = tmp_model([])
        suite = run_tests_from_model(model_dir, test_name="Missing.Tests")
        assert suite.total == 0
        assert suite.tests == []


# ---------------------------------------------------------------------------
# get_pbi_files_opened — mirrors Pester "Should run tests locally" setup
# ---------------------------------------------------------------------------

class TestGetPbiFilesOpened:
    """
    Unit tests for get_pbi_files_opened().

    Mirrors the Pester 'Should run tests locally' setup: enumerates open
    Power BI Desktop windows via ctypes EnumWindows, finds msmdsrv.exe child
    processes via psutil, and verifies connectivity via EVALUATE INFO.VIEW.MEASURES().
    """

    def test_raises_import_error_when_psutil_unavailable(self):
        """Mirrors Pester: meaningful error when prerequisite is missing."""
        import pql_test_runner as runner
        original = runner.HAS_PSUTIL
        try:
            runner.HAS_PSUTIL = False
            with pytest.raises(ImportError, match="psutil"):
                get_pbi_files_opened()
        finally:
            runner.HAS_PSUTIL = original

    def test_returns_empty_list_when_no_pbi_windows_found(self):
        """
        No PBI Desktop open → empty list.
        Mirrors Pester: no results when model is not running locally.
        """
        if not HAS_PSUTIL:
            pytest.skip("psutil not installed")
        with patch("pql_test_runner._get_pbi_process_window_titles", return_value={}):
            result = get_pbi_files_opened()
        assert result == []

    def test_returns_instance_for_running_model(self):
        """
        Mirrors Pester 'Should run tests locally': one PBI Desktop open
        with SampleModel → one LocalPbiInstance found on expected port.
        Port is dynamic (PBI Desktop allocates a random ephemeral port each
        session), so assertions derive from the mock input, not a magic number.
        """
        if not HAS_PSUTIL:
            pytest.skip("psutil not installed")
        port = _MOCK_AS_PORT_A
        fake_proc = _make_mock_process(pid=999, name="msmdsrv.exe", ppid=1234, listen_port=port)
        with (
            patch(
                "pql_test_runner._get_pbi_process_window_titles",
                return_value={1234: "SampleModel - Power BI Desktop"},
            ),
            patch("pql_test_runner._psutil.process_iter", return_value=[fake_proc]),
            patch(
                "pql_test_runner._get_catalog_from_local_port",
                return_value="",  # EVALUATE INFO.VIEW.MEASURES() succeeded; no catalog needed
            ),
        ):
            instances = get_pbi_files_opened()
        assert len(instances) == 1
        assert instances[0].model_name == "SampleModel"
        assert instances[0].server == f"localhost:{port}"  # derived from mock, not hardcoded
        assert instances[0].catalog == ""  # local: no Initial Catalog; AS auto-selects

    def test_model_name_strips_power_bi_desktop_suffix(self):
        """
        Window title ' - Power BI Desktop' suffix is stripped.
        Mirrors Invoke-DQVTesting's $Model = $title.Replace(' - Power BI Desktop', '').
        """
        if not HAS_PSUTIL:
            pytest.skip("psutil not installed")
        fake_proc = _make_mock_process(pid=100, name="msmdsrv.exe", ppid=200, listen_port=12345)
        with (
            patch(
                "pql_test_runner._get_pbi_process_window_titles",
                return_value={200: "My Report Name - Power BI Desktop"},
            ),
            patch("pql_test_runner._psutil.process_iter", return_value=[fake_proc]),
            patch("pql_test_runner._get_catalog_from_local_port", return_value="My Report Name"),
        ):
            instances = get_pbi_files_opened()
        assert len(instances) == 1
        assert instances[0].model_name == "My Report Name"

    def test_returns_multiple_instances_for_multiple_models(self):
        """
        Mirrors Pester: multiple models open → results for each.
        Checks that results have IsTestResult > 0 per model.
        """
        if not HAS_PSUTIL:
            pytest.skip("psutil not installed")
        proc_a = _make_mock_process(pid=10, name="msmdsrv.exe", ppid=100, listen_port=_MOCK_AS_PORT_A)
        proc_b = _make_mock_process(pid=20, name="msmdsrv.exe", ppid=200, listen_port=_MOCK_AS_PORT_B)
        with (
            patch(
                "pql_test_runner._get_pbi_process_window_titles",
                return_value={
                    100: "ModelA - Power BI Desktop",
                    200: "ModelB - Power BI Desktop",
                },
            ),
            patch("pql_test_runner._psutil.process_iter", return_value=[proc_a, proc_b]),
            patch("pql_test_runner._get_catalog_from_local_port", side_effect=["", ""]),
        ):
            instances = get_pbi_files_opened()
        assert len(instances) == 2
        names = {i.model_name for i in instances}
        assert names == {"ModelA", "ModelB"}

    def test_ignores_non_msmdsrv_processes(self):
        """Only msmdsrv.exe processes are candidates — other processes are ignored."""
        if not HAS_PSUTIL:
            pytest.skip("psutil not installed")
        other_proc = _make_mock_process(pid=50, name="PBIDesktop.exe", ppid=0, listen_port=9999)
        with (
            patch(
                "pql_test_runner._get_pbi_process_window_titles",
                return_value={0: "SomeModel - Power BI Desktop"},
            ),
            patch("pql_test_runner._psutil.process_iter", return_value=[other_proc]),
        ):
            instances = get_pbi_files_opened()
        assert instances == []

    def test_skips_process_with_access_denied(self):
        """
        Mirrors Invoke-DQVTesting error handling: AccessDenied is silently skipped,
        not raised — so other models can still be enumerated.
        """
        if not HAS_PSUTIL:
            pytest.skip("psutil not installed")
        import pql_test_runner as runner
        bad_proc = MagicMock()
        bad_proc.info = {"pid": 99, "name": "msmdsrv.exe", "ppid": 1234}
        bad_proc.net_connections.side_effect = runner._psutil.AccessDenied(pid=99)
        with (
            patch(
                "pql_test_runner._get_pbi_process_window_titles",
                return_value={1234: "LockedModel - Power BI Desktop"},
            ),
            patch("pql_test_runner._psutil.process_iter", return_value=[bad_proc]),
        ):
            instances = get_pbi_files_opened()
        assert instances == []

    def test_falls_back_to_empty_catalog_when_connectivity_check_fails(self):
        """
        When the EVALUATE INFO.VIEW.MEASURES() connectivity check fails
        (returns None), catalog falls back to empty string so the connection
        string omits Initial Catalog and lets AS auto-select the database.
        """
        if not HAS_PSUTIL:
            pytest.skip("psutil not installed")
        fake_proc = _make_mock_process(pid=30, name="msmdsrv.exe", ppid=300, listen_port=54321)
        with (
            patch(
                "pql_test_runner._get_pbi_process_window_titles",
                return_value={300: "FallbackModel - Power BI Desktop"},
            ),
            patch("pql_test_runner._psutil.process_iter", return_value=[fake_proc]),
            patch("pql_test_runner._get_catalog_from_local_port", return_value=None),
        ):
            instances = get_pbi_files_opened()
        assert len(instances) == 1
        assert instances[0].catalog == ""  # empty: omit Initial Catalog in connection string


# ---------------------------------------------------------------------------
# resolve_local_xmla_connection — mirrors Pester -Local flag tests
# ---------------------------------------------------------------------------

class TestResolveLocalXmlaConnection:
    """
    Unit tests for resolve_local_xmla_connection().

    Mirrors Pester's '-Local' tag tests:
    - 'Should run tests locally' — correct model open → connection returned
    - 'Should warn about no test because path does not have tests for currently opened file'
      maps to None/warning when model is not found
    - 'Should run tests for a subset based on folder path' — filtered test subsets
    """

    def _make_instance(self, model_name: str, port: int = _MOCK_AS_PORT_A) -> LocalPbiInstance:
        return LocalPbiInstance(
            model_name=model_name,
            server=f"localhost:{port}",
            catalog=f"{model_name}-GUID",
        )

    def test_returns_connection_for_matching_model(self, tmp_path):
        """
        Mirrors 'Should run tests locally': SampleModel open → connection returned,
        no warnings (warnings.Length == 0 in Pester).
        Server and catalog are derived from the mock instance, not hardcoded,
        because the AS port is dynamically allocated by PBI Desktop.
        """
        (tmp_path / "SampleModel.pbip").write_text("{}")
        inst = self._make_instance("SampleModel")
        with patch("pql_test_runner.get_pbi_files_opened", return_value=[inst]):
            conn = resolve_local_xmla_connection(str(tmp_path))
        assert conn is not None
        assert conn.server == inst.server    # dynamic: derived from the detected instance
        assert conn.catalog == inst.catalog  # dynamic: derived from the detected instance

    def test_returns_none_when_no_pbi_instances_running(self, tmp_path):
        """
        Mirrors Pester: result for model whose path has no running PBI Desktop.
        The model-specific warning ('No matching Power BI Desktop instance found')
        is produced by the caller (CLI/runner), not by this function.
        """
        (tmp_path / "SampleModel.pbip").write_text("{}")
        with (
            patch("pql_test_runner.get_pbi_files_opened", return_value=[]),
            patch("pql_test_runner._detect_local_pbi_desktop_port", return_value=None),
        ):
            conn = resolve_local_xmla_connection(str(tmp_path))
        assert conn is None

    def test_returns_none_when_different_model_is_open(self, tmp_path):
        """
        Mirrors Pester 'Should warn about no test because path does not have tests
        for currently opened file': a different model is open, so no match → None.
        """
        (tmp_path / "SampleModel.pbip").write_text("{}")
        instances = [self._make_instance("OtherModel")]
        with patch("pql_test_runner.get_pbi_files_opened", return_value=instances):
            conn = resolve_local_xmla_connection(str(tmp_path))
        assert conn is None

    def test_matching_is_case_insensitive(self, tmp_path):
        """Model name match is case-insensitive (mirrors PowerShell -eq behaviour)."""
        (tmp_path / "samplemodel.pbip").write_text("{}")
        instances = [self._make_instance("SAMPLEMODEL")]
        with patch("pql_test_runner.get_pbi_files_opened", return_value=instances):
            conn = resolve_local_xmla_connection(str(tmp_path))
        assert conn is not None

    def test_uses_first_instance_when_no_pbip_file(self, tmp_path):
        """
        When no .pbip file exists (path has no model stem) the first detected
        instance is used — mirrors the 'open any model' convenience fallback.
        Server is derived from the mock instance rather than hardcoded.
        """
        # tmp_path has no .pbip file
        inst = self._make_instance("AnyOpenModel", port=_MOCK_AS_PORT_B)
        with patch("pql_test_runner.get_pbi_files_opened", return_value=[inst]):
            conn = resolve_local_xmla_connection(str(tmp_path))
        assert conn is not None
        assert conn.server == inst.server  # dynamic: derived from the detected instance

    def test_falls_back_to_port_file_when_psutil_unavailable(self, tmp_path):
        """
        When psutil raises ImportError the port-file fallback is used.
        Mirrors Invoke-DQVTesting running on a machine without psutil installed.
        Port is provided by the mock fallback; catalog is empty (AS auto-selects).
        """
        fallback_server = f"localhost:{_MOCK_AS_PORT_A}"
        (tmp_path / "MyModel.pbip").write_text("{}")
        with (
            patch(
                "pql_test_runner.get_pbi_files_opened",
                side_effect=ImportError("psutil not installed"),
            ),
            patch(
                "pql_test_runner._detect_local_pbi_desktop_port",
                return_value=fallback_server,
            ),
        ):
            conn = resolve_local_xmla_connection(str(tmp_path))
        assert conn is not None
        assert conn.server == fallback_server  # dynamic: derived from fallback mock
        assert conn.catalog == ""  # local: no Initial Catalog; AS auto-selects

    def test_falls_back_to_port_file_from_semantic_model_path(self, tmp_path):
        """
        When given the .SemanticModel directory directly (no .pbip in that dir),
        the port-file fallback is used; catalog is empty (AS auto-selects).
        """
        fallback_server = f"localhost:{_MOCK_AS_PORT_A}"
        semantic_dir = tmp_path / "SampleModel.SemanticModel"
        semantic_dir.mkdir()
        with (
            patch(
                "pql_test_runner.get_pbi_files_opened",
                side_effect=ImportError("psutil not installed"),
            ),
            patch(
                "pql_test_runner._detect_local_pbi_desktop_port",
                return_value=fallback_server,
            ),
        ):
            conn = resolve_local_xmla_connection(str(semantic_dir))
        assert conn is not None
        assert conn.server == fallback_server
        assert conn.catalog == ""  # local: no Initial Catalog; AS auto-selects

    @pytest.mark.live
    def test_runs_full_suite_from_sample_model_when_pbi_open(self, sample_model_path):
        """
        Integration-style test mirroring Pester 'Should run tests locally'.

        Detects the real Analysis Services port from a running PBI Desktop;
        skips when no PBI Desktop instance is found (mirrors the Pester
        requirement 'Make sure SampleModel is open' before running the test).
        The actual XMLA query is mocked so no real connection is made.
        Checks: testResults.Length > 0 and no unexpected errors.
        """
        # Dynamically detect the real AS port — PBI Desktop picks a random
        # ephemeral port each time it starts, so we cannot hardcode it.
        real_server = _detect_local_pbi_desktop_port()
        if real_server is None:
            pytest.skip("PBI Desktop with SampleModel must be open to run this test")

        instances = [LocalPbiInstance(
            model_name="SampleModel",
            server=real_server,      # dynamic: actual port from the running instance
            catalog="SampleModel",
        )]
        rows = [
            {"TestName": "check 1", "Expected": "1", "Actual": "1", "Passed": "true"},
            {"TestName": "check 2", "Expected": "foo", "Actual": "foo", "Passed": "true"},
        ]
        with (
            patch("pql_test_runner.get_pbi_files_opened", return_value=instances),
            patch("pql_test_runner._execute_dax_query", return_value=rows),
        ):
            conn = resolve_local_xmla_connection(sample_model_path)
            assert conn is not None
            assert conn.server == real_server  # propagated correctly
            suite = run_tests_from_model(sample_model_path, connection=conn)

        # Mirrors: $testResults.Length | Should -BeGreaterThan 0
        assert suite.total > 0
        # Mirrors: $warnings.Length | Should -Be 0 (no failures)
        failures = [r for r in suite.results if not r.passed]
        assert len(failures) == 0

    def test_warns_when_no_dax_test_files_found(self, tmp_path):
        """
        Mirrors Pester 'Should warn about no test because path does not have tests
        for currently opened file': The model has no *.Tests.dax files — the TestSuite
        should have total == 0 and the result-set is empty (warning emitted by CLI).
        Server is derived from the mock instance, not hardcoded, because PBI Desktop
        allocates a random port dynamically.
        """
        (tmp_path / "SampleModel.pbip").write_text("{}")
        (tmp_path / "SampleModel.SemanticModel" / "DAXQueries").mkdir(parents=True)
        # Use _make_instance so the port comes from the shared mock constant
        inst = LocalPbiInstance(
            model_name="SampleModel",
            server=f"localhost:{_MOCK_AS_PORT_A}",
            catalog="SampleModel",
        )
        with patch("pql_test_runner.get_pbi_files_opened", return_value=[inst]):
            conn = resolve_local_xmla_connection(str(tmp_path))
        assert conn is not None  # connection resolved fine
        assert conn.server == inst.server  # dynamic: derived from the instance

        suite = run_tests_from_model(str(tmp_path), connection=conn)
        # No *.Tests.dax files → total == 0, like Pester $warnings.Length > 0
        assert suite.total == 0
        assert suite.tests == []
