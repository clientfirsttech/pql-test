# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for `pql-test contract run` (pql_test.contract_run)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from pql_test.contract_run import detect_pql_assert, exit_code
from pql_test.contract_run import xmla_unavailable as real_xmla_unavailable
from pql_test.runner import TestResult

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES = REPO_ROOT / "python" / "tests" / "odcs" / "fixtures"


@pytest.fixture(autouse=True)
def _xmla_available(monkeypatch):
    """Act as if pyadomd were installed (it is not on Linux CI); the tests stub the connection itself."""
    monkeypatch.setattr("pql_test.contract_run.xmla_unavailable", lambda: None)


def _result(suite: str, passed: bool = True, skipped: bool = False) -> TestResult:
    return TestResult(test_name=f"{suite}: t", passed=passed, message="", skipped=skipped, suite_name=suite)


class TestExitCode:
    def test_warning_suite_failures_do_not_fail_the_run(self):
        given = "a failure only in a DEVWARN suite"
        should = "exit 0, because warning-severity rules are non-blocking"
        results = [_result("M.DataQuality.DEV.Tests"), _result("M.DataQuality.DEVWARN.Tests", passed=False)]

        assert exit_code(results, {"M.DataQuality.DEV.Tests"}) == 0, f"{given}: {should}"

    def test_blocking_suite_failure_fails_the_run(self):
        given = "a failure in a DEV suite"
        should = "exit 1"
        results = [_result("M.DataQuality.DEV.Tests", passed=False)]

        assert exit_code(results, {"M.DataQuality.DEV.Tests"}) == 1, f"{given}: {should}"

    def test_nothing_executed_fails_the_run(self):
        given = "every result skipped (no XMLA connection)"
        should = "exit 1, matching run-tests, so CI misconfiguration is not a silent pass"
        results = [_result("M.Schema.DEV.Tests", skipped=True)]

        assert exit_code(results, {"M.Schema.DEV.Tests"}) == 1, f"{given}: {should}"


class TestDetectPqlAssert:
    @pytest.mark.parametrize("reported, expected", [("0.8.0", "0.8"), ("0.10.2", "0.8"), ("1.0.0", "0.8"), ("0.7.9", "0.7")])
    def test_version_reported_by_the_model_picks_the_catalog(self, monkeypatch, reported, expected):
        given = f"a model whose PQL.Assert.LibraryVersion() returns {reported}"
        should = f"select the {expected} catalog"
        monkeypatch.setattr("pql_test.contract_run._execute_dax_query", lambda *_a: [{"[Value]": reported}])

        assert detect_pql_assert(object()) == expected, f"{given}: {should}"

    def test_model_without_the_function_means_0_7(self, monkeypatch):
        given = "a model where EVALUATE PQL.Assert.LibraryVersion() raises (PQL.Assert 0.7.x)"
        should = "select the 0.7 catalog instead of failing the run"

        def boom(*_a):
            raise RuntimeError("function not found")

        monkeypatch.setattr("pql_test.contract_run._execute_dax_query", boom)

        assert detect_pql_assert(object()) == "0.7", f"{given}: {should}"

    def test_no_connection_means_0_7(self):
        given = "no XMLA connection"
        should = "select the 0.7 catalog without querying"

        assert detect_pql_assert(None) == "0.7", f"{given}: {should}"


class TestContractGroup:
    def test_offers_every_contract_command(self):
        given = "pql-test contract"
        should = "offer the file-only commands plus run and doctor in one group"
        from pql_test.cli import cli

        assert set(cli.commands["contract"].commands) == {"init", "lint", "coverage", "generate", "trace", "run", "doctor"}, (
            f"{given}: {should}"
        )


class TestContractRunCommand:
    def test_generates_runs_and_traces_without_a_connection(self, tmp_path, monkeypatch):
        given = "contract run against a PBIP copy with no XMLA connection available"
        should = (
            "leave the model folder untouched, report every mapped rule as not executed, write --output, exit 1, "
            "and not claim the catalog was detected from the model"
        )
        model = tmp_path / "Sample.SemanticModel"
        (model / "definition").mkdir(parents=True)
        shutil.copy(FIXTURES / "marvel.odcs.yaml", tmp_path / "marvel.odcs.yaml")
        # No Power BI in CI: stub only the external XMLA resolution.
        monkeypatch.setattr("pql_test.contract_run.resolve_xmla_connection", lambda *_a, **_k: None)
        from pql_test.cli import cli

        out = tmp_path / "results.json"
        result = CliRunner().invoke(
            cli, ["contract", "run", str(tmp_path / "marvel.odcs.yaml"), str(model), "--env", "DEV", "--output", str(out)]
        )

        saved = json.loads(out.read_text(encoding="utf-8"))
        assert (
            result.exit_code,
            sorted(p.name for p in model.iterdir()),
            "NOT EXECUTED" in result.output,
            saved["skipped"] > 0,
            saved["contract"]["summary"]["not_executed"] > 0,
            "0.7 catalog selected (no XMLA connection to ask the model" in result.output,
        ) == (1, ["definition"], True, True, True, True), f"{given}: {should}\n{result.output}"

    @pytest.mark.parametrize(
        "args, reported, expected",
        [
            ([], "0.8.0", "Col.NullCountShouldBeAtMost"),
            ([], None, "Col.NullRateShouldBeAtMost"),
            (["--pql-assert", "0.7"], "0.8.0", "Col.NullRateShouldBeAtMost"),
            (["--pql-assert", "0.8"], None, "Col.NullCountShouldBeAtMost"),
        ],
    )
    def test_catalog_follows_the_option_then_the_model(self, tmp_path, monkeypatch, args, reported, expected):
        given = f"contract run {args or 'with the default --pql-assert auto'} on a model reporting {reported}"
        should = f"generate calls containing {expected}"
        from types import SimpleNamespace

        model = tmp_path / "Sample.SemanticModel"
        (model / "definition").mkdir(parents=True)
        contract = tmp_path / "c.odcs.yaml"
        contract.write_text(
            "apiVersion: v3.1.0\nkind: DataContract\nid: c\nversion: '1'\nstatus: active\nschema:\n  - name: T\n    properties:\n      - name: a\n        logicalType: integer\n        required: true\n",
            encoding="utf-8",
        )
        monkeypatch.setattr("pql_test.contract_run.resolve_xmla_connection", lambda *_a, **_k: SimpleNamespace(server="s", catalog="c"))
        ran = []
        monkeypatch.setattr("pql_test.contract_run.run_tests", lambda tests, *_a, **_k: ran.extend(tests) or [])

        def library_version(*_a):
            if reported is None:
                raise RuntimeError("function not found")
            return [{"[Value]": reported}]

        monkeypatch.setattr("pql_test.contract_run._execute_dax_query", library_version)
        from pql_test.cli import cli

        result = CliRunner().invoke(cli, ["contract", "run", str(contract), str(model), "--env", "DEV", *args])

        text = "".join(t.source for t in ran)
        assert expected in text, f"{given}: {should}\n{result.output}"

    def test_invalid_contract_exits_1(self, tmp_path):
        given = "a contract with an unsupported apiVersion"
        should = "exit 1 before generating anything"
        bad = tmp_path / "bad.odcs.yaml"
        bad.write_text("apiVersion: v9.0.0\nkind: DataContract\nid: x\nversion: '1'\nstatus: active\n", encoding="utf-8")
        from pql_test.cli import cli

        result = CliRunner().invoke(cli, ["contract", "run", str(bad), str(tmp_path), "--env", "DEV"])

        assert (result.exit_code, "v3.2.x" in result.output) == (1, True), f"{given}: {should}"


class TestTraceAnnotations:
    def _report(self):
        from pql_test.odcs.api import plan_contract
        from pql_test.odcs.results import read_results, trace

        plan = plan_contract(FIXTURES / "marvel-must-fail.odcs.yaml")
        return trace(plan, read_results(FIXTURES / "results-marvel-must-fail.json"))

    def test_github_format_emits_one_error_per_failed_rule(self, capsys):
        given = "--log-format github and five failed contract rules"
        should = "emit one ::error annotation per failed rule, titled with the rule id"
        from pql_test.contract_run import print_trace_annotations

        print_trace_annotations(self._report(), "github")
        lines = capsys.readouterr().out.splitlines()

        assert (len(lines), all(line.startswith("::error title=ODCS rule ") for line in lines)) == (5, True), (
            f"{given}: {should}"
        )

    def test_azuredevops_format_uses_logissue(self, capsys):
        given = "--log-format azuredevops"
        should = "emit ##vso[task.logissue] lines"
        from pql_test.contract_run import print_trace_annotations

        print_trace_annotations(self._report(), "azuredevops")

        assert capsys.readouterr().out.startswith("##vso[task.logissue type=error]ODCS rule "), f"{given}: {should}"


class TestContractDoctor:
    @staticmethod
    def _doctor(monkeypatch, conn, reported, *args):
        """Run `pql-test contract doctor` on examples/SampleModel (PQL.Assert 0.8.0) with a stubbed connection."""
        monkeypatch.setattr("pql_test.contract_run.resolve_xmla_connection", lambda *_a, **_k: conn)

        def query(_conn, dax):
            if reported == "broken":
                raise RuntimeError("token expired")
            if reported == "no library" and "PQL.Assert" in dax:
                raise RuntimeError("function not found")
            if "LibraryVersion" not in dax:
                return [{"[Value]": 1}]
            if reported is None:
                raise RuntimeError("function not found")
            return [{"[Value]": reported}]

        monkeypatch.setattr("pql_test.contract_run._execute_dax_query", query)
        from pql_test.cli import cli

        model = REPO_ROOT / "examples" / "SampleModel.SemanticModel"
        return CliRunner().invoke(cli, ["contract", "doctor", str(model), "--format", "json", *args])

    def test_deployed_model_behind_the_folder_is_flagged(self, monkeypatch):
        given = "a model folder on PQL.Assert 0.8.0 whose deployed model has no LibraryVersion()"
        should = "add the live checks and warn that the deployed model is behind the folder"
        from types import SimpleNamespace

        result = self._doctor(monkeypatch, SimpleNamespace(server="s", catalog="c"), None)

        checks = {c["name"]: c for c in json.loads(result.output)["checks"]}
        assert (
            result.exit_code,
            checks["XMLA connection"]["status"],
            checks["Deployed PQL.Assert"]["detail"].startswith("0.7.x or older"),
            checks["Deployed vs. model folder"]["status"],
        ) == (0, "ok", True, "warn"), f"{given}: {should}\n{result.output}"

    def test_matching_deployed_library(self, monkeypatch):
        given = "a deployed model reporting PQL.Assert 0.8.0, like the folder"
        should = "report the deployed version and no drift"
        from types import SimpleNamespace

        result = self._doctor(monkeypatch, SimpleNamespace(server="s", catalog="c"), "0.8.0")

        checks = {c["name"]: c for c in json.loads(result.output)["checks"]}
        assert (checks["Deployed PQL.Assert"]["detail"], checks["Deployed vs. model folder"]["status"]) == (
            "0.8.0",
            "ok",
        ), f"{given}: {should}\n{result.output}"

    def test_connection_that_cannot_query_fails(self, monkeypatch):
        given = "a resolved connection whose queries fail (e.g. expired credentials)"
        should = "fail the connection check with the error, not report an old PQL.Assert"
        from types import SimpleNamespace

        result = self._doctor(monkeypatch, SimpleNamespace(server="s", catalog="c"), "broken")

        checks = {c["name"]: c for c in json.loads(result.output)["checks"]}
        assert (
            result.exit_code,
            checks["XMLA connection"]["status"],
            "token expired" in checks["XMLA connection"]["detail"],
            "Deployed PQL.Assert" in checks,
        ) == (1, "fail", True, False), f"{given}: {should}\n{result.output}"

    def test_deployed_model_without_pql_assert_fails(self, monkeypatch):
        given = "a deployed model with no PQL.Assert functions at all"
        should = "fail the deployed-library check instead of reporting 0.7.x"
        from types import SimpleNamespace

        result = self._doctor(monkeypatch, SimpleNamespace(server="s", catalog="c"), "no library")

        checks = {c["name"]: c for c in json.loads(result.output)["checks"]}
        assert (result.exit_code, checks["Deployed PQL.Assert"]["status"], "Deployed vs. model folder" in checks) == (
            1,
            "fail",
            False,
        ), f"{given}: {should}{chr(10)}{result.output}"

    def test_text_output_opens_like_other_connected_commands(self, monkeypatch):
        given = "pql-test contract doctor in text format with a connection"
        should = "open with the XMLA connection line, the session banner, and the model line"
        from types import SimpleNamespace

        monkeypatch.setattr(
            "pql_test.contract_run.resolve_xmla_connection", lambda *_a, **_k: SimpleNamespace(server="srv", catalog="cat")
        )
        monkeypatch.setattr("pql_test.contract_run._execute_dax_query", lambda *_a: [{"[Value]": "0.8.0"}])
        from pql_test.cli import cli

        model = str(REPO_ROOT / "examples" / "SampleModel.SemanticModel")
        result = CliRunner().invoke(cli, ["contract", "doctor", model])

        lines = result.output.splitlines()
        assert (lines[0], "contract doctor session starts" in lines[1], lines[2]) == (
            "XMLA connection: srv / catalog: cat",
            True,
            f"model: {model}",
        ), f"{given}: {should}{chr(10)}{result.output}"

    def test_no_connection_skips_the_live_checks(self, monkeypatch):
        given = "no XMLA connection"
        should = "warn once, skip the live checks, and still exit 0 on the offline result"

        result = self._doctor(monkeypatch, None, None)

        checks = {c["name"]: c for c in json.loads(result.output)["checks"]}
        assert (result.exit_code, checks["XMLA connection"]["status"], "Deployed PQL.Assert" in checks) == (
            0,
            "warn",
            False,
        ), f"{given}: {should}\n{result.output}"

    def test_text_output_uses_pql_test_status_labels(self, monkeypatch):
        given = "pql-test contract doctor in text format"
        should = "print a banner and PASS / WARN status labels"
        monkeypatch.setattr("pql_test.contract_run.resolve_xmla_connection", lambda *_a, **_k: None)
        from pql_test.cli import cli

        result = CliRunner().invoke(cli, ["contract", "doctor", str(REPO_ROOT / "examples" / "SampleModel.SemanticModel")])

        assert (result.exit_code, "contract doctor" in result.output, "PASS" in result.output, "WARN" in result.output) == (
            0,
            True,
            True,
            True,
        ), f"{given}: {should}\n{result.output}"

    def test_doctor_without_a_model_needs_no_connection(self, monkeypatch):
        given = "pql-test contract doctor with no MODEL_PATH"
        should = "run only the environment checks, never connecting"

        def no_connection(*_a, **_k):
            raise AssertionError("doctor without a model must not connect")

        monkeypatch.setattr("pql_test.contract_run.resolve_xmla_connection", no_connection)
        from pql_test.cli import cli

        result = CliRunner().invoke(cli, ["contract", "doctor", "--format", "json"])

        assert (result.exit_code, json.loads(result.output)["recommendedPqlAssert"]) == (0, None), (
            f"{given}: {should}\n{result.output}"
        )


class TestLocalModelPath:
    """`local/<model_name>`: run against the model open in Power BI Desktop, generating into its PBIP folder."""

    @staticmethod
    def _model(root: Path, name: str = "Sample") -> Path:
        model = root / f"{name}.SemanticModel"
        (model / "definition").mkdir(parents=True)
        return model

    @staticmethod
    def _invoke(*args):
        from pql_test.cli import cli

        return CliRunner().invoke(cli, ["contract", *[str(a) for a in args]])

    def test_run_needs_no_folder_for_the_open_model(self, tmp_path, monkeypatch):
        given = "contract run CONTRACT local/Sample from a folder with no Sample.SemanticModel"
        should = "ask the resolver for local/Sample as given, with no folder lookup and nothing written"
        (tmp_path / ".git").mkdir()
        monkeypatch.chdir(tmp_path)
        targets = []
        monkeypatch.setattr("pql_test.contract_run.resolve_xmla_connection", lambda target, _o: targets.append(target))

        result = self._invoke("run", FIXTURES / "marvel.odcs.yaml", "local/Sample", "--env", "DEV")

        assert (targets, "no files were written" in result.output, list(tmp_path.iterdir())) == (
            ["local/Sample"],
            True,
            [tmp_path / ".git"],
        ), f"{given}: {should}\n{result.output}"

    def test_write_saves_into_model_dir(self, tmp_path, monkeypatch):
        given = "contract run CONTRACT local/Sample --write --model-dir <folder>"
        should = "save the suites into that folder's DAXQueries/"
        model = self._model(tmp_path)
        monkeypatch.setattr("pql_test.contract_run.resolve_xmla_connection", lambda *_a, **_k: None)

        self._invoke("run", FIXTURES / "marvel.odcs.yaml", "local/Sample", "--write", "--model-dir", model, "--env", "DEV")

        assert (model / "DAXQueries" / "Marvel.Schema.DEV.Tests.dax").exists(), f"{given}: {should}"

    @pytest.mark.parametrize("option", [["--force"], ["--model-dir", "x"]])
    def test_write_only_options_need_write(self, tmp_path, option):
        given = f"contract run with {option[0]} and no --write"
        should = "exit 2: run writes no files without --write"
        model = self._model(tmp_path)

        result = self._invoke("run", FIXTURES / "marvel.odcs.yaml", model, "--env", "DEV", *option)

        assert (result.exit_code, f"{option[0]} goes with --write" in result.output) == (2, True), (
            f"{given}: {should}\n{result.output}"
        )

    def test_folder_is_found_from_the_repository_root(self, tmp_path, monkeypatch):
        given = "local/Sample run from a subfolder of a repository with examples/Sample.SemanticModel and a .venv copy"
        should = "find the folder from the repository root, skipping hidden folders"
        (tmp_path / ".git").mkdir()
        model = self._model(tmp_path / "examples")
        self._model(tmp_path / ".venv" / "lib")
        (tmp_path / "docs").mkdir()
        monkeypatch.chdir(tmp_path / "docs")
        from pql_test.odcs.pbip import require_semantic_model_dir

        assert require_semantic_model_dir("local/Sample") == model, f"{given}: {should}"

    def test_no_or_several_folders_are_model_path_errors(self, tmp_path):
        given = "local/Sample with no Sample.SemanticModel, then with two"
        should = "raise a model path error that says to pass the folder each time"
        from pql_test.odcs.pbip import ModelPathError, find_local_model_dir

        messages = []
        for copies in (0, 2):
            for i in range(copies):
                self._model(tmp_path / f"copy{i}")
            with pytest.raises(ModelPathError) as exc:
                find_local_model_dir("Sample", tmp_path)
            messages.append(str(exc.value))

        assert [("pass the folder" in m.lower(), "Several" in m) for m in messages] == [(True, False), (True, True)], (
            f"{given}: {should}\n{messages}"
        )

    def test_file_only_commands_accept_local(self, tmp_path, monkeypatch):
        given = "contract lint CONTRACT local/SampleModel from the repository's examples/ folder"
        should = "check the names against examples/SampleModel.SemanticModel without connecting"
        monkeypatch.chdir(REPO_ROOT / "examples")
        monkeypatch.setattr("pql_test.contract_run.resolve_xmla_connection", lambda *_a, **_k: pytest.fail("connected"))

        result = self._invoke("lint", FIXTURES / "marvel.odcs.yaml", "local/SampleModel")

        assert (result.exit_code, "names resolve" in result.output) == (0, True), f"{given}: {should}\n{result.output}"

    def test_model_dir_with_a_folder_model_path_is_a_usage_error(self, tmp_path):
        given = "--model-dir with a PBIP folder as MODEL_PATH"
        should = "exit 2: --model-dir only goes with local/<model_name>"
        model = self._model(tmp_path)

        result = self._invoke("doctor", model, "--model-dir", model)

        assert (result.exit_code, "--model-dir goes with a local/<model_name>" in result.output) == (2, True), (
            f"{given}: {should}\n{result.output}"
        )

    def test_doctor_fails_when_the_named_model_is_not_open(self, tmp_path, monkeypatch):
        given = "contract doctor local/Sample while no Desktop instance has Sample open"
        should = "fail the XMLA connection check with pql-test's list of open instances, and exit 1"
        model = self._model(tmp_path)
        (model / "definition" / "functions.tmdl").write_text(
            (REPO_ROOT / "examples" / "SampleModel.SemanticModel" / "definition" / "functions.tmdl").read_text(
                encoding="utf-8"
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr("pql_test.contract_run.resolve_xmla_connection", lambda *_a, **_k: None)
        monkeypatch.setattr("pql_test.cli._format_local_miss_diagnostic", lambda name: f"No instance for '{name}'.")

        result = self._invoke("doctor", "local/Sample", "--model-dir", model, "--format", "json")

        checks = {c["name"]: c for c in json.loads(result.output)["checks"]}
        assert (result.exit_code, checks["XMLA connection"]["status"], checks["XMLA connection"]["detail"]) == (
            1,
            "fail",
            "No instance for 'Sample'.",
        ), f"{given}: {should}\n{result.output}"


class TestWithoutXmla:
    """No pyadomd here (Linux): the file checks still run, and nothing tries to connect."""

    REASON = "XMLA needs ADOMD.NET, which runs on Windows only"

    @pytest.fixture(autouse=True)
    def _no_xmla(self, monkeypatch):
        monkeypatch.setattr("pql_test.contract_run.xmla_unavailable", lambda: self.REASON)
        monkeypatch.setattr("pql_test.contract_run.resolve_xmla_connection", lambda *_a, **_k: pytest.fail("connected"))

    @staticmethod
    def _doctor(model_path: str):
        from pql_test.cli import cli

        result = CliRunner().invoke(cli, ["contract", "doctor", model_path, "--format", "json"])
        return result, {c["name"]: c for c in json.loads(result.output)["checks"]}

    def test_doctor_warns_and_still_recommends(self):
        given = "contract doctor on examples/SampleModel where XMLA is unavailable"
        should = "pass with a warning that names the reason, and still recommend 0.8 from the TMDL"

        result, checks = self._doctor(str(REPO_ROOT / "examples" / "SampleModel.SemanticModel"))

        assert (result.exit_code, checks["XMLA connection"]["status"], self.REASON in checks["XMLA connection"]["detail"]) == (
            0,
            "warn",
            True,
        ), f"{given}: {should}\n{result.output}"

    def test_doctor_local_fails(self, monkeypatch):
        given = "contract doctor local/SampleModel where XMLA is unavailable"
        should = "fail: local/<name> asks for the open model, which cannot be reached"
        monkeypatch.chdir(REPO_ROOT)

        result, checks = self._doctor("local/SampleModel")

        assert (result.exit_code, checks["XMLA connection"]["status"]) == (1, "fail"), f"{given}: {should}\n{result.output}"

    def test_run_says_why_the_suites_did_not_run(self, tmp_path):
        given = "contract run where XMLA is unavailable"
        should = "say why the suites did not run, write nothing, and exit 1 (nothing ran)"
        model = tmp_path / "Sample.SemanticModel"
        (model / "definition").mkdir(parents=True)
        from pql_test.cli import cli

        result = CliRunner().invoke(cli, ["contract", "run", str(FIXTURES / "marvel.odcs.yaml"), str(model), "--env", "DEV"])

        assert (result.exit_code, (model / "DAXQueries").exists(), f"Warning: {self.REASON}." in result.output) == (
            1,
            False,
            True,
        ), f"{given}: {should}\n{result.output}"

    def test_off_windows_nothing_loads_or_downloads_adomd(self, monkeypatch):
        given = "Linux: the XMLA check, then the ADOMD.NET NuGet auto-install"
        should = "report Windows-only without starting the loader, and never download"
        from pql_test import runner
        from pql_test.runner.adomd import _auto_install_adomd_from_nuget

        monkeypatch.setattr("sys.platform", "linux")
        monkeypatch.setattr(runner, "has_pyadomd", lambda: pytest.fail("loaded ADOMD.NET"), raising=False)
        monkeypatch.setattr("urllib.request.urlretrieve", lambda *_a, **_k: pytest.fail("downloaded"))

        assert (real_xmla_unavailable(), _auto_install_adomd_from_nuget()) == (self.REASON, None), f"{given}: {should}"


def test_local_with_a_backslash_is_the_same_open_model(tmp_path):
    given = "local\\Sample (a Windows-style separator)"
    should = "become the local/Sample target, so the resolver connects to that open model only"
    from pql_test.contract_run import resolve_model_target

    assert resolve_model_target("local\\Sample", None) == ("local/Sample", "local/Sample"), f"{given}: {should}"


class TestRunFormat:
    def test_format_json_prints_the_results_with_the_trace(self, tmp_path, monkeypatch):
        given = "contract run --format json with no connection"
        should = "print run-tests' JSON plus the per-rule trace on stdout, and no report"
        model = tmp_path / "Sample.SemanticModel"
        (model / "definition").mkdir(parents=True)
        monkeypatch.setattr("pql_test.contract_run.resolve_xmla_connection", lambda *_a, **_k: None)
        from pql_test.cli import cli

        result = CliRunner().invoke(
            cli, ["contract", "run", str(FIXTURES / "marvel.odcs.yaml"), str(model), "--env", "DEV", "--format", "json"]
        )

        data = json.loads(result.stdout)  # stdout is only the JSON; notes go to stderr
        assert (sorted(data)[:2], "contract rules" in result.stdout) == (["contract", "failed"], False), (
            f"{given}: {should}\n{result.output}"
        )

    def test_format_json_and_log_format_are_a_usage_error(self, tmp_path):
        given = "contract run --format json --log-format github"
        should = "exit 2: both would claim stdout"
        from pql_test.cli import cli

        result = CliRunner().invoke(
            cli,
            ["contract", "run", str(FIXTURES / "marvel.odcs.yaml"), str(tmp_path), "--env", "DEV", "--format", "json", "--log-format", "github"],
        )

        assert (result.exit_code, "--format json and --log-format" in result.output) == (2, True), f"{given}: {should}"
