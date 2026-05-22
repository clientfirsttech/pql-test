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

from pql_test.runner import (
    HAS_PSUTIL,
    HAS_PYADOMD,
    Environment,
    LocalPbiInstance,
    ModelIdentifier,
    PqlTest,
    ResolvedXmlaConnection,
    TestResult,
    XmlaConnectionOptions,
    _collect_dax_test_files,
    _detect_local_pbi_desktop_port,
    _find_pbi_ancestor_pid,
    _find_pbip_file,
    _find_semantic_model_dir,
    get_pbi_files_opened,
    parse_model_identifier,
    resolve_local_xmla_connection,
    resolve_local_xmla_connection_by_name,
    resolve_service_xmla_connection_by_name,
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
# _find_pbi_ancestor_pid
# ---------------------------------------------------------------------------

class TestFindPbiAncestorPid:
    """
    Unit tests for the process-tree walking helper that maps msmdsrv.exe
    to its PBIDesktop.exe ancestor across an arbitrary number of intermediate
    host processes.
    """

    def _make_psutil_process(self, pid: int, ppid: int) -> MagicMock:
        """Minimal mock that supports .ppid() and psutil exceptions."""
        from pql_test import runner
        proc = MagicMock()
        proc.ppid.return_value = ppid
        proc.pid = pid
        return proc

    def test_returns_immediate_parent_when_direct_child(self):
        """msmdsrv.exe is a direct child of PBIDesktop.exe."""
        if not HAS_PSUTIL:
            pytest.skip("psutil not installed")
        from pql_test import runner

        pbi_pid = 100
        msmdsrv_proc = self._make_psutil_process(pid=999, ppid=pbi_pid)

        with patch("pql_test.runner._psutil.Process", side_effect=lambda pid: self._make_psutil_process(pid, 0)):
            result = _find_pbi_ancestor_pid(msmdsrv_proc, {pbi_pid})

        assert result == pbi_pid

    def test_returns_grandparent_when_one_intermediate_process(self):
        """
        msmdsrv.exe → intermediate host → PBIDesktop.exe
        The tree walk must traverse the intermediate process and still find
        the PBI ancestor.
        """
        if not HAS_PSUTIL:
            pytest.skip("psutil not installed")

        pbi_pid = 100
        intermediate_pid = 200
        # msmdsrv parent is the intermediate process
        msmdsrv_proc = self._make_psutil_process(pid=999, ppid=intermediate_pid)
        # intermediate's parent is PBIDesktop
        intermediate_proc = self._make_psutil_process(pid=intermediate_pid, ppid=pbi_pid)

        from pql_test import runner

        def _process_factory(pid: int) -> MagicMock:
            if pid == intermediate_pid:
                return intermediate_proc
            return self._make_psutil_process(pid, 0)  # top-level / unknown

        with patch("pql_test.runner._psutil.Process", side_effect=_process_factory):
            result = _find_pbi_ancestor_pid(msmdsrv_proc, {pbi_pid})

        assert result == pbi_pid

    def test_returns_none_when_no_pbi_ancestor_exists(self):
        """
        Process chain has no PBI Desktop ancestor — should return None without
        raising an exception.
        """
        if not HAS_PSUTIL:
            pytest.skip("psutil not installed")

        unrelated_pid = 50
        proc = self._make_psutil_process(pid=999, ppid=unrelated_pid)
        top_proc = self._make_psutil_process(pid=unrelated_pid, ppid=0)

        with patch("pql_test.runner._psutil.Process", return_value=top_proc):
            result = _find_pbi_ancestor_pid(proc, {1234})

        assert result is None

    def test_handles_no_such_process_gracefully(self):
        """
        If any process in the chain has already exited, NoSuchProcess is caught
        and None is returned instead of propagating.
        """
        if not HAS_PSUTIL:
            pytest.skip("psutil not installed")
        from pql_test import runner

        proc = self._make_psutil_process(pid=999, ppid=50)
        proc.ppid.side_effect = runner._psutil.NoSuchProcess(pid=999)

        result = _find_pbi_ancestor_pid(proc, {100})
        assert result is None


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
            patch("pql_test.runner._acquire_service_principal_token", return_value="fake-token"),
            patch("pql_test.runner._resolve_pbi_workspace_and_dataset_names", return_value=("ws-1", "ds-1")),
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
            patch("pql_test.runner._acquire_service_principal_token", return_value="fake-token"),
            patch("pql_test.runner._resolve_pbi_workspace_and_dataset_names", return_value=("w", "d")),
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
            patch("pql_test.runner._acquire_service_principal_token", return_value="fake-token"),
            patch("pql_test.runner._resolve_pbi_workspace_and_dataset_names", return_value=("ws-1", "ds-1")),
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
            patch("pql_test.runner.get_pbi_files_opened", return_value=[]),
            patch("pql_test.runner._detect_local_pbi_desktop_port", return_value=None),
        ):
            conn = resolve_xmla_connection(str(tmp_path), opts)
        assert conn is None

    def test_returns_local_connection_when_pbi_desktop_running(self, tmp_path):
        (tmp_path / "MyModel.pbip").write_text("{}")
        opts = XmlaConnectionOptions()
        with (
            patch("pql_test.runner.get_pbi_files_opened", return_value=[]),
            patch(
                "pql_test.runner._detect_local_pbi_desktop_port",
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
            patch("pql_test.runner.get_pbi_files_opened", return_value=[]),
            patch(
                "pql_test.runner._detect_local_pbi_desktop_port",
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
            patch("pql_test.runner._acquire_service_principal_token", return_value="fake-token"),
            patch("pql_test.runner._resolve_pbi_workspace_and_dataset_names", return_value=("w", "d")),
            patch(
                "pql_test.runner._detect_local_pbi_desktop_port",
                return_value=_MOCK_PORTFILE_SERVER,  # port is irrelevant; remote URL takes priority
            ),
        ):
            conn = resolve_xmla_connection(str(tmp_path), opts)
        assert conn is not None
        assert "powerbi://api.powerbi.com" in conn.server

    def test_requires_all_three_remote_params(self, tmp_path):
        # Missing dataset_id — should not produce a remote connection.
        # Also suppress local fallback so a running PBI Desktop doesn't interfere.
        opts = XmlaConnectionOptions(tenant_id="t", workspace_id="w")
        with (
            patch("pql_test.runner.get_pbi_files_opened", return_value=[]),
            patch("pql_test.runner._detect_local_pbi_desktop_port", return_value=None),
        ):
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
        with patch("pql_test.runner._execute_dax_query", return_value=rows):
            results = run_test(self._make_test(), self._make_conn())
        assert len(results) == 1
        assert results[0].passed is True

    def test_passes_when_passed_column_is_1(self):
        rows = [{"TestName": "t", "Expected": "x", "Actual": "x", "Passed": "1"}]
        with patch("pql_test.runner._execute_dax_query", return_value=rows):
            results = run_test(self._make_test(), self._make_conn())
        assert results[0].passed is True

    def test_fails_when_passed_column_is_false(self):
        rows = [{"TestName": "Bad test", "Expected": "1", "Actual": "2", "Passed": "false"}]
        with patch("pql_test.runner._execute_dax_query", return_value=rows):
            results = run_test(self._make_test(), self._make_conn())
        assert results[0].passed is False

    def test_test_name_used_from_row(self):
        rows = [{"TestName": "MyRowTest", "Expected": "1", "Actual": "1", "Passed": "true"}]
        with patch("pql_test.runner._execute_dax_query", return_value=rows):
            results = run_test(self._make_test(), self._make_conn())
        assert results[0].test_name == "MyRowTest"

    def test_falls_back_to_suite_name_when_test_name_empty(self):
        rows = [{"TestName": "", "Expected": "1", "Actual": "1", "Passed": "true"}]
        with patch("pql_test.runner._execute_dax_query", return_value=rows):
            results = run_test(self._make_test(), self._make_conn())
        assert results[0].test_name == "Calculations.DEV.Tests"

    def test_handles_multiple_assertion_rows(self):
        rows = [
            {"TestName": "t1", "Expected": "1", "Actual": "1", "Passed": "true"},
            {"TestName": "t2", "Expected": "2", "Actual": "3", "Passed": "false"},
        ]
        with patch("pql_test.runner._execute_dax_query", return_value=rows):
            results = run_test(self._make_test(), self._make_conn())
        assert len(results) == 2
        assert results[0].passed is True
        assert results[1].passed is False

    def test_message_includes_expected_and_actual(self):
        rows = [{"TestName": "t", "Expected": "42", "Actual": "99", "Passed": "false"}]
        with patch("pql_test.runner._execute_dax_query", return_value=rows):
            results = run_test(self._make_test(), self._make_conn())
        assert results[0].expected == "42"
        assert results[0].actual == "99"
        assert "42" in results[0].message
        assert "99" in results[0].message

    def test_suite_name_populated_from_test_name(self):
        rows = [{"TestName": "t1", "Expected": "1", "Actual": "1", "Passed": "true"}]
        with patch("pql_test.runner._execute_dax_query", return_value=rows):
            results = run_test(self._make_test(), self._make_conn())
        assert results[0].suite_name == "Calculations.DEV.Tests"

    def test_suite_name_set_when_no_connection(self):
        results = run_test(self._make_test(), connection=None)
        assert results[0].suite_name == "Calculations.DEV.Tests"

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
        with patch("pql_test.runner._execute_dax_query", return_value=rows):
            results = run_test(self._make_test(), self._make_conn())
        assert "Rule: Avoid SELECT *" in results[0].message

    def test_returns_failed_result_on_empty_rows(self):
        with patch("pql_test.runner._execute_dax_query", return_value=[]):
            results = run_test(self._make_test(), self._make_conn())
        assert len(results) == 1
        assert results[0].passed is False
        assert "no rows" in results[0].message.lower()

    def test_returns_failed_result_on_query_exception(self):
        with patch(
            "pql_test.runner._execute_dax_query",
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
        with patch("pql_test.runner._execute_dax_query", return_value=rows):
            results = run_test(self._make_test(), self._make_conn())
        assert results[0].passed is True
        assert results[0].test_name == "t1"

    def test_role_name_applied_as_roles_for_local_connection(self):
        """
        Local connection + PqlTest.role_name →  Roles= in the connection string.
        This is the fix for the "not a properly formed account name" error that
        occurs when trying to use an AAD UPN with EffectiveUserName against a
        local PBI Desktop Analysis Services instance.
        """
        test = PqlTest(
            name="RLS.ANY.Tests",
            file_path="",
            source="EVALUATE RLS.ANY.Tests()",
            impersonated_user_name="west@contoso.com",
            role_name="West",
        )
        rows = [{"TestName": "West test", "Expected": "0", "Actual": "0", "Passed": "true"}]

        captured: list[ResolvedXmlaConnection] = []

        def _capture_conn(conn, _query):
            captured.append(conn)
            return rows

        # _make_conn() returns localhost:50001 — a local connection
        with patch("pql_test.runner._execute_dax_query", side_effect=_capture_conn):
            result = run_test(test, self._make_conn())

        assert len(result) == 1
        assert result[0].passed is True
        assert len(captured) == 1
        assert captured[0].roles == "West"
        assert captured[0].effective_user_name is None

    def test_impersonated_user_applied_as_effective_user_name_for_service_connection(self):
        """
        Service connection + PqlTest.impersonated_user_name → EffectiveUserName=
        in the connection string (AAD UPN works against XMLA endpoints).
        """
        test = PqlTest(
            name="RLS.ANY.Tests",
            file_path="",
            source="EVALUATE RLS.ANY.Tests()",
            impersonated_user_name="west@contoso.com",
            role_name="West",
        )
        rows = [{"TestName": "t", "Expected": "0", "Actual": "0", "Passed": "true"}]
        service_conn = ResolvedXmlaConnection(
            server="powerbi://api.powerbi.com/v1.0/myorg/MyWorkspace",
            catalog="RLS_Model",
        )

        captured: list[ResolvedXmlaConnection] = []

        def _capture_conn(conn, _query):
            captured.append(conn)
            return rows

        with patch("pql_test.runner._execute_dax_query", side_effect=_capture_conn):
            result = run_test(test, service_conn)

        assert result[0].passed is True
        assert captured[0].effective_user_name == "west@contoso.com"
        assert captured[0].roles is None

    def test_no_rls_applied_when_role_name_absent_on_local_connection(self):
        """
        Local connection + impersonated_user_name only (no role_name) → no
        impersonation applied.  This avoids crashing with an invalid UPN.
        """
        test = PqlTest(
            name="RLS.ANY.Tests",
            file_path="",
            source="EVALUATE RLS.ANY.Tests()",
            impersonated_user_name="west@contoso.com",
            role_name=None,
        )
        rows = [{"TestName": "t", "Expected": "0", "Actual": "0", "Passed": "true"}]

        captured: list[ResolvedXmlaConnection] = []

        def _capture_conn(conn, _query):
            captured.append(conn)
            return rows

        with patch("pql_test.runner._execute_dax_query", side_effect=_capture_conn):
            run_test(test, self._make_conn())

        assert captured[0].roles is None
        assert captured[0].effective_user_name is None

    def test_no_effective_user_name_when_impersonation_not_set(self):
        """Without impersonated_user_name the connection is used unchanged."""
        test = PqlTest(
            name="Schema.DEV.Tests",
            file_path="",
            source="EVALUATE Schema.DEV.Tests()",
            impersonated_user_name=None,
        )
        rows = [{"TestName": "t", "Expected": "1", "Actual": "1", "Passed": "true"}]

        captured: list[ResolvedXmlaConnection] = []

        def _capture_conn(conn, _query):
            captured.append(conn)
            return rows

        with patch("pql_test.runner._execute_dax_query", side_effect=_capture_conn):
            run_test(test, self._make_conn())

        assert captured[0].effective_user_name is None
        assert captured[0].roles is None

    def test_rls_does_not_mutate_original_connection(self):
        """
        The per-test Roles= connection must be a copy; the original connection
        object must remain unmodified so other tests in the same suite are unaffected.
        """
        test = PqlTest(
            name="RLS.ANY.Tests",
            file_path="",
            source="EVALUATE RLS.ANY.Tests()",
            impersonated_user_name="west@contoso.com",
            role_name="West",
        )
        rows = [{"TestName": "t", "Expected": "0", "Actual": "0", "Passed": "true"}]
        original_conn = self._make_conn()

        with patch("pql_test.runner._execute_dax_query", return_value=rows):
            run_test(test, original_conn)

        assert original_conn.roles is None
        assert original_conn.effective_user_name is None


# ---------------------------------------------------------------------------
# _build_connection_string — RLS overrides (Roles= and EffectiveUserName=)
# ---------------------------------------------------------------------------

class TestBuildConnectionStringEffectiveUserName:
    """Unit tests for the EffectiveUserName connection string path."""

    def test_effective_user_name_appended_to_connection_string(self):
        from pql_test.runner import _build_connection_string
        conn = ResolvedXmlaConnection(
            server="powerbi://api.powerbi.com/v1.0/myorg/WS",
            catalog="RLS_Model",
            effective_user_name="west@contoso.com",
        )
        cs = _build_connection_string(conn)
        assert "EffectiveUserName=west@contoso.com;" in cs

    def test_no_effective_user_name_field_absent(self):
        from pql_test.runner import _build_connection_string
        conn = ResolvedXmlaConnection(server="localhost:50001", catalog="RLS_Model")
        cs = _build_connection_string(conn)
        assert "EffectiveUserName" not in cs

    def test_effective_user_name_not_added_when_token_auth(self):
        """Bearer token auth takes priority; EffectiveUserName is not added."""
        from pql_test.runner import _build_connection_string
        conn = ResolvedXmlaConnection(
            server="powerbi://api.powerbi.com/v1.0/myorg/WS",
            catalog="RLS_Model",
            access_token="tok123",
            effective_user_name="west@contoso.com",
        )
        cs = _build_connection_string(conn)
        assert "EffectiveUserName" not in cs
        assert "Password=tok123;" in cs

    def test_roles_appended_to_connection_string(self):
        """Roles= property is added for local connections using named-role RLS."""
        from pql_test.runner import _build_connection_string
        conn = ResolvedXmlaConnection(
            server="localhost:50001",
            catalog="RLS_Model",
            roles="West",
        )
        cs = _build_connection_string(conn)
        assert "Roles=West;" in cs
        assert "EffectiveUserName" not in cs

    def test_roles_takes_priority_over_effective_user_name(self):
        """When both Roles and EffectiveUserName are set, Roles= wins."""
        from pql_test.runner import _build_connection_string
        conn = ResolvedXmlaConnection(
            server="localhost:50001",
            catalog="RLS_Model",
            roles="West",
            effective_user_name="west@contoso.com",
        )
        cs = _build_connection_string(conn)
        assert "Roles=West;" in cs
        assert "EffectiveUserName" not in cs

    def test_roles_not_added_when_token_auth(self):
        """Bearer token auth takes priority; Roles= is not added."""
        from pql_test.runner import _build_connection_string
        conn = ResolvedXmlaConnection(
            server="localhost:50001",
            catalog="RLS_Model",
            access_token="tok123",
            roles="West",
        )
        cs = _build_connection_string(conn)
        assert "Roles" not in cs
        assert "Password=tok123;" in cs


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
        with patch("pql_test.runner._execute_dax_query", return_value=rows):
            results = run_tests(tests, connection=conn)
        assert len(results) == 2


# ---------------------------------------------------------------------------
# run_tests_from_model
# ---------------------------------------------------------------------------

class TestRunTestsFromModel:
    def test_returns_empty_suite_for_nonexistent_model(self):
        # Suppress local auto-detection so a running PBI Desktop doesn't cause
        # live discovery on a nonexistent path.
        with patch("pql_test.runner.resolve_xmla_connection", return_value=None):
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
        with patch("pql_test.runner._execute_dax_query", return_value=rows):
            with patch(
                "pql_test.runner.resolve_xmla_connection", return_value=conn
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
        exec_rows = [{"TestName": "t1", "Expected": "1", "Actual": "1", "Passed": "true"}]
        # _retrieve_tests_via_dax returns None → falls back to file scan so
        # the discovery mock doesn't conflict with the execution mock.
        with (
            patch("pql_test.runner._retrieve_tests_via_dax", return_value=None),
            patch("pql_test.runner._execute_dax_query", return_value=exec_rows),
            patch("pql_test.runner.resolve_xmla_connection", return_value=conn),
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
        from pql_test import runner
        original = runner.HAS_PSUTIL
        try:
            runner.HAS_PSUTIL = False
            with pytest.raises(ImportError, match="psutil"):
                get_pbi_files_opened()
        finally:
            runner.HAS_PSUTIL = original

    def test_returns_empty_list_when_no_pbi_windows_found(self):
        """
        No PBI Desktop open at all — no windows AND no msmdsrv processes → empty list.
        Mirrors Pester: no results when model is not running locally.
        """
        if not HAS_PSUTIL:
            pytest.skip("psutil not installed")
        with (
            patch("pql_test.runner._get_pbi_process_window_titles", return_value={}),
            patch("pql_test.runner._psutil.process_iter", return_value=[]),
            patch("pql_test.runner._psutil.net_connections", return_value=[]),
        ):
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
                "pql_test.runner._get_pbi_process_window_titles",
                return_value={1234: "SampleModel - Power BI Desktop"},
            ),
            patch("pql_test.runner._psutil.process_iter", return_value=[fake_proc]),
            patch(
                "pql_test.runner._get_catalog_from_local_port",
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
                "pql_test.runner._get_pbi_process_window_titles",
                return_value={200: "My Report Name - Power BI Desktop"},
            ),
            patch("pql_test.runner._psutil.process_iter", return_value=[fake_proc]),
            patch("pql_test.runner._get_catalog_from_local_port", return_value="My Report Name"),
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
                "pql_test.runner._get_pbi_process_window_titles",
                return_value={
                    100: "ModelA - Power BI Desktop",
                    200: "ModelB - Power BI Desktop",
                },
            ),
            patch("pql_test.runner._psutil.process_iter", return_value=[proc_a, proc_b]),
            patch("pql_test.runner._get_catalog_from_local_port", side_effect=["", ""]),
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
                "pql_test.runner._get_pbi_process_window_titles",
                return_value={0: "SomeModel - Power BI Desktop"},
            ),
            patch("pql_test.runner._psutil.process_iter", return_value=[other_proc]),
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
        from pql_test import runner
        bad_proc = MagicMock()
        bad_proc.info = {"pid": 99, "name": "msmdsrv.exe", "ppid": 1234}
        bad_proc.net_connections.side_effect = runner._psutil.AccessDenied(pid=99)
        with (
            patch(
                "pql_test.runner._get_pbi_process_window_titles",
                return_value={1234: "LockedModel - Power BI Desktop"},
            ),
            patch("pql_test.runner._psutil.process_iter", return_value=[bad_proc]),
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
                "pql_test.runner._get_pbi_process_window_titles",
                return_value={300: "FallbackModel - Power BI Desktop"},
            ),
            patch("pql_test.runner._psutil.process_iter", return_value=[fake_proc]),
            patch("pql_test.runner._get_catalog_from_local_port", return_value=None),
        ):
            instances = get_pbi_files_opened()
        assert len(instances) == 1
        assert instances[0].catalog == ""  # empty: omit Initial Catalog in connection string

    def test_conn_listen_string_status_is_accepted(self):
        """
        psutil 6+ removed the CONN_LISTEN constant and uses the plain string
        "LISTEN" instead.  Verify that get_pbi_files_opened() still discovers
        the port when conn.status is already the expected string.
        """
        if not HAS_PSUTIL:
            pytest.skip("psutil not installed")
        port = _MOCK_AS_PORT_A
        # Build a mock connection whose status is the string "LISTEN" (not
        # the psutil constant), which is what psutil 6+ returns.
        conn = MagicMock()
        conn.status = "LISTEN"
        conn.laddr = MagicMock()
        conn.laddr.ip = "127.0.0.1"
        conn.laddr.port = port

        fake_proc = MagicMock()
        fake_proc.info = {"pid": 999, "name": "msmdsrv.exe", "ppid": 1234}
        fake_proc.net_connections.return_value = [conn]

        with (
            patch(
                "pql_test.runner._get_pbi_process_window_titles",
                return_value={1234: "StringListenModel - Power BI Desktop"},
            ),
            patch("pql_test.runner._psutil.process_iter", return_value=[fake_proc]),
            patch("pql_test.runner._get_catalog_from_local_port", return_value=""),
        ):
            instances = get_pbi_files_opened()

        assert len(instances) == 1
        assert instances[0].model_name == "StringListenModel"
        assert instances[0].server == f"localhost:{port}"

    def test_tree_walk_finds_model_via_intermediate_process(self):
        """
        Modern Power BI Desktop may spawn msmdsrv.exe through an intermediate
        host process rather than directly.  When the immediate parent PID is not
        in pbi_pid_to_model, the tree walk should still resolve the correct name.
        """
        if not HAS_PSUTIL:
            pytest.skip("psutil not installed")
        from pql_test import runner

        port = _MOCK_AS_PORT_A
        pbi_pid = 1000
        intermediate_pid = 2000

        fake_proc = _make_mock_process(
            pid=3000, name="msmdsrv.exe", ppid=intermediate_pid, listen_port=port
        )

        # _find_pbi_ancestor_pid calls _psutil.Process(ppid).ppid():
        # intermediate.ppid() → pbi_pid → found in pbi_pids
        intermediate_mock = MagicMock()
        intermediate_mock.ppid.return_value = pbi_pid

        with (
            patch(
                "pql_test.runner._get_pbi_process_window_titles",
                return_value={pbi_pid: "TreeWalkModel - Power BI Desktop"},
            ),
            patch("pql_test.runner._psutil.process_iter", return_value=[fake_proc]),
            patch("pql_test.runner._psutil.Process", return_value=intermediate_mock),
            patch("pql_test.runner._psutil.net_connections", return_value=[]),
            patch("pql_test.runner._get_catalog_from_local_port", return_value=""),
        ):
            instances = get_pbi_files_opened()

        assert len(instances) == 1
        assert instances[0].model_name == "TreeWalkModel"
        assert instances[0].server == f"localhost:{port}"

    def test_uses_global_net_connections_when_available(self):
        """
        When psutil.net_connections() (global) is available, the port is
        resolved from the pre-built pid→port map rather than per-process
        net_connections().  This is more reliable on some Windows configurations.
        """
        if not HAS_PSUTIL:
            pytest.skip("psutil not installed")

        port = _MOCK_AS_PORT_A
        msmdsrv_pid = 999
        pbi_pid = 1234

        fake_proc = MagicMock()
        fake_proc.info = {"pid": msmdsrv_pid, "name": "msmdsrv.exe", "ppid": pbi_pid}
        # net_connections on the process object would NOT be called when the
        # global map already has the entry.
        fake_proc.net_connections.side_effect = AssertionError("should not be called")

        global_conn = MagicMock()
        global_conn.status = "LISTEN"
        global_conn.laddr = MagicMock(ip="127.0.0.1", port=port)
        global_conn.pid = msmdsrv_pid

        with (
            patch(
                "pql_test.runner._get_pbi_process_window_titles",
                return_value={pbi_pid: "GlobalConnModel - Power BI Desktop"},
            ),
            patch("pql_test.runner._psutil.process_iter", return_value=[fake_proc]),
            patch("pql_test.runner._psutil.net_connections", return_value=[global_conn]),
            patch("pql_test.runner._get_catalog_from_local_port", return_value=""),
        ):
            instances = get_pbi_files_opened()

        assert len(instances) == 1
        assert instances[0].model_name == "GlobalConnModel"
        assert instances[0].server == f"localhost:{port}"
        fake_proc.net_connections.assert_not_called()

    def test_finds_msmdsrv_when_pbi_window_titles_unavailable(self):
        """
        When _get_pbi_process_window_titles() returns empty (e.g. UAC mismatch
        or Microsoft Store variant), get_pbi_files_opened() must NOT return early.
        It should still find msmdsrv.exe and return an instance with an empty
        model_name so the unnamed-instance fallback in resolve_local_xmla_connection
        can handle it.
        """
        if not HAS_PSUTIL:
            pytest.skip("psutil not installed")

        port = _MOCK_AS_PORT_A
        fake_proc = _make_mock_process(pid=500, name="msmdsrv.exe", ppid=100, listen_port=port)

        with (
            patch("pql_test.runner._get_pbi_process_window_titles", return_value={}),
            patch("pql_test.runner._psutil.process_iter", return_value=[fake_proc]),
            patch("pql_test.runner._psutil.net_connections", return_value=[]),
            patch("pql_test.runner._get_catalog_from_local_port", return_value=""),
        ):
            instances = get_pbi_files_opened()

        # We found msmdsrv even without a PBI window — model_name is empty
        assert len(instances) == 1
        assert instances[0].model_name == ""
        assert instances[0].server == f"localhost:{port}"

    def test_cmdline_fallback_resolves_model_name_from_pbip_argument(self):
        """
        Step 1b: when _get_pbi_process_window_titles() returns empty, the
        command-line fallback scans PBIDesktop.exe processes and extracts the
        model name from a .pbip file-path argument.

        This is the fix for the scenario where PBI Desktop and the terminal run
        at different UAC elevation levels, so EnumWindows returns no titles.
        """
        if not HAS_PSUTIL:
            pytest.skip("psutil not installed")

        pbi_pid = 100
        port = _MOCK_AS_PORT_A

        msmdsrv_proc = _make_mock_process(
            pid=999, name="msmdsrv.exe", ppid=pbi_pid, listen_port=port
        )

        # PBIDesktop.exe process with a .pbip path in its cmdline
        pbi_proc = MagicMock()
        pbi_proc.info = {
            "pid": pbi_pid,
            "name": "PBIDesktop.exe",
            "cmdline": [r"C:\Program Files\...\PBIDesktop.exe", r"C:\Models\RLS_Model.pbip"],
        }

        def _fake_process_iter(attrs):
            if "cmdline" in attrs:
                # Step 1b scan: returns pbi_proc
                return [pbi_proc]
            # msmdsrv scan
            return [msmdsrv_proc]

        with (
            patch("pql_test.runner._get_pbi_process_window_titles", return_value={}),
            patch("pql_test.runner._psutil.process_iter", side_effect=_fake_process_iter),
            patch("pql_test.runner._psutil.net_connections", return_value=[]),
            patch("pql_test.runner._get_catalog_from_local_port", return_value=""),
        ):
            instances = get_pbi_files_opened()

        assert len(instances) == 1
        assert instances[0].model_name == "RLS_Model"
        assert instances[0].server == f"localhost:{port}"

    def test_cmdline_fallback_resolves_model_name_from_pbix_argument(self):
        """Step 1b also recognises .pbix (legacy) file-path arguments."""
        if not HAS_PSUTIL:
            pytest.skip("psutil not installed")

        pbi_pid = 200
        port = _MOCK_AS_PORT_B

        msmdsrv_proc = _make_mock_process(
            pid=888, name="msmdsrv.exe", ppid=pbi_pid, listen_port=port
        )

        pbi_proc = MagicMock()
        pbi_proc.info = {
            "pid": pbi_pid,
            "name": "PBIDesktop.exe",
            "cmdline": [r"C:\...\PBIDesktop.exe", r"C:\Reports\SalesReport.pbix"],
        }

        def _fake_process_iter(attrs):
            if "cmdline" in attrs:
                return [pbi_proc]
            return [msmdsrv_proc]

        with (
            patch("pql_test.runner._get_pbi_process_window_titles", return_value={}),
            patch("pql_test.runner._psutil.process_iter", side_effect=_fake_process_iter),
            patch("pql_test.runner._psutil.net_connections", return_value=[]),
            patch("pql_test.runner._get_catalog_from_local_port", return_value=""),
        ):
            instances = get_pbi_files_opened()

        assert len(instances) == 1
        assert instances[0].model_name == "SalesReport"

    def test_cmdline_fallback_two_models_both_resolved(self):
        """
        Two PBI Desktop instances open with different models: both are resolved
        correctly via the cmdline fallback so local/<name> matching works.
        This directly reproduces the user's scenario (RLS_Model + SampleModel
        both open, window titles unavailable, both showing as empty strings).
        """
        if not HAS_PSUTIL:
            pytest.skip("psutil not installed")

        pbi_pid_rls = 100
        pbi_pid_sample = 200

        msmdsrv_rls = _make_mock_process(
            pid=901, name="msmdsrv.exe", ppid=pbi_pid_rls, listen_port=_MOCK_AS_PORT_A
        )
        msmdsrv_sample = _make_mock_process(
            pid=902, name="msmdsrv.exe", ppid=pbi_pid_sample, listen_port=_MOCK_AS_PORT_B
        )

        pbi_proc_rls = MagicMock()
        pbi_proc_rls.info = {
            "pid": pbi_pid_rls,
            "name": "PBIDesktop.exe",
            "cmdline": [r"PBIDesktop.exe", r"C:\Models\RLS_Model.pbip"],
        }
        pbi_proc_sample = MagicMock()
        pbi_proc_sample.info = {
            "pid": pbi_pid_sample,
            "name": "PBIDesktop.exe",
            "cmdline": [r"PBIDesktop.exe", r"C:\Models\SampleModel.pbip"],
        }

        def _fake_process_iter(attrs):
            if "cmdline" in attrs:
                return [pbi_proc_rls, pbi_proc_sample]
            return [msmdsrv_rls, msmdsrv_sample]

        with (
            patch("pql_test.runner._get_pbi_process_window_titles", return_value={}),
            patch("pql_test.runner._psutil.process_iter", side_effect=_fake_process_iter),
            patch("pql_test.runner._psutil.net_connections", return_value=[]),
            patch("pql_test.runner._get_catalog_from_local_port", return_value=""),
        ):
            instances = get_pbi_files_opened()

        assert len(instances) == 2
        names = {i.model_name for i in instances}
        assert names == {"RLS_Model", "SampleModel"}

    def test_cmdline_fallback_empty_model_name_when_no_file_arg(self):
        """
        When PBIDesktop.exe was opened without a file (new blank report), the
        cmdline fallback leaves model_name as '' rather than raising an error.
        """
        if not HAS_PSUTIL:
            pytest.skip("psutil not installed")

        pbi_pid = 100
        port = _MOCK_AS_PORT_A

        msmdsrv_proc = _make_mock_process(
            pid=999, name="msmdsrv.exe", ppid=pbi_pid, listen_port=port
        )
        # _find_pbi_ancestor_pid calls proc.ppid() (method, not .info["ppid"]).
        # Set it so the tree-walk returns the right integer and stops immediately.
        msmdsrv_proc.ppid.return_value = pbi_pid

        pbi_proc = MagicMock()
        pbi_proc.info = {
            "pid": pbi_pid,
            "name": "PBIDesktop.exe",
            "cmdline": [r"PBIDesktop.exe"],  # no file argument
        }

        def _fake_process_iter(attrs):
            if "cmdline" in attrs:
                return [pbi_proc]
            return [msmdsrv_proc]

        with (
            patch("pql_test.runner._get_pbi_process_window_titles", return_value={}),
            patch("pql_test.runner._psutil.process_iter", side_effect=_fake_process_iter),
            patch("pql_test.runner._psutil.net_connections", return_value=[]),
            patch("pql_test.runner._get_catalog_from_local_port", return_value=""),
        ):
            instances = get_pbi_files_opened()

        assert len(instances) == 1
        assert instances[0].model_name == ""

    def test_cmdline_fallback_skips_non_pbidesktop_processes(self):
        """Step 1b only picks up PBIDesktop.exe, not other processes."""
        if not HAS_PSUTIL:
            pytest.skip("psutil not installed")

        other_proc = MagicMock()
        other_proc.info = {
            "pid": 999,
            "name": "notepad.exe",
            "cmdline": [r"notepad.exe", r"C:\file.pbip"],
        }
        msmdsrv_proc = _make_mock_process(
            pid=111, name="msmdsrv.exe", ppid=999, listen_port=_MOCK_AS_PORT_A
        )

        def _fake_process_iter(attrs):
            if "cmdline" in attrs:
                return [other_proc]
            return [msmdsrv_proc]

        with (
            patch("pql_test.runner._get_pbi_process_window_titles", return_value={}),
            patch("pql_test.runner._psutil.process_iter", side_effect=_fake_process_iter),
            patch("pql_test.runner._psutil.net_connections", return_value=[]),
            patch("pql_test.runner._get_catalog_from_local_port", return_value=""),
        ):
            instances = get_pbi_files_opened()

        # msmdsrv found but its parent (notepad) is not a PBI process → empty model name
        assert len(instances) == 1
        assert instances[0].model_name == ""

    def test_window_titles_take_priority_over_cmdline_fallback(self):
        """
        Step 1b only activates when window titles return nothing.  When
        _get_pbi_process_window_titles() returns titles, Step 1b is skipped.
        """
        if not HAS_PSUTIL:
            pytest.skip("psutil not installed")

        pbi_pid = 100
        port = _MOCK_AS_PORT_A

        msmdsrv_proc = _make_mock_process(
            pid=999, name="msmdsrv.exe", ppid=pbi_pid, listen_port=port
        )

        # Window title returns a name; a conflicting cmdline name should NOT be used
        with (
            patch(
                "pql_test.runner._get_pbi_process_window_titles",
                return_value={pbi_pid: "WindowTitleModel - Power BI Desktop"},
            ),
            patch("pql_test.runner._psutil.process_iter", return_value=[msmdsrv_proc]),
            patch("pql_test.runner._psutil.net_connections", return_value=[]),
            patch("pql_test.runner._get_catalog_from_local_port", return_value=""),
        ):
            instances = get_pbi_files_opened()

        assert len(instances) == 1
        assert instances[0].model_name == "WindowTitleModel"


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
        with patch("pql_test.runner.get_pbi_files_opened", return_value=[inst]):
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
            patch("pql_test.runner.get_pbi_files_opened", return_value=[]),
            patch("pql_test.runner._detect_local_pbi_desktop_port", return_value=None),
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
        with patch("pql_test.runner.get_pbi_files_opened", return_value=instances):
            conn = resolve_local_xmla_connection(str(tmp_path))
        assert conn is None

    def test_matching_is_case_insensitive(self, tmp_path):
        """Model name match is case-insensitive (mirrors PowerShell -eq behaviour)."""
        (tmp_path / "samplemodel.pbip").write_text("{}")
        instances = [self._make_instance("SAMPLEMODEL")]
        with patch("pql_test.runner.get_pbi_files_opened", return_value=instances):
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
        with patch("pql_test.runner.get_pbi_files_opened", return_value=[inst]):
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
                "pql_test.runner.get_pbi_files_opened",
                side_effect=ImportError("psutil not installed"),
            ),
            patch(
                "pql_test.runner._detect_local_pbi_desktop_port",
                return_value=fallback_server,
            ),
        ):
            conn = resolve_local_xmla_connection(str(tmp_path))
        assert conn is not None
        assert conn.server == fallback_server  # dynamic: derived from fallback mock
        assert conn.catalog == ""  # local: no Initial Catalog; AS auto-selects

    def test_returns_connection_when_single_unnamed_instance_exists(self, tmp_path):
        """
        When the process-tree walk cannot link msmdsrv.exe to a PBIDesktop.exe
        window (model_name is empty) but exactly one PBI Desktop window is open,
        resolve_local_xmla_connection should fall back to that instance rather
        than returning None.  This handles modern PBI Desktop builds where the
        process tree cannot be walked reliably.
        """
        (tmp_path / "SampleModel.pbip").write_text("{}")
        # Instance with empty model_name — tree walk produced no result
        unnamed_inst = LocalPbiInstance(
            model_name="",
            server=f"localhost:{_MOCK_AS_PORT_A}",
            catalog="",
        )
        with patch("pql_test.runner.get_pbi_files_opened", return_value=[unnamed_inst]):
            conn = resolve_local_xmla_connection(str(tmp_path))
        assert conn is not None
        assert conn.server == unnamed_inst.server

    def test_returns_none_when_multiple_unnamed_instances_exist(self, tmp_path):
        """
        When multiple unnamed instances are detected the caller cannot know
        which one to use — return None rather than guessing.
        """
        (tmp_path / "SampleModel.pbip").write_text("{}")
        inst_a = LocalPbiInstance(model_name="", server=f"localhost:{_MOCK_AS_PORT_A}", catalog="")
        inst_b = LocalPbiInstance(model_name="", server=f"localhost:{_MOCK_AS_PORT_B}", catalog="")
        with patch("pql_test.runner.get_pbi_files_opened", return_value=[inst_a, inst_b]):
            conn = resolve_local_xmla_connection(str(tmp_path))
        assert conn is None

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
                "pql_test.runner.get_pbi_files_opened",
                side_effect=ImportError("psutil not installed"),
            ),
            patch(
                "pql_test.runner._detect_local_pbi_desktop_port",
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
        # First call: RetrieveTestsV2 discovery — must return Name-keyed rows.
        # Subsequent calls: test execution — return assertion result rows.
        discovery_rows = [
            {"Name": "Calculations.DEV.Tests", "Description": "basic check", "PQLAssert_ImpersonatedUserName": ""},
            {"Name": "Schema.DEV.Tests", "Description": "", "PQLAssert_ImpersonatedUserName": ""},
        ]
        result_rows = [
            {"TestName": "check 1", "Expected": "1", "Actual": "1", "Passed": "true"},
            {"TestName": "check 2", "Expected": "foo", "Actual": "foo", "Passed": "true"},
        ]
        with (
            patch("pql_test.runner.get_pbi_files_opened", return_value=instances),
            patch("pql_test.runner._execute_dax_query", side_effect=[discovery_rows, result_rows, result_rows]),
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
        with patch("pql_test.runner.get_pbi_files_opened", return_value=[inst]):
            conn = resolve_local_xmla_connection(str(tmp_path))
        assert conn is not None  # connection resolved fine
        assert conn.server == inst.server  # dynamic: derived from the instance

        suite = run_tests_from_model(str(tmp_path), connection=conn)
        # No *.Tests.dax files → total == 0, like Pester $warnings.Length > 0
        assert suite.total == 0
        assert suite.tests == []

# ---------------------------------------------------------------------------
# _retrieve_tests_via_dax
# ---------------------------------------------------------------------------

from pql_test.runner import _retrieve_tests_via_dax  # noqa: E402


class TestRetrieveTestsViaDax:
    """Tests for the live-model discovery helper _retrieve_tests_via_dax()."""

    # ------------------------------------------------------------------
    # V2 success path
    # ------------------------------------------------------------------

    def test_v2_success_returns_test_list(self):
        """V2 rows → PqlTest list with all metadata populated."""
        rows = [
            {
                "PQL.Assert.RetrieveTestsV2()[Name]": "Calcs.DEV.Tests",
                "PQL.Assert.RetrieveTestsV2()[Description]": "Calculation tests",
                "PQL.Assert.RetrieveTestsV2()[PQLAssert_ImpersonatedUserName]": "alice@contoso.com",
            }
        ]
        conn = MagicMock()
        with patch("pql_test.runner._execute_dax_query", return_value=rows):
            result = _retrieve_tests_via_dax(conn)

        assert result is not None
        assert len(result) == 1
        t = result[0]
        assert t.name == "Calcs.DEV.Tests"
        assert t.description == "Calculation tests"
        assert t.impersonated_user_name == "alice@contoso.com"

    def test_v2_role_name_column_populated(self):
        """PQLAssert_RoleName column from V2 rows → PqlTest.role_name."""
        rows = [
            {
                "PQL.Assert.RetrieveTestsV2()[Name]": "RLS.ANY.Tests",
                "PQL.Assert.RetrieveTestsV2()[Description]": None,
                "PQL.Assert.RetrieveTestsV2()[PQLAssert_ImpersonatedUserName]": "west@contoso.com",
                "PQL.Assert.RetrieveTestsV2()[PQLAssert_RoleName]": "West",
            }
        ]
        conn = MagicMock()
        with patch("pql_test.runner._execute_dax_query", return_value=rows):
            result = _retrieve_tests_via_dax(conn)

        assert result is not None
        assert len(result) == 1
        t = result[0]
        assert t.role_name == "West"
        assert t.impersonated_user_name == "west@contoso.com"

    def test_v2_role_name_none_when_column_absent(self):
        """If PQLAssert_RoleName column is missing, role_name is None (no crash)."""
        rows = [
            {
                "PQL.Assert.RetrieveTestsV2()[Name]": "Calcs.DEV.Tests",
                "PQL.Assert.RetrieveTestsV2()[Description]": None,
                "PQL.Assert.RetrieveTestsV2()[PQLAssert_ImpersonatedUserName]": None,
                # PQLAssert_RoleName intentionally absent
            }
        ]
        conn = MagicMock()
        with patch("pql_test.runner._execute_dax_query", return_value=rows):
            result = _retrieve_tests_via_dax(conn)

        assert result is not None
        assert result[0].role_name is None

    def test_v2_source_is_evaluate_expression(self):
        """source must be 'EVALUATE <name>()' for live-discovered tests."""
        rows = [
            {
                "PQL.Assert.RetrieveTestsV2()[Name]": "Calcs.DEV.Tests",
                "PQL.Assert.RetrieveTestsV2()[Description]": None,
                "PQL.Assert.RetrieveTestsV2()[PQLAssert_ImpersonatedUserName]": None,
            }
        ]
        conn = MagicMock()
        with patch("pql_test.runner._execute_dax_query", return_value=rows):
            result = _retrieve_tests_via_dax(conn)

        assert result is not None
        assert result[0].source == "EVALUATE Calcs.DEV.Tests()"

    def test_v2_file_path_is_empty_string(self):
        """Live-discovered tests have no local file path."""
        rows = [
            {
                "PQL.Assert.RetrieveTestsV2()[Name]": "Calcs.DEV.Tests",
                "PQL.Assert.RetrieveTestsV2()[Description]": None,
                "PQL.Assert.RetrieveTestsV2()[PQLAssert_ImpersonatedUserName]": None,
            }
        ]
        conn = MagicMock()
        with patch("pql_test.runner._execute_dax_query", return_value=rows):
            result = _retrieve_tests_via_dax(conn)

        assert result is not None
        assert result[0].file_path == ""

    def test_v2_multiple_rows(self):
        """All rows from V2 are converted to PqlTest objects."""
        rows = [
            {
                "PQL.Assert.RetrieveTestsV2()[Name]": f"Suite{i}.Tests",
                "PQL.Assert.RetrieveTestsV2()[Description]": None,
                "PQL.Assert.RetrieveTestsV2()[PQLAssert_ImpersonatedUserName]": None,
            }
            for i in range(3)
        ]
        conn = MagicMock()
        with patch("pql_test.runner._execute_dax_query", return_value=rows):
            result = _retrieve_tests_via_dax(conn)

        assert result is not None
        assert len(result) == 3
        assert [t.name for t in result] == ["Suite0.Tests", "Suite1.Tests", "Suite2.Tests"]

    # ------------------------------------------------------------------
    # V1 fallback
    # ------------------------------------------------------------------

    def test_falls_back_to_v1_when_v2_raises(self):
        """If V2 raises, V1 is attempted and its results are returned."""
        v1_rows = [{"PQL.Assert.RetrieveTests()[Name]": "Calcs.DEV.Tests"}]

        call_count: list[int] = [0]

        def _fake_execute(conn, dax: str):
            call_count[0] += 1
            if "RetrieveTestsV2" in dax:
                raise Exception("Function not found")
            return v1_rows

        conn = MagicMock()
        with patch("pql_test.runner._execute_dax_query", side_effect=_fake_execute):
            result = _retrieve_tests_via_dax(conn)

        assert result is not None
        assert len(result) == 1
        assert result[0].name == "Calcs.DEV.Tests"
        assert call_count[0] == 2  # V2 then V1

    def test_v1_fallback_impersonated_user_is_none(self):
        """V1 rows have no impersonation column → field is None."""
        v1_rows = [{"PQL.Assert.RetrieveTests()[Name]": "Calcs.DEV.Tests"}]

        def _fake_execute(conn, dax: str):
            if "RetrieveTestsV2" in dax:
                raise Exception("not found")
            return v1_rows

        conn = MagicMock()
        with patch("pql_test.runner._execute_dax_query", side_effect=_fake_execute):
            result = _retrieve_tests_via_dax(conn)

        assert result is not None
        assert result[0].impersonated_user_name is None

    # ------------------------------------------------------------------
    # Both queries fail → None (file-scan fallback signal)
    # ------------------------------------------------------------------

    def test_returns_none_when_both_dax_queries_fail(self):
        """If both V2 and V1 raise, None is returned (sentinel for file scan)."""
        conn = MagicMock()
        with patch("pql_test.runner._execute_dax_query", side_effect=Exception("error")):
            result = _retrieve_tests_via_dax(conn)

        assert result is None

    # ------------------------------------------------------------------
    # retrieve_tests() integration: connection threading
    # ------------------------------------------------------------------

    def test_retrieve_tests_uses_live_discovery_when_connection_given(self, tmp_model):
        """retrieve_tests(path, connection=conn) delegates to _retrieve_tests_via_dax."""
        rows = [
            {
                "PQL.Assert.RetrieveTestsV2()[Name]": "Calcs.DEV.Tests",
                "PQL.Assert.RetrieveTestsV2()[Description]": None,
                "PQL.Assert.RetrieveTestsV2()[PQLAssert_ImpersonatedUserName]": None,
            }
        ]
        model_dir = tmp_model(
            [{"suite_name": "Calculations.DEV", "source": make_dax_source("Calcs")}]
        )
        conn = MagicMock()
        with patch("pql_test.runner._execute_dax_query", return_value=rows):
            result = retrieve_tests(model_dir, connection=conn)

        assert len(result) == 1
        assert result[0].name == "Calcs.DEV.Tests"
        # Live path: no file path
        assert result[0].file_path == ""

    def test_retrieve_tests_falls_back_to_file_scan_when_dax_fails(self, tmp_model):
        """When both DAX queries fail, file scan is used automatically."""
        model_dir = tmp_model(
            [{"suite_name": "Calculations.DEV", "source": make_dax_source("Calcs")}]
        )
        conn = MagicMock()
        with patch("pql_test.runner._execute_dax_query", side_effect=Exception("network error")):
            result = retrieve_tests(model_dir, connection=conn)

        # Falls back to file scan → finds the .Tests.dax file
        assert len(result) == 1
        assert result[0].file_path.endswith(".dax")

    def test_retrieve_tests_uses_file_scan_when_no_connection(self, tmp_model):
        """retrieve_tests(path) with no connection always uses file scan."""
        model_dir = tmp_model(
            [{"suite_name": "Calculations.DEV", "source": make_dax_source("Calcs")}]
        )
        result = retrieve_tests(model_dir)
        assert len(result) == 1
        assert result[0].file_path.endswith(".dax")


# ---------------------------------------------------------------------------
# parse_model_identifier
# ---------------------------------------------------------------------------

class TestParseModelIdentifier:
    """Tests for model identifier format detection."""

    def test_local_prefix_returns_local_kind(self):
        """'local/SampleModel' → kind='local', model_name='SampleModel'."""
        ident = parse_model_identifier("local/SampleModel")
        assert ident.kind == "local"
        assert ident.model_name == "SampleModel"
        assert ident.raw == "local/SampleModel"

    def test_local_prefix_with_spaces_in_name(self):
        """'local/My Model' → kind='local', model_name='My Model'."""
        ident = parse_model_identifier("local/My Model")
        assert ident.kind == "local"
        assert ident.model_name == "My Model"

    def test_local_prefix_existing_path_uses_path_kind(self, tmp_path):
        """If 'local/<name>' exists on disk, treat it as a filesystem path."""
        local_dir = tmp_path / "local" / "Model"
        local_dir.mkdir(parents=True)
        ident = parse_model_identifier(str(local_dir))
        assert ident.kind == "path"

    def test_dotted_name_returns_service_kind(self):
        """'MyWorkspace.MyModel' → kind='service'."""
        ident = parse_model_identifier("MyWorkspace.MyModel")
        assert ident.kind == "service"
        assert ident.workspace_name == "MyWorkspace"
        assert ident.model_name == "MyModel"
        assert ident.raw == "MyWorkspace.MyModel"

    def test_dotted_name_splits_on_last_dot(self):
        """'My.Complex.Workspace.MyModel' → workspace='My.Complex.Workspace'."""
        ident = parse_model_identifier("My.Complex.Workspace.MyModel")
        assert ident.kind == "service"
        assert ident.workspace_name == "My.Complex.Workspace"
        assert ident.model_name == "MyModel"

    def test_dotted_name_existing_path_uses_path_kind(self, tmp_path):
        """If a dotted path exists on disk, treat it as a filesystem path."""
        dotted_dir = tmp_path / "ws.model"
        dotted_dir.mkdir()
        ident = parse_model_identifier(str(dotted_dir))
        assert ident.kind == "path"

    def test_relative_path_returns_path_kind(self, tmp_path):
        """'./examples/Model' → kind='path' even if it doesn't exist."""
        ident = parse_model_identifier("./some.dotted.path")
        assert ident.kind == "path"

    def test_absolute_path_returns_path_kind(self, tmp_path):
        """/absolute/path → kind='path'."""
        ident = parse_model_identifier("/some/absolute/path")
        assert ident.kind == "path"

    def test_plain_directory_returns_path_kind(self, tmp_path):
        """'examples' → kind='path' (no dot, no local/ prefix)."""
        ident = parse_model_identifier("examples")
        assert ident.kind == "path"
        assert ident.raw == "examples"

    def test_backslash_path_returns_path_kind(self):
        """Windows-style path → kind='path'."""
        ident = parse_model_identifier("\\\\server\\share\\model.sm")
        assert ident.kind == "path"


# ---------------------------------------------------------------------------
# resolve_service_xmla_connection_by_name
# ---------------------------------------------------------------------------

class TestResolveServiceXmlaConnectionByName:
    """Tests for building XMLA connections from workspace + model display names."""

    def test_returns_connection_with_valid_credentials(self):
        """Full credentials → connection with expected server and catalog."""
        opts = XmlaConnectionOptions(
            tenant_id="t-1", client_id="c-1", client_secret="s-1",
        )
        with patch("pql_test.runner._acquire_service_principal_token", return_value="fake-token"):
            conn = resolve_service_xmla_connection_by_name("MyWorkspace", "MyModel", opts)
        assert conn is not None
        assert "MyWorkspace" in conn.server
        assert conn.catalog == "MyModel"
        assert conn.access_token == "fake-token"
        assert "powerbi://api.powerbi.com" in conn.server

    def test_returns_none_without_tenant_id(self):
        """Missing tenant_id → None."""
        opts = XmlaConnectionOptions(client_id="c-1", client_secret="s-1")
        conn = resolve_service_xmla_connection_by_name("WS", "M", opts)
        assert conn is None

    def test_returns_none_without_client_id(self):
        """Missing client_id → None."""
        opts = XmlaConnectionOptions(tenant_id="t-1", client_secret="s-1")
        conn = resolve_service_xmla_connection_by_name("WS", "M", opts)
        assert conn is None

    def test_returns_none_without_client_secret(self):
        """Missing client_secret → None."""
        opts = XmlaConnectionOptions(tenant_id="t-1", client_id="c-1")
        conn = resolve_service_xmla_connection_by_name("WS", "M", opts)
        assert conn is None

    def test_uses_correct_environment_endpoint(self):
        """USGov environment → USGov XMLA prefix."""
        opts = XmlaConnectionOptions(
            tenant_id="t", client_id="c", client_secret="s",
            environment=Environment.US_GOV,
        )
        with patch("pql_test.runner._acquire_service_principal_token", return_value="tok"):
            conn = resolve_service_xmla_connection_by_name("WS", "M", opts)
        assert conn is not None
        assert "powerbigov.us" in conn.server


# ---------------------------------------------------------------------------
# resolve_local_xmla_connection_by_name
# ---------------------------------------------------------------------------

class TestResolveLocalXmlaConnectionByName:
    """Tests for resolving local connections by model name."""

    def test_returns_connection_for_matching_instance(self):
        """Matching model name → connection returned."""
        inst = LocalPbiInstance(
            model_name="SampleModel",
            server=f"localhost:{_MOCK_AS_PORT_A}",
            catalog="",
        )
        with patch("pql_test.runner.get_pbi_files_opened", return_value=[inst]):
            conn = resolve_local_xmla_connection_by_name("SampleModel")
        assert conn is not None
        assert conn.server == inst.server

    def test_matching_is_case_insensitive(self):
        """Model name match is case-insensitive."""
        inst = LocalPbiInstance(
            model_name="SampleModel",
            server=f"localhost:{_MOCK_AS_PORT_A}",
            catalog="",
        )
        with patch("pql_test.runner.get_pbi_files_opened", return_value=[inst]):
            conn = resolve_local_xmla_connection_by_name("SAMPLEMODEL")
        assert conn is not None

    def test_returns_none_when_no_match(self):
        """No matching model → None."""
        inst = LocalPbiInstance(
            model_name="OtherModel",
            server=f"localhost:{_MOCK_AS_PORT_A}",
            catalog="",
        )
        with patch("pql_test.runner.get_pbi_files_opened", return_value=[inst]):
            conn = resolve_local_xmla_connection_by_name("SampleModel")
        assert conn is None

    def test_returns_none_when_no_instances(self):
        """No running instances → None."""
        with (
            patch("pql_test.runner.get_pbi_files_opened", return_value=[]),
            patch("pql_test.runner._detect_local_pbi_desktop_port", return_value=None),
        ):
            conn = resolve_local_xmla_connection_by_name("SampleModel")
        assert conn is None

    def test_falls_back_to_port_file_when_psutil_unavailable(self):
        """psutil ImportError → port-file fallback."""
        fallback_server = f"localhost:{_MOCK_AS_PORT_A}"
        with (
            patch("pql_test.runner.get_pbi_files_opened", side_effect=ImportError("psutil")),
            patch("pql_test.runner._detect_local_pbi_desktop_port", return_value=fallback_server),
        ):
            conn = resolve_local_xmla_connection_by_name("SampleModel")
        assert conn is not None
        assert conn.server == fallback_server

    def test_returns_single_unnamed_instance(self):
        """Single unnamed instance → connection returned."""
        inst = LocalPbiInstance(
            model_name="",
            server=f"localhost:{_MOCK_AS_PORT_A}",
            catalog="",
        )
        with patch("pql_test.runner.get_pbi_files_opened", return_value=[inst]):
            conn = resolve_local_xmla_connection_by_name("AnyModel")
        assert conn is not None


# ---------------------------------------------------------------------------
# resolve_xmla_connection — local/<model_name> routing (regression tests)
#
# Bug: when 'local/<model_name>' was passed and the named PBI Desktop instance
# was not found, resolve_xmla_connection fell through to
# resolve_local_xmla_connection(), which had model_name=None and returned the
# FIRST running PBI Desktop instance (e.g. SampleModel) rather than None.
# This caused the wrong model's tests to run silently.
# Fix: resolve_xmla_connection now detects kind='local' and delegates to
# resolve_local_xmla_connection_by_name() — which always matches by name.
# ---------------------------------------------------------------------------

class TestResolveXmlaConnectionLocalRouting:
    """Regression tests for local/<model_name> routing in resolve_xmla_connection."""

    def test_local_path_routes_to_name_based_resolver(self):
        """
        resolve_xmla_connection('local/SampleModel', opts) must call
        resolve_local_xmla_connection_by_name, not resolve_local_xmla_connection.
        The name-based resolver performs an exact (case-insensitive) match and
        never returns an arbitrary running instance.
        """
        opts = XmlaConnectionOptions()
        inst = LocalPbiInstance(
            model_name="SampleModel",
            server=f"localhost:{_MOCK_AS_PORT_A}",
            catalog="SampleModel-GUID",
        )
        with patch("pql_test.runner.get_pbi_files_opened", return_value=[inst]):
            conn = resolve_xmla_connection("local/SampleModel", opts)
        assert conn is not None
        assert conn.server == inst.server
        assert conn.catalog == inst.catalog

    def test_local_path_returns_none_when_named_model_not_open(self):
        """
        When 'local/RLS_Model' is supplied but only SampleModel is running,
        resolve_xmla_connection must return None — not SampleModel's connection.
        This is the exact scenario that triggered the original bug.
        """
        opts = XmlaConnectionOptions()
        # Only SampleModel is open; RLS_Model is not
        inst = LocalPbiInstance(
            model_name="SampleModel",
            server=f"localhost:{_MOCK_AS_PORT_A}",
            catalog="SampleModel-GUID",
        )
        with patch("pql_test.runner.get_pbi_files_opened", return_value=[inst]):
            conn = resolve_xmla_connection("local/RLS_Model", opts)
        assert conn is None

    def test_local_path_does_not_call_path_based_resolver(self):
        """
        resolve_local_xmla_connection (path-based) must NOT be called when the
        model_path uses the 'local/<name>' format.  If it were called with a
        non-existent path, it could return an unrelated running instance.
        """
        opts = XmlaConnectionOptions()
        with (
            patch(
                "pql_test.runner.resolve_local_xmla_connection_by_name",
                return_value=None,
            ) as mock_by_name,
            patch(
                "pql_test.runner.resolve_local_xmla_connection",
            ) as mock_by_path,
        ):
            resolve_xmla_connection("local/RLS_Model", opts)

        mock_by_name.assert_called_once_with("RLS_Model")
        mock_by_path.assert_not_called()

    def test_local_path_matching_is_case_insensitive(self):
        """Name matching propagated through resolve_xmla_connection → by_name is case-insensitive."""
        opts = XmlaConnectionOptions()
        inst = LocalPbiInstance(
            model_name="rls_model",
            server=f"localhost:{_MOCK_AS_PORT_A}",
            catalog="",
        )
        with patch("pql_test.runner.get_pbi_files_opened", return_value=[inst]):
            conn = resolve_xmla_connection("local/RLS_Model", opts)
        assert conn is not None

    def test_run_tests_from_model_skips_wrong_instance(self):
        """
        End-to-end: run_tests_from_model('local/RLS_Model') when only SampleModel
        is open must produce skipped results — not run tests against SampleModel.
        This directly reproduces the user-visible symptom of the original bug.
        """
        # Only SampleModel is open
        inst = LocalPbiInstance(
            model_name="SampleModel",
            server=f"localhost:{_MOCK_AS_PORT_A}",
            catalog="SampleModel-GUID",
        )
        with (
            patch("pql_test.runner.get_pbi_files_opened", return_value=[inst]),
            patch("pql_test.runner._detect_local_pbi_desktop_port", return_value=None),
        ):
            suite = run_tests_from_model(
                "local/RLS_Model",
                skip_message="No matching Power BI Desktop instance found for model 'RLS_Model'.",
            )
        # Connection is None → all tests are skipped, never executed against SampleModel
        assert all(r.skipped for r in suite.results), (
            "Expected all results to be skipped when the named model is not open"
        )