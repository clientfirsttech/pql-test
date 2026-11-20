# SPDX-License-Identifier: AGPL-3.0-only
"""A ``<name>.SemanticModel`` MODEL_PATH names the dataset; PQL_DATASET_ID is only a default.

See tasks/model-path-names-the-dataset-epic.md. The connection itself is stubbed: these tests
check which dataset the CLI asks the resolver for.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

FIXTURES = Path(__file__).resolve().parent / "odcs" / "fixtures"
ENV_GUID = "11111111-1111-1111-1111-111111111111"
FLAG_GUID = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def requested(monkeypatch):
    """Service credentials with PQL_DATASET_ID in the environment; collects the options each connect asks for."""
    for name, value in {
        "PQL_TENANT_ID": "t",
        "PQL_WORKSPACE_ID": "w",
        "PQL_CLIENT_ID": "c",
        "PQL_CLIENT_SECRET": "s",
        "PQL_DATASET_ID": ENV_GUID,
    }.items():
        monkeypatch.setenv(name, value)
    seen = []

    def record(_path, opts):
        seen.append((opts.dataset_id, opts.dataset_name))

    monkeypatch.setattr("pql_test.cli.resolve_xmla_connection", record)
    monkeypatch.setattr("pql_test.contract_run.resolve_xmla_connection", record)
    monkeypatch.setattr("pql_test.contract_run.xmla_unavailable", lambda: None)
    monkeypatch.setattr("pql_test.cli._exit_unless_windows", lambda _cmd: None)
    return seen


def _model(tmp_path: Path, folder: str) -> Path:
    model = tmp_path / folder
    (model / "definition").mkdir(parents=True)
    (model / "DAXQueries").mkdir()
    return model


def _invoke(*args: str):
    from pql_test.cli import cli

    return CliRunner().invoke(cli, list(args))


class TestFolderWinsOverEnvironment:
    def test_run_tests_uses_the_folder_model(self, tmp_path, requested):
        given = "run-tests on CodeCoverage.SemanticModel with PQL_DATASET_ID set in the environment"
        should = "connect to the CodeCoverage dataset, not the PQL_DATASET_ID one"
        model = _model(tmp_path, "CodeCoverage.SemanticModel")

        _invoke("run-tests", str(model))

        assert requested == [(None, "CodeCoverage")], f"{given}: {should}"

    def test_says_the_folder_replaced_the_environment(self, tmp_path, requested):
        given = "the folder replacing PQL_DATASET_ID"
        should = "say which model it uses and how to pick another dataset"
        model = _model(tmp_path, "CodeCoverage.SemanticModel")

        result = _invoke("run-tests", str(model))

        assert "PQL_DATASET_ID" in result.output and "CodeCoverage" in result.output and "--dataset-id" in result.output, (
            f"{given}: {should}\n{result.output}"
        )

    def test_contract_run_uses_the_folder_model(self, tmp_path, requested):
        given = "contract run on CodeCoverage.SemanticModel with PQL_DATASET_ID set in the environment"
        should = "connect to the CodeCoverage dataset, not the PQL_DATASET_ID one"
        model = _model(tmp_path, "CodeCoverage.SemanticModel")
        shutil.copy(FIXTURES / "marvel.odcs.yaml", tmp_path / "marvel.odcs.yaml")

        _invoke("contract", "run", str(tmp_path / "marvel.odcs.yaml"), str(model), "--env", "DEV")

        assert requested == [(None, "CodeCoverage")], f"{given}: {should}"


class TestExplicitChoicesStillWin:
    def test_dataset_id_flag_beats_the_folder(self, tmp_path, requested):
        given = "run-tests on CodeCoverage.SemanticModel with --dataset-id on the command line"
        should = "connect to the dataset that ID identifies"
        model = _model(tmp_path, "CodeCoverage.SemanticModel")

        _invoke("run-tests", str(model), "--dataset-id", FLAG_GUID)

        assert requested == [(FLAG_GUID, None)], f"{given}: {should}"

    def test_a_path_that_names_no_model_keeps_the_environment(self, tmp_path, requested):
        given = "run-tests on a folder that is not <name>.SemanticModel, with PQL_DATASET_ID set"
        should = "keep using PQL_DATASET_ID"
        model = _model(tmp_path, "models")

        _invoke("run-tests", str(model))

        assert requested == [(ENV_GUID, None)], f"{given}: {should}"

    def test_local_model_path_says_nothing_about_the_dataset(self, tmp_path, requested, monkeypatch):
        given = "contract run local/CodeCoverage --write with PQL_DATASET_ID set"
        should = "not mention PQL_DATASET_ID, because a local/ path never uses a dataset"
        model = _model(tmp_path, "CodeCoverage.SemanticModel")
        shutil.copy(FIXTURES / "marvel.odcs.yaml", tmp_path / "marvel.odcs.yaml")

        result = _invoke(
            "contract", "run", str(tmp_path / "marvel.odcs.yaml"), "local/CodeCoverage",
            "--env", "DEV", "--write", "--model-dir", str(model),
        )

        assert "PQL_DATASET_ID" not in result.output, f"{given}: {should}\n{result.output}"
