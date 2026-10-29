# SPDX-License-Identifier: AGPL-3.0-only
"""
Tests for environment-specific test discovery (--env / environment=...).

Test suites encode their target environment in the function name:
<Suite>.<ENV>.Tests (e.g. Calculations.DEV.Tests, BestPractices.ANY.Tests).
Live discovery passes the environment to PQL.Assert.RetrieveTestsV2("<ENV>");
fallback paths filter client-side by the naming convention.

Run with:
    cd python
    pytest tests/test_environment_discovery.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from pql_test.runner import (
    PqlTest,
    _retrieve_tests_via_dax,
    _test_matches_environment,
    retrieve_test_by_name,
    retrieve_tests,
    run_tests_from_model,
)
from tests.conftest import make_dax_source


# ---------------------------------------------------------------------------
# _test_matches_environment
# ---------------------------------------------------------------------------

class TestTestMatchesEnvironment:
    """Unit tests for the <Suite>.<ENV>.Tests naming-convention matcher."""

    def test_matches_exact_env_segment(self):
        assert _test_matches_environment("Calculations.DEV.Tests", "DEV")

    def test_is_case_insensitive(self):
        assert _test_matches_environment("Calculations.DEV.Tests", "dev")
        assert _test_matches_environment("Calculations.dev.Tests", "DEV")

    def test_rejects_other_environment(self):
        assert not _test_matches_environment("Calculations.DEV.Tests", "PROD")

    def test_any_is_not_a_wildcard(self):
        # ANY is an ordinary token: --env DEV must not pick up *.ANY.Tests,
        # and --env ANY must not pick up *.DEV.Tests.
        assert not _test_matches_environment("BestPractices.ANY.Tests", "DEV")
        assert not _test_matches_environment("Calculations.DEV.Tests", "ANY")
        assert _test_matches_environment("BestPractices.ANY.Tests", "ANY")

    def test_rejects_name_without_env_segment(self):
        assert not _test_matches_environment("Calcs.Tests", "DEV")

    def test_singular_test_suffix_supported(self):
        assert _test_matches_environment("ColumnTests.BKUP.Test", "BKUP")

    def test_rejects_non_test_suffix(self):
        assert not _test_matches_environment("Calculations.DEV.Measures", "DEV")


# ---------------------------------------------------------------------------
# _retrieve_tests_via_dax with environment
# ---------------------------------------------------------------------------

class TestRetrieveTestsViaDaxEnvironment:
    """V2("<env>") is tried first; parameterless fallbacks filter client-side."""

    _V2_ENV_ROWS = [
        {"PQL.Assert.RetrieveTestsV2()[Name]": "Calculations.DEV.Tests"},
        {"PQL.Assert.RetrieveTestsV2()[Name]": "Schema.DEV.Tests"},
    ]

    def test_env_passes_environment_to_v2(self):
        """--env DEV -> the first DAX query is RetrieveTestsV2("DEV")."""
        queries: list[str] = []

        def _fake_execute(conn, dax: str):
            queries.append(dax)
            return self._V2_ENV_ROWS

        conn = MagicMock()
        with patch("pql_test.runner._execute_dax_query", side_effect=_fake_execute):
            result = _retrieve_tests_via_dax(conn, environment="DEV")

        assert queries[0] == 'EVALUATE PQL.Assert.RetrieveTestsV2("DEV")'
        assert result is not None
        assert [t.name for t in result] == [
            "Calculations.DEV.Tests",
            "Schema.DEV.Tests",
        ]

    def test_env_server_filtered_results_not_refiltered(self):
        """Rows returned by V2("<env>") are trusted as-is — the UDF owns the
        matching semantics (it may e.g. include ANY suites for every env)."""
        rows = [{"PQL.Assert.RetrieveTestsV2()[Name]": "BestPractices.ANY.Tests"}]
        conn = MagicMock()
        with patch("pql_test.runner._execute_dax_query", return_value=rows):
            result = _retrieve_tests_via_dax(conn, environment="DEV")

        assert result is not None
        assert [t.name for t in result] == ["BestPractices.ANY.Tests"]

    def test_env_falls_back_to_parameterless_v2_with_client_filter(self):
        """V2("<env>") raises (older UDF without the parameter) -> V2() runs
        and the environment filter is applied by naming convention."""
        all_rows = [
            {"PQL.Assert.RetrieveTestsV2()[Name]": "Calculations.DEV.Tests"},
            {"PQL.Assert.RetrieveTestsV2()[Name]": "Schema.PROD.Tests"},
            {"PQL.Assert.RetrieveTestsV2()[Name]": "BestPractices.ANY.Tests"},
        ]

        def _fake_execute(conn, dax: str):
            if 'RetrieveTestsV2("' in dax:
                raise Exception("too many arguments")
            if "RetrieveTestsV2" in dax:
                return all_rows
            raise Exception("should not reach V1")

        conn = MagicMock()
        with patch("pql_test.runner._execute_dax_query", side_effect=_fake_execute):
            result = _retrieve_tests_via_dax(conn, environment="PROD")

        assert result is not None
        assert [t.name for t in result] == ["Schema.PROD.Tests"]

    def test_env_falls_back_to_v1_with_client_filter(self):
        """Both V2 forms raise -> V1 runs and the client-side filter applies."""
        v1_rows = [
            {"PQL.Assert.RetrieveTests()[Name]": "Calculations.DEV.Tests"},
            {"PQL.Assert.RetrieveTests()[Name]": "Backup.BKUP.Tests"},
        ]

        def _fake_execute(conn, dax: str):
            if "RetrieveTestsV2" in dax:
                raise Exception("not found")
            return v1_rows

        conn = MagicMock()
        with patch("pql_test.runner._execute_dax_query", side_effect=_fake_execute):
            result = _retrieve_tests_via_dax(conn, environment="BKUP")

        assert result is not None
        assert [t.name for t in result] == ["Backup.BKUP.Tests"]

    def test_no_env_does_not_call_parameterized_v2(self):
        """Without an environment the behavior is unchanged: plain V2 first."""
        queries: list[str] = []

        def _fake_execute(conn, dax: str):
            queries.append(dax)
            return []

        conn = MagicMock()
        with patch("pql_test.runner._execute_dax_query", side_effect=_fake_execute):
            _retrieve_tests_via_dax(conn)

        assert queries == ["EVALUATE PQL.Assert.RetrieveTestsV2()"]

    def test_env_quotes_are_escaped_in_dax_literal(self):
        """A double quote in the env name can't break out of the DAX string."""
        queries: list[str] = []

        def _fake_execute(conn, dax: str):
            queries.append(dax)
            return []

        conn = MagicMock()
        with patch("pql_test.runner._execute_dax_query", side_effect=_fake_execute):
            _retrieve_tests_via_dax(conn, environment='DE"V')

        assert queries[0] == 'EVALUATE PQL.Assert.RetrieveTestsV2("DE""V")'


# ---------------------------------------------------------------------------
# retrieve_tests(environment=...) — offline file scan
# ---------------------------------------------------------------------------

class TestRetrieveTestsEnvironmentFileScan:
    """Environment filtering on the offline DAXQueries/ file scan."""

    def _model(self, tmp_model) -> str:
        return tmp_model(
            [
                {
                    "suite_name": "Calculations.DEV",
                    "source": make_dax_source("Calculations.DEV.Tests"),
                },
                {
                    "suite_name": "Schema.PROD",
                    "source": make_dax_source("Schema.PROD.Tests"),
                },
                {
                    "suite_name": "BestPractices.ANY",
                    "source": make_dax_source("BestPractices.ANY.Tests"),
                },
            ]
        )

    def test_filters_to_requested_environment(self, tmp_model):
        tests = retrieve_tests(self._model(tmp_model), environment="DEV")
        assert [t.name for t in tests] == ["Calculations.DEV.Tests"]

    def test_any_selects_only_any_suites(self, tmp_model):
        tests = retrieve_tests(self._model(tmp_model), environment="ANY")
        assert [t.name for t in tests] == ["BestPractices.ANY.Tests"]

    def test_env_match_is_case_insensitive(self, tmp_model):
        tests = retrieve_tests(self._model(tmp_model), environment="prod")
        assert [t.name for t in tests] == ["Schema.PROD.Tests"]

    def test_unknown_environment_returns_empty(self, tmp_model):
        assert retrieve_tests(self._model(tmp_model), environment="UAT") == []

    def test_no_environment_returns_all(self, tmp_model):
        tests = retrieve_tests(self._model(tmp_model))
        assert len(tests) == 3

    def test_retrieve_test_by_name_respects_environment(self, tmp_model):
        model_dir = self._model(tmp_model)
        assert (
            retrieve_test_by_name(
                model_dir, "Calculations.DEV.Tests", environment="DEV"
            )
            is not None
        )
        assert (
            retrieve_test_by_name(
                model_dir, "Calculations.DEV.Tests", environment="PROD"
            )
            is None
        )


# ---------------------------------------------------------------------------
# retrieve_tests(environment=...) — live discovery + local ownership filter
# ---------------------------------------------------------------------------

class TestRetrieveTestsEnvironmentOwnershipFilter:
    """Live discovery with the local ownership set scoped to the environment."""

    def test_local_names_scoped_to_env_no_spurious_missing_warning(
        self, tmp_model, capsys
    ):
        """Local model declares DEV + PROD suites; live discovery (server-
        filtered to DEV) returns only the DEV suite.  The PROD suite must not
        produce a 'not registered in the deployed dataset' warning."""
        model_dir = tmp_model(
            [
                {
                    "suite_name": "Calculations.DEV",
                    "source": make_dax_source("Calculations.DEV.Tests"),
                },
                {
                    "suite_name": "Schema.PROD",
                    "source": make_dax_source("Schema.PROD.Tests"),
                },
            ]
        )
        live = [
            PqlTest(
                name="Calculations.DEV.Tests",
                file_path="",
                source="EVALUATE Calculations.DEV.Tests()",
            )
        ]
        conn = MagicMock()
        with patch("pql_test.runner._retrieve_tests_via_dax", return_value=live):
            tests = retrieve_tests(model_dir, connection=conn, environment="DEV")

        assert [t.name for t in tests] == ["Calculations.DEV.Tests"]
        err = capsys.readouterr().err
        assert "not registered in the deployed dataset" not in err

    def test_live_extras_not_declared_locally_are_skipped(self, tmp_model, capsys):
        """A live suite not declared locally for that env is filtered out."""
        model_dir = tmp_model(
            [
                {
                    "suite_name": "Calculations.DEV",
                    "source": make_dax_source("Calculations.DEV.Tests"),
                },
            ]
        )
        live = [
            PqlTest(
                name="Calculations.DEV.Tests",
                file_path="",
                source="EVALUATE Calculations.DEV.Tests()",
            ),
            PqlTest(
                name="Rogue.DEV.Tests",
                file_path="",
                source="EVALUATE Rogue.DEV.Tests()",
            ),
        ]
        conn = MagicMock()
        with patch("pql_test.runner._retrieve_tests_via_dax", return_value=live):
            tests = retrieve_tests(model_dir, connection=conn, environment="DEV")

        assert [t.name for t in tests] == ["Calculations.DEV.Tests"]
        assert "Rogue.DEV.Tests" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# run_tests_from_model(environment=...)
# ---------------------------------------------------------------------------

class TestRunTestsFromModelEnvironment:
    """run_tests_from_model threads the environment through discovery."""

    def test_only_matching_suites_are_executed_offline(self, tmp_model):
        model_dir = tmp_model(
            [
                {
                    "suite_name": "Calculations.DEV",
                    "source": make_dax_source("Calculations.DEV.Tests"),
                },
                {
                    "suite_name": "Schema.PROD",
                    "source": make_dax_source("Schema.PROD.Tests"),
                },
            ]
        )
        with patch("pql_test.runner.resolve_xmla_connection", return_value=None):
            suite = run_tests_from_model(model_dir, environment="DEV")

        assert len(suite.tests) == 1
        assert suite.tests[0].name == "Calculations.DEV.Tests"
        # No connection -> the one discovered suite reports as skipped.
        assert suite.total == 1
        assert suite.skipped == 1
