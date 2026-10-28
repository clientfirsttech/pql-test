# SPDX-License-Identifier: AGPL-3.0-only
"""The CLI argument conventions (CONTRIBUTING.md, "CLI Argument Conventions"), checked on every command."""

from __future__ import annotations

from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from pql_test.cli import cli
from pql_test.cli_options import (
    deprecated_alias,
    emit_result,
    format_option,
    verbosity_options,
)

SAMPLE = Path(__file__).resolve().parents[2] / "examples" / "SampleModel.SemanticModel"

# Commands that print a report: -v/--verbose and -q/--quiet.
REPORT_COMMANDS = {
    "check-prereqs", "retrieve-tests", "retrieve-test", "run-tests", "code-coverage", "auth status",
    "contract init", "contract lint", "contract coverage", "contract generate", "contract trace",
    "contract run", "contract doctor",
}  # fmt: skip
# Report commands whose result is files rather than a report have no --format.
NO_FORMAT = {"contract init", "contract generate"}
# Old spellings that must stay hidden (they still work, with a warning).
DEPRECATED = {"--human", "-u", "--user", "-p", "--password", "--tenant", "--environment"}


def _commands(group: click.Group = cli, prefix: str = "") -> dict[str, click.Command]:
    found = {}
    for name, command in group.commands.items():
        if isinstance(command, click.Group):
            found.update(_commands(command, f"{prefix}{name} "))
        else:
            found[f"{prefix}{name}"] = command
    return found


def _options(command: click.Command) -> dict[str, click.Option]:
    return {opt: p for p in command.params if isinstance(p, click.Option) for opt in p.opts + p.secondary_opts}


COMMANDS = _commands()


def test_every_report_command_is_listed():
    given = "the CLI's commands"
    should = "include every command the conventions name, so a renamed command fails here"

    assert REPORT_COMMANDS <= set(COMMANDS), f"{given}: {should}: {sorted(REPORT_COMMANDS - set(COMMANDS))}"


@pytest.mark.parametrize("name", sorted(REPORT_COMMANDS))
def test_report_commands_take_verbose_quiet_and_format(name):
    given = f"pql-test {name}"
    should = "take -v/--verbose and -q/--quiet, and --format text|json unless its result is files"
    options = _options(COMMANDS[name])

    has = {flag for flag in ("-v", "--verbose", "-q", "--quiet", "--format") if flag in options}
    expected = {"-v", "--verbose", "-q", "--quiet"} | (set() if name in NO_FORMAT else {"--format"})
    choices = set(options["--format"].type.choices) if "--format" in options else {"text", "json"}

    assert (has, choices) == (expected, {"text", "json"}), f"{given}: {should}"


@pytest.mark.parametrize("name", sorted(COMMANDS))
def test_output_has_the_short_form_and_old_spellings_are_hidden(name):
    given = f"pql-test {name}"
    should = "pair --output with -o, give -v/-q one meaning, and keep deprecated spellings out of --help"
    options = _options(COMMANDS[name])

    shown = {opt for opt, p in options.items() if not p.hidden}
    problems = []
    if "--output" in options and "-o" not in options["--output"].opts:
        problems.append("--output without -o")
    for short, long in (("-v", "--verbose"), ("-q", "--quiet"), ("-o", "--output")):
        if short in options and long not in options[short].opts:
            problems.append(f"{short} is not {long}")
    problems += sorted(f"{opt} is shown" for opt in shown & DEPRECATED)

    assert problems == [], f"{given}: {should}: {problems}"


class TestBehaviour:
    @pytest.fixture(autouse=True)
    def _offline(self, monkeypatch):
        monkeypatch.setenv("PQL_TEST_HERMETIC", "1")  # no Desktop scan, stored credentials, or ADOMD.NET download

    def test_quiet_prints_only_the_summary_line(self):
        given = "retrieve-tests --format text -q on SampleModel"
        should = "print one line: the summary"

        result = CliRunner().invoke(cli, ["retrieve-tests", str(SAMPLE), "--format", "text", "-q"])

        assert (result.exit_code, result.stdout.splitlines()) == (0, ["Found 4 DAX test suite(s)."]), (
            f"{given}: {should}\n{result.output}"
        )

    def test_quiet_never_suppresses_json(self):
        given = "retrieve-tests -q with the default JSON format"
        should = "still print the JSON: it is the result, not a report"
        import json

        result = CliRunner().invoke(cli, ["retrieve-tests", str(SAMPLE), "-q"])

        assert len(json.loads(result.stdout)) == 4, f"{given}: {should}\n{result.output}"

    def test_quiet_and_verbose_together_are_a_usage_error(self):
        given = "check-prereqs -q -v"
        should = "exit 2"

        result = CliRunner().invoke(cli, ["check-prereqs", "-q", "-v"])

        assert (result.exit_code, "only one of --quiet and --verbose" in result.output) == (2, True), f"{given}: {should}"

    def test_human_still_works_and_warns(self):
        given = "retrieve-test SampleModel Schema.DEV.Tests --human (the old spelling)"
        should = "behave as --format text and warn on stderr"

        result = CliRunner().invoke(cli, ["retrieve-test", str(SAMPLE), "Schema.DEV.Tests", "--human"])

        assert (
            result.exit_code,
            "Found 1 DAX test suite(s)" in result.stdout,
            "--human is deprecated; use --format text" in result.stderr,
        ) == (0, True, True), f"{given}: {should}\n{result.output}"

    @pytest.mark.parametrize("args", [["--test", "Schema.DEV.Tests"], ["Schema.DEV.Tests"]])
    def test_retrieve_test_takes_name_or_test(self, args):
        given = f"retrieve-test SampleModel {' '.join(args)}"
        should = "show the suite either way"

        result = CliRunner().invoke(cli, ["retrieve-test", str(SAMPLE), *args, "--format", "text"])

        assert (result.exit_code, "Schema.DEV.Tests" in result.stdout) == (0, True), f"{given}: {should}\n{result.output}"


class TestDeprecatedAlias:
    @staticmethod
    def _command():
        @click.command()
        @deprecated_alias("-u", "--user", to="client_id", use="--client-id")
        @click.option("--client-id")
        @deprecated_alias("--human", to="output_format", use="--format text", value="text")
        @format_option(default="json")
        @verbosity_options()
        def cmd(client_id, output_format):
            emit_result(f"{client_id} {output_format}")  # the result: stdout even with --format json

        return cmd

    @pytest.mark.parametrize(
        ("args", "printed"),
        [
            (["-u", "abc"], "abc json"),
            (["--user", "abc"], "abc json"),
            (["--client-id", "abc"], "abc json"),
            (["--human"], "None text"),
            (["--user", "abc", "--client-id", "abc"], "abc json"),
        ],
    )
    def test_alias_fills_the_new_option(self, args, printed):
        given = f"the old spelling {args}"
        should = f"behave as the new one ({printed!r})"

        result = CliRunner().invoke(self._command(), args)

        assert (result.exit_code, result.stdout.strip()) == (0, printed), f"{given}: {should}\n{result.output}"

    def test_alias_and_new_option_disagreeing_is_a_usage_error(self):
        given = "--user abc --client-id xyz"
        should = "exit 2: the two spellings disagree"

        result = CliRunner().invoke(self._command(), ["--user", "abc", "--client-id", "xyz"])

        assert (result.exit_code, "disagree" in result.output) == (2, True), f"{given}: {should}"

    def test_alias_is_hidden_from_help(self):
        given = "--help of a command with aliases"
        should = "show only the new spellings"

        help_text = CliRunner().invoke(self._command(), ["--help"]).output

        assert ("--client-id" in help_text, "--user" in help_text, "--human" in help_text) == (True, False, False), (
            f"{given}: {should}"
        )


@pytest.mark.parametrize(
    "args",
    [
        ["check-prereqs", "--format", "json"],
        ["retrieve-tests", str(SAMPLE)],
        ["contract", "lint", str(Path(__file__).parent / "odcs" / "fixtures" / "marvel.odcs.yaml"), str(SAMPLE), "--format", "json"],
        ["contract", "doctor", str(SAMPLE), "--format", "json"],
    ],
)
def test_json_stdout_is_only_json(args, monkeypatch):
    given = f"pql-test {args[0]} with JSON output"
    should = "print nothing but JSON on stdout (notes and warnings go to stderr)"
    import json

    monkeypatch.setenv("PQL_TEST_HERMETIC", "1")
    monkeypatch.setattr("pql_test.contract_run.xmla_unavailable", lambda: "no XMLA in this test")

    result = CliRunner().invoke(cli, args)

    json.loads(result.stdout)  # raises on anything but JSON
    assert result.exit_code in (0, 1), f"{given}: {should}\n{result.output}"
