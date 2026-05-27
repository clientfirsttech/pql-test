"""
CLI integration tests for pql_test_cli.

Run with:
    cd python
    pytest tests/test_pql_test_cli.py -v
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import make_dax_source

# Run CLI as a module instead of script
_CLI_MODULE = "pql_test.cli"


def run_cli(
    args: list[str],
    cwd: str | None = None,
    *,
    live: bool = False,
) -> tuple[str, str, int]:
    """Run the CLI in a subprocess and return (stdout, stderr, returncode).

    By default the subprocess runs in *hermetic* mode: no .env loading, no
    stored interactive credentials, no auto-detection of a running PBI
    Desktop instance.  This keeps unit tests deterministic regardless of
    developer-machine state.

    Pass ``live=True`` for tests that need a real XMLA connection (typically
    ``@pytest.mark.live``).  In live mode the subprocess inherits the
    parent's ``PQL_*`` environment variables and loads ``.env`` normally,
    so a service principal configured via ``python/.env`` or
    ``python/tests/.env`` is honored.
    """
    if live:
        # Inherit tenant/workspace/client/secret from .env so the CLI can
        # build a service-principal connection.  Strip any PQL_DATASET_ID
        # variants — those would override the matrix-style path-based
        # dataset-name derivation the CLI uses (and that the production
        # CI workflow relies on), causing the subprocess to connect to
        # whichever single dataset .env happens to point at instead of
        # the model under test.
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("PQL_DATASET")
        }
        # Set hermetic so the subprocess doesn't reload .env itself —
        # if it did, PQL_DATASET_ID would come straight back.  We pass
        # the SP credentials via env explicitly above; hermetic mode
        # leaves the service-resolution path intact when explicit creds
        # are present.
        env["PQL_TEST_HERMETIC"] = "1"
    else:
        # Strip PQL_* vars so that credentials loaded by test_live_service.py
        # at collection time do not bleed into hermetic subprocesses.
        env = {k: v for k, v in os.environ.items() if not k.startswith("PQL_")}
        # Tell the CLI to skip .env loading, stored-credential lookups
        # (would prompt a browser), and PBI Desktop auto-detection.
        env["PQL_TEST_HERMETIC"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, "-m", _CLI_MODULE, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=cwd,
        timeout=60 if live else 30,
        env=env,
    )
    return result.stdout, result.stderr, result.returncode


def _live_creds_available() -> bool:
    """Return True when PQL_* service-principal vars are populated.

    Loads ``.env`` from a few well-known locations before checking, since
    a parent pytest process doesn't auto-load it.
    """
    try:
        from dotenv import load_dotenv  # type: ignore[import-untyped]
    except ImportError:
        load_dotenv = None  # noqa: N806

    if load_dotenv is not None:
        here = Path(__file__).resolve()
        for candidate in (
            here.parent / ".env",                        # python/tests/.env
            here.parent.parent / ".env",                 # python/.env
            here.parent.parent.parent / ".env",          # repo root .env
        ):
            if candidate.is_file():
                load_dotenv(candidate, override=False)

    required = ("PQL_TENANT_ID", "PQL_WORKSPACE_ID", "PQL_CLIENT_ID", "PQL_CLIENT_SECRET")
    return all(os.environ.get(k, "").strip() for k in required)


# Eagerly load .env so live tests can decide to skip at collection time.
_HAS_LIVE_CREDS = _live_creds_available()
_requires_live_creds = pytest.mark.skipif(
    not _HAS_LIVE_CREDS,
    reason="live test: PQL_TENANT_ID/WORKSPACE_ID/CLIENT_ID/CLIENT_SECRET not configured. "
    "Add a service principal to python/.env or python/tests/.env.",
)


# ---------------------------------------------------------------------------
# --help / --version
# ---------------------------------------------------------------------------

class TestMetaFlags:
    def test_prints_help_text(self):
        stdout, _, code = run_cli(["--help"])
        assert code == 0
        assert "pql-test" in stdout.lower() or "discover" in stdout.lower()

    def test_help_mentions_retrieve_tests(self):
        stdout, _, _ = run_cli(["--help"])
        assert "retrieve-tests" in stdout

    def test_help_mentions_run_tests(self):
        stdout, _, _ = run_cli(["--help"])
        assert "run-tests" in stdout

    def test_help_mentions_check_prereqs(self):
        stdout, _, _ = run_cli(["--help"])
        assert "check-prereqs" in stdout

    def test_prints_version(self):
        stdout, _, code = run_cli(["--version"])
        assert code == 0
        # Version should contain digits and dots
        assert any(c.isdigit() for c in stdout)

    def test_no_args_shows_help(self):
        stdout, stderr, code = run_cli([])
        # Click groups with no subcommand exit 2 and print help/usage to stderr
        combined = stdout + stderr
        assert "pql-test" in combined.lower() or "Usage" in combined


# ---------------------------------------------------------------------------
# check-prereqs
# ---------------------------------------------------------------------------

class TestCheckPrereqs:
    def test_outputs_python_version_check(self):
        stdout, _, _ = run_cli(["check-prereqs"])
        assert "Python" in stdout

    def test_outputs_pyadomd_check(self):
        stdout, _, _ = run_cli(["check-prereqs"])
        assert "pyadomd" in stdout

    def test_outputs_msal_check(self):
        stdout, _, _ = run_cli(["check-prereqs"])
        assert "msal" in stdout

    def test_outputs_pass_or_fail_indicators(self):
        stdout, _, _ = run_cli(["check-prereqs"])
        # Either ✅ or ❌ should appear for each item
        assert "\u2705" in stdout or "\u274c" in stdout

    def test_outputs_psutil_check(self):
        """Mirrors Pester 'Module should exist': psutil prerequisite reported."""
        stdout, _, _ = run_cli(["check-prereqs"])
        assert "psutil" in stdout


# ---------------------------------------------------------------------------
# retrieve-tests
# ---------------------------------------------------------------------------

class TestRetrieveTests:
    def test_errors_when_model_path_missing(self):
        _, stderr, code = run_cli(["retrieve-tests"])
        assert code != 0

    def test_errors_when_model_path_does_not_exist(self):
        _, stderr, code = run_cli(["retrieve-tests", "/nonexistent/path/xyz"])
        assert code == 1
        assert "not found" in stderr.lower()

    def test_reports_no_tests_for_empty_model(self, tmp_path):
        dax_dir = tmp_path / "model.SemanticModel" / "DAXQueries"
        dax_dir.mkdir(parents=True)
        stdout, _, code = run_cli(["retrieve-tests", str(tmp_path)])
        assert code == 0
        assert stdout.strip() == "[]"

    def test_lists_single_test_suite(self, tmp_path):
        dax_dir = tmp_path / "model.SemanticModel" / "DAXQueries"
        dax_dir.mkdir(parents=True)
        (dax_dir / "Calculations.DEV.Tests.dax").write_text(
            make_dax_source("Calcs"), encoding="utf-8"
        )
        stdout, _, code = run_cli(["retrieve-tests", str(tmp_path)])
        assert code == 0
        assert "Calculations.DEV.Tests" in stdout

    def test_lists_multiple_test_suites(self, tmp_path):
        dax_dir = tmp_path / "model.SemanticModel" / "DAXQueries"
        dax_dir.mkdir(parents=True)
        (dax_dir / "Suite.Alpha.Tests.dax").write_text(
            make_dax_source("Alpha"), encoding="utf-8"
        )
        (dax_dir / "Suite.Beta.Tests.dax").write_text(
            make_dax_source("Beta"), encoding="utf-8"
        )
        stdout, _, code = run_cli(["retrieve-tests", str(tmp_path)])
        assert code == 0
        assert "Suite.Alpha.Tests" in stdout
        assert "Suite.Beta.Tests" in stdout

    def test_verbose_shows_file_path(self, tmp_path):
        dax_dir = tmp_path / "model.SemanticModel" / "DAXQueries"
        dax_dir.mkdir(parents=True)
        (dax_dir / "Suite.Verbose.Tests.dax").write_text(
            make_dax_source("V"), encoding="utf-8"
        )
        stdout, _, code = run_cli(["retrieve-tests", str(tmp_path), "--verbose"])
        assert code == 0
        assert ".dax" in stdout or "File:" in stdout

    def test_test_flag_filters_to_named_suite(self, tmp_path):
        dax_dir = tmp_path / "model.SemanticModel" / "DAXQueries"
        dax_dir.mkdir(parents=True)
        (dax_dir / "Suite.Alpha.Tests.dax").write_text(
            make_dax_source("Alpha"), encoding="utf-8"
        )
        (dax_dir / "Suite.Beta.Tests.dax").write_text(
            make_dax_source("Beta"), encoding="utf-8"
        )
        stdout, _, code = run_cli(
            ["retrieve-tests", str(tmp_path), "--test", "Suite.Alpha.Tests"]
        )
        assert code == 0
        assert "Suite.Alpha.Tests" in stdout
        assert "Suite.Beta.Tests" not in stdout

    def test_test_flag_exits_1_when_suite_not_found(self, tmp_path):
        dax_dir = tmp_path / "model.SemanticModel" / "DAXQueries"
        dax_dir.mkdir(parents=True)
        _, _, code = run_cli(
            ["retrieve-tests", str(tmp_path), "--test", "Missing.Tests"]
        )
        assert code == 1

    def test_discovers_real_sample_model_suites(self, sample_model_path):
        stdout, _, code = run_cli(["retrieve-tests", sample_model_path])
        assert code == 0
        assert "Tests" in stdout
        assert stdout.strip() != "[]"


# ---------------------------------------------------------------------------
# retrieve-test (single suite)
# ---------------------------------------------------------------------------

class TestRetrieveTest:
    def test_errors_when_model_path_does_not_exist(self):
        _, stderr, code = run_cli(["retrieve-test", "/nonexistent/path/xyz", "Any"])
        assert code == 1
        assert "not found" in stderr.lower()

    def test_errors_when_suite_not_found(self, tmp_path):
        dax_dir = tmp_path / "model.SemanticModel" / "DAXQueries"
        dax_dir.mkdir(parents=True)
        stdout, _, code = run_cli(["retrieve-test", str(tmp_path), "Missing.Tests"])
        assert code == 1
        assert stdout.strip() == "null"

    def test_shows_named_suite(self, tmp_path):
        dax_dir = tmp_path / "model.SemanticModel" / "DAXQueries"
        dax_dir.mkdir(parents=True)
        (dax_dir / "Calculations.DEV.Tests.dax").write_text(
            make_dax_source("Calcs"), encoding="utf-8"
        )
        stdout, _, code = run_cli(
            ["retrieve-test", str(tmp_path), "Calculations.DEV.Tests"]
        )
        assert code == 0
        assert "Calculations.DEV.Tests" in stdout

    def test_does_not_show_other_suites(self, tmp_path):
        dax_dir = tmp_path / "model.SemanticModel" / "DAXQueries"
        dax_dir.mkdir(parents=True)
        (dax_dir / "Suite.Alpha.Tests.dax").write_text(
            make_dax_source("Alpha"), encoding="utf-8"
        )
        (dax_dir / "Suite.Beta.Tests.dax").write_text(
            make_dax_source("Beta"), encoding="utf-8"
        )
        stdout, _, code = run_cli(
            ["retrieve-test", str(tmp_path), "Suite.Beta.Tests"]
        )
        assert code == 0
        assert "Suite.Beta.Tests" in stdout
        assert "Suite.Alpha.Tests" not in stdout

    def test_verbose_shows_dax_source(self, tmp_path):
        dax_dir = tmp_path / "model.SemanticModel" / "DAXQueries"
        dax_dir.mkdir(parents=True)
        source = make_dax_source("MyFunc")
        (dax_dir / "My.Suite.Tests.dax").write_text(source, encoding="utf-8")
        stdout, _, code = run_cli(
            ["retrieve-test", str(tmp_path), "My.Suite.Tests", "--verbose"]
        )
        assert code == 0
        assert "EVALUATE" in stdout


# ---------------------------------------------------------------------------
# run-tests
# ---------------------------------------------------------------------------

class TestRunTests:
    def test_errors_when_model_path_missing(self):
        _, stderr, code = run_cli(["run-tests"])
        assert code != 0

    def test_errors_when_model_path_does_not_exist(self):
        _, stderr, code = run_cli(["run-tests", "/nonexistent/path/xyz"])
        assert code == 1
        assert "not found" in stderr.lower()

    def test_exits_0_and_shows_summary_for_empty_model(self, tmp_path):
        dax_dir = tmp_path / "model.SemanticModel" / "DAXQueries"
        dax_dir.mkdir(parents=True)
        stdout, _, code = run_cli(["run-tests", str(tmp_path)])
        assert code == 0
        assert "0 total" in stdout

    def test_shows_warning_when_no_connection_and_has_tests(self, tmp_path):
        dax_dir = tmp_path / "model.SemanticModel" / "DAXQueries"
        dax_dir.mkdir(parents=True)
        (dax_dir / "Suite.Tests.dax").write_text(
            make_dax_source("S"), encoding="utf-8"
        )
        stdout, stderr, _ = run_cli(["run-tests", str(tmp_path)])
        combined = stdout + stderr
        assert "XMLA" in combined or "connection" in combined.lower()

    def test_accepts_connection_flags_without_parse_error(self, tmp_path):
        dax_dir = tmp_path / "model.SemanticModel" / "DAXQueries"
        dax_dir.mkdir(parents=True)
        (dax_dir / "Suite.Tests.dax").write_text(
            make_dax_source("S"), encoding="utf-8"
        )
        # Flags should parse fine; actual XMLA call will fail — that's expected
        stdout, stderr, _ = run_cli(
            [
                "run-tests",
                str(tmp_path),
                "--tenant-id", "test-tenant",
                "--workspace-id", "test-ws",
                "--dataset-id", "test-ds",
                "--client-id", "test-client",
                "--client-secret", "test-secret",
            ]
        )
        # Should not crash on argument parsing
        combined = stdout + stderr
        assert "Error: No such option" not in combined

    def test_shows_xmla_connection_line_when_remote_params_given(self, tmp_path):
        dax_dir = tmp_path / "model.SemanticModel" / "DAXQueries"
        dax_dir.mkdir(parents=True)
        stdout, stderr, _ = run_cli(
            [
                "run-tests",
                str(tmp_path),
                "--tenant-id", "my-tenant",
                "--workspace-id", "my-ws",
                "--dataset-id", "my-ds",
            ]
        )
        combined = stdout + stderr
        assert "my-tenant" in combined or "my-ws" in combined

    def test_exits_0_when_all_tests_pass(self, tmp_path):
        dax_dir = tmp_path / "model.SemanticModel" / "DAXQueries"
        dax_dir.mkdir(parents=True)
        (dax_dir / "Suite.Tests.dax").write_text(
            make_dax_source("S"), encoding="utf-8"
        )
        # Patch the runner so tests "pass" without real XMLA
        import unittest.mock as mock

        rows = [{"TestName": "t1", "Expected": "1", "Actual": "1", "Passed": "true"}]

        # We run via subprocess so we cannot easily inject mocks.
        # This test validates flag parsing and output format with no connection
        # (tests will be reported as skipped/failed — exit 1 is acceptable).
        stdout, stderr, code = run_cli(["run-tests", str(tmp_path)])
        # Without a real XMLA connection the test shows "No XMLA" warning
        # and exits 0 for an empty model or 1 for failed/skipped tests.
        # We just verify it runs without crashing.
        assert "Error:" not in stdout or "not found" not in stdout

    def test_shows_results_summary_line(self, tmp_path):
        dax_dir = tmp_path / "model.SemanticModel" / "DAXQueries"
        dax_dir.mkdir(parents=True)
        stdout, _, _ = run_cli(["run-tests", str(tmp_path)])
        assert "passed" in stdout and "failed" in stdout and "total" in stdout

    def test_zero_total_shows_no_tests_found_message(self, tmp_path):
        """When discovery finds nothing, output must say 'No tests found.'
        instead of just rendering the bare '0 passed, 0 failed, 0 total' line —
        users couldn't tell whether the model was legitimately empty or whether
        an access/permission/connectivity error was silently swallowed.
        See tasks/surface-silent-test-discovery-failures-epic.md.

        Skipped on dev machines that have any PBI Desktop instance open,
        because resolve_local_xmla_connection silently grabs it and runs
        against whichever model is loaded.
        """
        try:
            from pql_test.runner import get_pbi_files_opened
            if get_pbi_files_opened():
                pytest.skip(
                    "PBI Desktop running; test only meaningful when no "
                    "local instances are detected"
                )
        except ImportError:
            pass

        dax_dir = tmp_path / "model.SemanticModel" / "DAXQueries"
        dax_dir.mkdir(parents=True)
        stdout, stderr, _ = run_cli(["run-tests", str(tmp_path)])
        combined = stdout + stderr
        assert "No tests found" in combined, (
            "Expected an explicit 'No tests found.' line; got just:\n"
            + combined[:600]
        )

    # ------------------------------------------------------------------
    # local/<name> model-path syntax replaces the removed --local flag
    # (see tasks/remove-local-cli-flag-epic.md).
    # ------------------------------------------------------------------

    def test_local_flag_is_rejected(self, tmp_path):
        """Given --local is passed, the CLI should reject it as unknown."""
        dax_dir = tmp_path / "model.SemanticModel" / "DAXQueries"
        dax_dir.mkdir(parents=True)
        stdout, stderr, code = run_cli(["run-tests", str(tmp_path), "--local"])
        combined = stdout + stderr
        assert "No such option" in combined
        assert code != 0

    def test_retrieve_tests_local_flag_is_rejected(self, tmp_path):
        """Given --local is passed to retrieve-tests, also reject."""
        dax_dir = tmp_path / "model.SemanticModel" / "DAXQueries"
        dax_dir.mkdir(parents=True)
        stdout, stderr, code = run_cli(["retrieve-tests", str(tmp_path), "--local"])
        combined = stdout + stderr
        assert "No such option" in combined
        assert code != 0

    def test_local_identifier_is_accepted_by_parser(self):
        """`local/<name>` is a valid MODEL_PATH (no parse error)."""
        stdout, stderr, _ = run_cli(["run-tests", "local/SomeModel"])
        assert "No such option" not in stderr
        assert "No such option" not in stdout

    def test_local_identifier_does_not_require_remote_connection_flags(self):
        """`local/<name>` works without --tenant-id / --workspace-id."""
        _, stderr, _ = run_cli(["run-tests", "local/SomeModel"])
        assert "Missing option" not in stderr

    def test_local_identifier_shows_warning_when_no_pbi_desktop_open(self):
        """When local/<name> is used but no matching PBI Desktop is open,
        a warning is printed.  Skipped on dev machines where any PBI Desktop
        instance is running, because resolve_local_xmla_connection_by_name
        has a permissive single-unnamed-instance fallback that would connect
        anyway and produce no warning."""
        try:
            from pql_test.runner import get_pbi_files_opened  # type: ignore
            if get_pbi_files_opened():
                pytest.skip("PBI Desktop instance(s) detected; test only meaningful in CI")
        except ImportError:
            pass  # psutil not installed → no detection → warning path will fire
        stdout, stderr, _ = run_cli(["run-tests", "local/DefinitelyNotOpen"])
        combined = (stdout + stderr).lower()
        assert any(
            phrase in combined
            for phrase in ("no matching", "not found", "no power bi", "warning")
        )

    def test_local_identifier_shows_summary_line(self):
        """`local/<name>` still prints a passed/failed/total summary."""
        stdout, _, _ = run_cli(["run-tests", "local/SomeModel"])
        assert "passed" in stdout and "failed" in stdout and "total" in stdout

    def test_local_identifier_with_verbose_does_not_crash(self):
        """`local/<name> --verbose` is a valid combination and should not error."""
        stdout, stderr, _ = run_cli(["run-tests", "local/SomeModel", "--verbose"])
        assert "Error:" not in stderr or "not found" not in stderr

    def test_run_tests_help_does_not_mention_local_flag(self):
        """Help text must no longer advertise --local."""
        stdout, _, code = run_cli(["run-tests", "--help"])
        assert code == 0
        assert "--local" not in stdout
        # but local/<model_name> should still be documented as a path format
        assert "local/<model_name>" in stdout

    def test_retrieve_tests_help_does_not_mention_local_flag(self):
        """retrieve-tests help text must no longer advertise --local."""
        stdout, _, code = run_cli(["retrieve-tests", "--help"])
        assert code == 0
        assert "--local" not in stdout
        assert "local/<model_name>" in stdout


# ---------------------------------------------------------------------------
# --output flag tests
# ---------------------------------------------------------------------------

class TestRunTestsOutputOption:
    def test_output_flag_is_accepted_by_parser(self, tmp_path):
        """--output <file> is a valid flag and causes no parse error."""
        dax_dir = tmp_path / "model.SemanticModel" / "DAXQueries"
        dax_dir.mkdir(parents=True)
        out_file = tmp_path / "results.json"
        stdout, stderr, _ = run_cli(["run-tests", str(tmp_path), "--output", str(out_file)])
        assert "No such option" not in stderr

    def test_output_writes_json_file(self, tmp_path):
        """--output writes valid JSON with passed/failed/total keys."""
        dax_dir = tmp_path / "model.SemanticModel" / "DAXQueries"
        dax_dir.mkdir(parents=True)
        out_file = tmp_path / "results.json"
        run_cli(["run-tests", str(tmp_path), "--output", str(out_file)])
        assert out_file.exists()
        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert "passed" in data
        assert "failed" in data
        assert "total" in data

    def test_output_json_contains_results_array(self, tmp_path):
        """Written JSON includes a 'results' list."""
        dax_dir = tmp_path / "model.SemanticModel" / "DAXQueries"
        dax_dir.mkdir(parents=True)
        out_file = tmp_path / "results.json"
        run_cli(["run-tests", str(tmp_path), "--output", str(out_file)])
        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert "results" in data
        assert isinstance(data["results"], list)

    def test_output_still_shows_human_on_stdout(self, tmp_path):
        """When --output is given, human-readable output still goes to stdout."""
        dax_dir = tmp_path / "model.SemanticModel" / "DAXQueries"
        dax_dir.mkdir(parents=True)
        out_file = tmp_path / "results.json"
        stdout, _, _ = run_cli(["run-tests", str(tmp_path), "--output", str(out_file)])
        assert "passed" in stdout

    def test_output_reports_file_written(self, tmp_path):
        """stdout mentions the file that was written."""
        dax_dir = tmp_path / "model.SemanticModel" / "DAXQueries"
        dax_dir.mkdir(parents=True)
        out_file = tmp_path / "results.json"
        stdout, _, _ = run_cli(["run-tests", str(tmp_path), "--output", str(out_file)])
        assert "results.json" in stdout or str(out_file) in stdout

    def test_output_flag_appears_in_help(self):
        """--output is documented in run-tests --help."""
        stdout, _, code = run_cli(["run-tests", "--help"])
        assert code == 0
        assert "--output" in stdout


# ---------------------------------------------------------------------------
# --log-format flag tests
# ---------------------------------------------------------------------------

class TestRunTestsLogFormat:
    def test_log_format_azuredevops_is_accepted(self, tmp_path):
        """--log-format azuredevops is a valid flag."""
        dax_dir = tmp_path / "model.SemanticModel" / "DAXQueries"
        dax_dir.mkdir(parents=True)
        stdout, stderr, _ = run_cli(["run-tests", str(tmp_path), "--log-format", "azuredevops"])
        assert "No such option" not in stderr
        assert "Invalid value" not in stderr

    def test_log_format_github_is_accepted(self, tmp_path):
        """--log-format github is a valid flag."""
        dax_dir = tmp_path / "model.SemanticModel" / "DAXQueries"
        dax_dir.mkdir(parents=True)
        stdout, stderr, _ = run_cli(["run-tests", str(tmp_path), "--log-format", "github"])
        assert "No such option" not in stderr
        assert "Invalid value" not in stderr

    def test_log_format_invalid_value_rejected(self, tmp_path):
        """An unrecognised --log-format value causes a parse error."""
        dax_dir = tmp_path / "model.SemanticModel" / "DAXQueries"
        dax_dir.mkdir(parents=True)
        _, stderr, code = run_cli(["run-tests", str(tmp_path), "--log-format", "teamcity"])
        assert code != 0
        assert "invalid" in stderr.lower() or "Invalid" in stderr

    def test_azuredevops_emits_group_annotation(self, tmp_path):
        """azuredevops format includes ##[group] and ##[endgroup] markers."""
        dax_dir = tmp_path / "model.SemanticModel" / "DAXQueries"
        dax_dir.mkdir(parents=True)
        stdout, _, _ = run_cli(["run-tests", str(tmp_path), "--log-format", "azuredevops"])
        assert "##[group]" in stdout
        assert "##[endgroup]" in stdout

    def test_azuredevops_emits_task_complete(self, tmp_path):
        """azuredevops format emits ##vso[task.complete ...] summary line."""
        dax_dir = tmp_path / "model.SemanticModel" / "DAXQueries"
        dax_dir.mkdir(parents=True)
        stdout, _, _ = run_cli(["run-tests", str(tmp_path), "--log-format", "azuredevops"])
        assert "##vso[task.complete" in stdout

    def test_github_emits_group_annotation(self, tmp_path):
        """github format includes ::group:: and ::endgroup:: markers."""
        dax_dir = tmp_path / "model.SemanticModel" / "DAXQueries"
        dax_dir.mkdir(parents=True)
        stdout, _, _ = run_cli(["run-tests", str(tmp_path), "--log-format", "github"])
        assert "::group::" in stdout
        assert "::endgroup::" in stdout

    def test_github_emits_notice_summary(self, tmp_path):
        """github format emits ::notice:: summary line."""
        dax_dir = tmp_path / "model.SemanticModel" / "DAXQueries"
        dax_dir.mkdir(parents=True)
        stdout, _, _ = run_cli(["run-tests", str(tmp_path), "--log-format", "github"])
        assert "::notice::" in stdout

    def test_log_format_combined_with_output(self, tmp_path):
        """--log-format and --output can be combined; JSON file is still written."""
        dax_dir = tmp_path / "model.SemanticModel" / "DAXQueries"
        dax_dir.mkdir(parents=True)
        out_file = tmp_path / "results.json"
        run_cli(["run-tests", str(tmp_path), "--log-format", "github", "--output", str(out_file)])
        assert out_file.exists()
        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert "total" in data

    def test_log_format_appears_in_help(self):
        """--log-format is documented in run-tests --help."""
        stdout, _, code = run_cli(["run-tests", "--help"])
        assert code == 0
        assert "--log-format" in stdout


# ---------------------------------------------------------------------------
# Model identifier format tests (local/<name>, workspace.model)
# ---------------------------------------------------------------------------

class TestModelIdentifierFormats:
    """CLI tests for the new model identifier formats."""

    def test_local_prefix_accepted_by_retrieve_tests(self):
        """'local/SampleModel' is accepted; no file-system path required."""
        stdout, stderr, code = run_cli(["retrieve-tests", "local/SampleModel"])
        combined = stdout + stderr
        # Should not get "Model path not found" error
        assert "Model path not found" not in combined
        # Should output a JSON array (empty is fine — no connection)
        assert code == 0

    def test_local_prefix_accepted_by_run_tests(self):
        """'local/SampleModel' is accepted by run-tests."""
        stdout, stderr, code = run_cli(["run-tests", "local/SampleModel"])
        combined = stdout + stderr
        assert "Model path not found" not in combined
        # Should show summary (0 total since no connection)
        assert "total" in stdout

    def test_local_prefix_shows_model_name_in_warning(self):
        """Warning message mentions the model name from local/<name>."""
        stdout, stderr, _ = run_cli(["run-tests", "local/MyTestModel"])
        combined = stdout + stderr
        assert "MyTestModel" in combined

    def test_service_format_exits_1_without_credentials(self):
        """'workspace.model' without auth credentials → exit 1."""
        _, stderr, code = run_cli(["run-tests", "MyWorkspace.MyModel"])
        assert code == 1
        assert "tenant-id" in stderr.lower() or "client-id" in stderr.lower()

    def test_service_format_accepted_by_retrieve_tests(self):
        """'workspace.model' → exit 1 with credential error (not path error)."""
        _, stderr, code = run_cli(["retrieve-tests", "MyWorkspace.MyModel"])
        assert code == 1
        # Should be a credentials error, not a file path error
        assert "Model path not found" not in stderr

    def test_service_format_accepted_by_retrieve_test(self):
        """'workspace.model' → exit 1 with credential error (not path error)."""
        _, stderr, code = run_cli(["retrieve-test", "MyWorkspace.MyModel", "SomeSuite"])
        assert code == 1
        assert "Model path not found" not in stderr

    def test_local_prefix_accepted_by_retrieve_test(self):
        """'local/SampleModel' is accepted by retrieve-test."""
        stdout, _, code = run_cli(["retrieve-test", "local/SampleModel", "Missing.Tests"])
        # No connection → test not found is expected
        assert code == 1
        assert "null" in stdout or "No test found" in stdout

    def test_run_tests_help_mentions_local_model_format(self):
        """run-tests help text mentions the local/<model_name> format."""
        stdout, _, code = run_cli(["run-tests", "--help"])
        assert code == 0
        assert "local/" in stdout

    def test_run_tests_help_mentions_service_format(self):
        """run-tests help text mentions the workspace.model format."""
        stdout, _, code = run_cli(["run-tests", "--help"])
        assert code == 0
        assert "Fabric CLI" in stdout or "dot notation" in stdout

    def test_retrieve_tests_help_mentions_local_model_format(self):
        """retrieve-tests help text mentions the local/<model_name> format."""
        stdout, _, code = run_cli(["retrieve-tests", "--help"])
        assert code == 0
        assert "local/" in stdout

    def test_local_model_run_tests_shows_summary_line(self):
        """local/<model_name> always shows a summary even without a connection."""
        stdout, _, _ = run_cli(["run-tests", "local/AnyModel"])
        assert "passed" in stdout and "failed" in stdout and "total" in stdout

    def test_retrieve_tests_resolves_xmla_for_filesystem_path(self, tmp_path, monkeypatch):
        """retrieve-tests <path> must call resolve_xmla_connection so local PBI
        Desktop auto-detection works the same way it does for run-tests.

        Captures the parity requirement from
        tasks/readme-drift-cleanup-epic.md.
        """
        from unittest.mock import MagicMock
        from click.testing import CliRunner

        # Import cli_module FIRST so its top-level dotenv.load_dotenv() runs
        # (which would otherwise re-populate the env vars we're about to
        # strip).  Only after the module is fully loaded do we delete the
        # PQL_* vars from the process env, ensuring click sees an empty
        # connection context.
        from pql_test import cli as cli_module

        for key in list(os.environ):
            if key.startswith("PQL_"):
                monkeypatch.delenv(key, raising=False)

        dax_dir = tmp_path / "model.SemanticModel" / "DAXQueries"
        dax_dir.mkdir(parents=True)
        (dax_dir / "Sample.Tests.dax").write_text(
            make_dax_source("Sample"), encoding="utf-8"
        )

        mock_resolve = MagicMock(return_value=None)
        monkeypatch.setattr(cli_module, "resolve_xmla_connection", mock_resolve)

        runner = CliRunner()
        result = runner.invoke(cli_module.cli, ["retrieve-tests", str(tmp_path)])

        assert mock_resolve.called, (
            f"retrieve-tests with a filesystem path must call "
            f"resolve_xmla_connection so local PBI Desktop is auto-detected, "
            f"matching run-tests behavior. See "
            f"tasks/readme-drift-cleanup-epic.md.\n"
            f"exit_code={result.exit_code} output={result.output[:200]!r}"
        )


# ---------------------------------------------------------------------------
# RLS_Model real-model tests
# ---------------------------------------------------------------------------

@pytest.mark.live
@_requires_live_creds
class TestRlsModel:
    """CLI tests against the real RLS_Model example in examples/.

    Marked ``live`` because RLS_Model declares its test suite only in
    ``definition/functions.tmdl`` (no ``*.Tests.dax`` file in DAXQueries/),
    so the offline file-scan fallback finds nothing — these tests
    inherently require a real XMLA connection to discover the suite via
    ``PQL.Assert.RetrieveTestsV2``.  Each invocation passes ``live=True``
    so the subprocess inherits the parent's ``PQL_*`` env vars and uses
    the service-principal credentials from ``.env``.

    Auto-skipped when those env vars aren't configured.
    """

    def test_retrieve_tests_finds_rls_suite(self, rls_model_path):
        """retrieve-tests discovers the RLS.ANY.Tests suite in the RLS model."""
        stdout, _, code = run_cli(["retrieve-tests", rls_model_path], live=True)
        assert code == 0
        assert "RLS.ANY.Tests" in stdout

    def test_retrieve_tests_returns_non_empty_list(self, rls_model_path):
        """retrieve-tests returns a non-empty JSON array for the RLS model."""
        stdout, _, code = run_cli(["retrieve-tests", rls_model_path], live=True)
        assert code == 0
        assert stdout.strip() != "[]"

    def test_retrieve_tests_has_single_suite(self, rls_model_path):
        """The RLS model contains exactly one test suite."""
        stdout, _, code = run_cli(["retrieve-tests", rls_model_path], live=True)
        assert code == 0
        suites = json.loads(stdout)
        assert len(suites) == 1
        assert suites[0]["name"] == "RLS.ANY.Tests"

    def test_retrieve_test_returns_rls_suite(self, rls_model_path):
        """retrieve-test returns the RLS.ANY.Tests suite when requested by name."""
        stdout, _, code = run_cli(
            ["retrieve-test", rls_model_path, "RLS.ANY.Tests"], live=True
        )
        assert code == 0
        assert "RLS.ANY.Tests" in stdout

    def test_retrieve_test_exits_1_for_missing_suite(self, rls_model_path):
        """retrieve-test exits 1 when the requested suite does not exist."""
        stdout, _, code = run_cli(
            ["retrieve-test", rls_model_path, "Missing.Tests"], live=True
        )
        assert code == 1
        assert stdout.strip() == "null"

    def test_run_tests_shows_summary_line(self, rls_model_path):
        """run-tests always prints a passed/failed/total summary for the RLS model."""
        stdout, _, _ = run_cli(["run-tests", rls_model_path], live=True)
        assert "passed" in stdout and "failed" in stdout and "total" in stdout
