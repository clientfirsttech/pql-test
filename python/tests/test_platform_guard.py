# SPDX-License-Identifier: AGPL-3.0-only
"""Off Windows, XMLA commands stop with one message; file-based commands keep working."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from pql_test.cli import cli

SAMPLE = Path(__file__).resolve().parents[2] / "examples" / "SampleModel.SemanticModel"


@pytest.fixture
def linux(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setenv("PQL_TEST_HERMETIC", "1")  # no Desktop scan, stored credentials, or ADOMD.NET download
    monkeypatch.setattr("pql_test.cli.resolve_xmla_connection", lambda *_a, **_k: pytest.fail("tried to connect"))


@pytest.mark.parametrize("command", ["run-tests", "code-coverage"])
def test_xmla_commands_stop_with_one_windows_only_message(linux, command):
    given = f"pql-test {command} on Linux"
    should = "exit 1 with a single Windows-only message, before any connection attempt"

    result = CliRunner().invoke(cli, [command, str(SAMPLE)])

    assert (result.exit_code, "runs on Windows only" in result.output, result.output.count("Error:")) == (1, True, 1), (
        f"{given}: {should}\n{result.output}"
    )


def test_retrieve_tests_reads_the_pbip_files(linux):
    given = "pql-test retrieve-tests on a PBIP folder on Linux"
    should = "list the suites from DAXQueries/ without XMLA"

    result = CliRunner().invoke(cli, ["retrieve-tests", str(SAMPLE)])

    assert (result.exit_code, "Schema.DEV.Tests" in result.output) == (0, True), f"{given}: {should}\n{result.output}"


def test_retrieve_test_by_name_reads_the_pbip_files(linux):
    given = "pql-test retrieve-test on a PBIP folder on Linux"
    should = "show the suite from DAXQueries/ without XMLA"

    result = CliRunner().invoke(cli, ["retrieve-test", str(SAMPLE), "Schema.DEV.Tests"])

    assert (result.exit_code, "Schema.DEV.Tests" in result.output) == (0, True), f"{given}: {should}\n{result.output}"


@pytest.mark.parametrize("command", [["retrieve-tests", "local/SampleModel"], ["retrieve-test", "local/SampleModel", "X"]])
def test_retrieve_from_an_open_model_needs_windows(linux, command):
    given = f"pql-test {' '.join(command)} on Linux"
    should = "exit 1 with the Windows-only message: local/<name> only exists over XMLA"

    result = CliRunner().invoke(cli, command)

    assert (result.exit_code, "runs on Windows only" in result.output) == (1, True), f"{given}: {should}\n{result.output}"
