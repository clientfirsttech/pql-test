# SPDX-License-Identifier: AGPL-3.0-only
"""`pql-test contract doctor`: environment and PBIP model file checks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from pql_test.cli import cli
from pql_test.odcs.cli import contract
from pql_test.odcs.doctor import Check, DoctorReport, recommend_catalog, run_doctor
from pql_test.odcs.udf import parse_functions

EXAMPLES = Path(__file__).resolve().parents[3] / "examples"


def _statuses(report: DoctorReport) -> dict[str, str]:
    return {c.name: c.status for c in report.checks}


def _model(tmp_path: Path, functions_tmdl: str | None) -> Path:
    model = tmp_path / "M.SemanticModel"
    (model / "definition").mkdir(parents=True)
    if functions_tmdl is not None:
        (model / "definition" / "functions.tmdl").write_text(functions_tmdl, encoding="utf-8")
    return model


def _fn(name: str, version: str = "0.7.1") -> str:
    return (
        f"function '{name}' =\n\t\t() => 1\n"
        f"\tannotation DAXLIB_PackageId = PQL.Assert\n\tannotation DAXLIB_PackageVersion = {version}\n"
    )


class TestEnvironment:
    def test_environment_only(self):
        given = "doctor with no MODEL_PATH"
        should = "pass the environment checks and make no recommendation"

        report = run_doctor()

        assert (report.ok, report.recommended, {"Python", "pql-test", "ODCS schemas"} <= set(_statuses(report))) == (
            True,
            None,
            True,
        ), f"{given}: {should}\n{report.checks}"



class TestModel:
    def test_sample_model_on_0_9_0(self):
        given = "examples/SampleModel (PQL.Assert 0.9.0)"
        should = "recommend --pql-assert 0.9"

        report = run_doctor(EXAMPLES / "SampleModel.SemanticModel")

        assert (report.ok, report.recommended) == (True, "0.9"), f"{given}: {should}\n{report.checks}"

    def test_rls_model_on_0_4_0(self):
        given = "examples/RLS_Model (PQL.Assert 0.4.0)"
        should = "recommend 0.7, and say 0.8 needs PQL.Assert 0.8.0 with an example of a missing function"

        report = run_doctor(EXAMPLES / "RLS_Model.SemanticModel")

        check = next(c for c in report.checks if c.name == "--pql-assert")
        hints = ("PQL.Assert 0.8.0 or later" in check.detail, "Col.DuplicateCountShouldBeAtMost" in check.detail)
        assert (report.ok, report.recommended, hints) == (True, "0.7", (True, True)), (
            f"{given}: {should}\n{report.checks}"
        )

    def test_not_a_pbip_model(self, tmp_path):
        given = "a MODEL_PATH that is not a PBIP model"
        should = "fail the model check"

        report = run_doctor(tmp_path)

        assert (report.ok, _statuses(report).get("PBIP model")) == (False, "fail"), f"{given}: {should}"

    def test_model_without_pql_assert(self, tmp_path):
        given = "a PBIP model with no PQL.Assert functions"
        should = "fail with a hint to install PQL.Assert, and recommend nothing"

        report = run_doctor(_model(tmp_path, None))

        check = next(c for c in report.checks if c.name == "PQL.Assert library")
        assert (report.ok, report.recommended, check.status, "DAX Lib" in check.detail) == (False, None, "fail", True), (
            f"{given}: {should}\n{report.checks}"
        )

    def test_mixed_versions_warn(self, tmp_path):
        given = "a model whose PQL.Assert functions carry two versions"
        should = "warn and name both versions"

        report = run_doctor(_model(tmp_path, _fn("PQL.Assert.A", "0.7.1") + _fn("PQL.Assert.B", "0.8.0")))

        check = next(c for c in report.checks if c.name == "PQL.Assert library")
        assert (check.status, "0.7.1" in check.detail, "0.8.0" in check.detail) == ("warn", True, True), (
            f"{given}: {should}"
        )

    def test_unannotated_library_warns(self, tmp_path):
        given = "PQL.Assert functions with no DAXLIB_PackageVersion annotation"
        should = "warn that the version is unknown"
        text = "function 'PQL.Assert.A' =\n\t\t() => 1\n\tannotation DAXLIB_PackageId = PQL.Assert\n"

        report = run_doctor(_model(tmp_path, text))

        check = next(c for c in report.checks if c.name == "PQL.Assert library")
        assert (check.status, "DAXLIB_PackageVersion" in check.detail) == ("warn", True), f"{given}: {should}"

    def test_dax_queries_folder_is_optional(self, tmp_path):
        given = "a PBIP model with no DAXQueries/ folder"
        should = "not fail, since generate creates it"

        report = run_doctor(_model(tmp_path, None))

        assert _statuses(report)["DAXQueries/"] == "ok", f"{given}: {should}"


class TestRecommendCatalog:
    def test_incomplete_library_recommends_nothing(self):
        given = "a model with only one PQL.Assert function"
        should = "recommend no catalog and list what the 0.7 catalog still needs"

        choice, missing = recommend_catalog(parse_functions(_fn("PQL.Assert.Tbl.ShouldExist")))

        assert (choice, "PQL.Assert.Tbl.ShouldExist" in missing["0.7"], len(missing["0.7"]) > 0) == (
            None,
            False,
            True,
        ), f"{given}: {should}"


class TestCli:
    """Through `pql-test contract doctor`, with no XMLA connection (the file checks only)."""

    @pytest.fixture(autouse=True)
    def _no_connection(self, monkeypatch):
        monkeypatch.setattr("pql_test.contract_run.resolve_xmla_connection", lambda *_a, **_k: None)

    def test_json_format(self):
        given = "doctor --format json on SampleModel"
        should = "emit one JSON report with the recommendation and every check"

        result = CliRunner().invoke(cli, ["contract", "doctor", str(EXAMPLES / "SampleModel.SemanticModel"), "--format", "json"])

        data = json.loads(result.output)
        assert (result.exit_code, data["ok"], data["recommendedPqlAssert"], len(data["checks"]) > 5) == (
            0,
            True,
            "0.9",
            True,
        ), f"{given}: {should}\n{result.output}"

    def test_failed_check_exits_1_and_text_marks_it(self, tmp_path):
        given = "doctor on a folder that is not a PBIP model"
        should = "exit 1 and mark the failed check FAIL"

        result = CliRunner().invoke(cli, ["contract", "doctor", str(tmp_path)])

        assert (result.exit_code, "FAIL PBIP model" in result.output) == (1, True), f"{given}: {should}\n{result.output}"

    def test_text_format_ends_with_the_recommendation(self):
        given = "doctor on SampleModel"
        should = "end with the --pql-assert recommendation"

        result = CliRunner().invoke(cli, ["contract", "doctor", str(EXAMPLES / "SampleModel.SemanticModel")])

        assert (result.exit_code, result.output.rstrip().splitlines()[-1]) == (
            0,
            "Use --pql-assert 0.9 with generate, coverage, and trace for this model.",
        ), f"{given}: {should}\n{result.output}"


def test_report_json_shape():
    given = "a report with one warning"
    should = "stay ok and serialise each check"
    report = DoctorReport([Check("x", "warn", "d")], recommended=None)

    assert report.to_json() == {
        "ok": True,
        "recommendedPqlAssert": None,
        "checks": [{"name": "x", "status": "warn", "detail": "d"}],
    }, f"{given}: {should}"


class TestGenerateAuto:
    def _contract(self, tmp_path):
        path = tmp_path / "c.odcs.yaml"
        path.write_text(
            "apiVersion: v3.1.0\nkind: DataContract\nid: c\nversion: '1'\nstatus: active\nschema:\n"
            "  - name: T\n    properties:\n      - name: a\n        logicalType: integer\n        required: true\n",
            encoding="utf-8",
        )
        return path

    def test_auto_reads_the_model_folder(self, tmp_path):
        given = "generate --pql-assert auto into a copy of SampleModel (PQL.Assert 0.9.0)"
        should = "use a catalog the model supports and say where the choice came from"
        import shutil

        shutil.copytree(EXAMPLES / "SampleModel.SemanticModel", tmp_path / "SampleModel.SemanticModel")

        result = CliRunner().invoke(
            contract,
            ["generate", str(self._contract(tmp_path)), str(tmp_path), "--env", "DEV", "--pql-assert", "auto", "--dry-run"],
        )

        assert (result.exit_code, "Col.NullCountShouldBeAtMost" in result.output, "functions.tmdl" in result.output) == (
            0,
            True,
            True,
        ), f"{given}: {should}\n{result.output}"

    def test_auto_without_pql_assert_falls_back_to_0_7(self, tmp_path):
        given = "generate --pql-assert auto into a model with no PQL.Assert functions"
        should = "fall back to the 0.7 catalog and say so"
        model = _model(tmp_path, None)

        result = CliRunner().invoke(
            contract,
            ["generate", str(self._contract(tmp_path)), str(model), "--env", "DEV", "--pql-assert", "auto", "--dry-run"],
        )

        assert (result.exit_code, "Col.NullRateShouldBeAtMost" in result.output, "using 0.7" in result.output) == (
            0,
            True,
            True,
        ), f"{given}: {should}\n{result.output}"
