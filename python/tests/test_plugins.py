# SPDX-License-Identifier: BUSL-1.1
"""Tests for pql_test.plugins: loading extra commands from the pql_test.commands entry points."""

from __future__ import annotations

from importlib.metadata import EntryPoint, entry_points

import click
import pytest
from click.testing import CliRunner
from pql_test.plugins import (
    ENTRY_POINT_GROUP,
    STRICT_ENV,
    load_plugins,
    select_entry_points,
)


@click.group(name="demo")
def demo() -> None:
    """A plugin command group used by these tests."""


@demo.command("hello")
def hello() -> None:
    click.echo("hi")


@click.command(name="run-tests")
def impostor() -> None:
    """A plugin command that collides with a built-in."""


def _ep(name: str, value: str) -> EntryPoint:
    return EntryPoint(name=name, value=value, group=ENTRY_POINT_GROUP)


def _host() -> click.Group:
    @click.group()
    def host() -> None:
        pass

    @host.command("run-tests")
    def builtin() -> None:
        click.echo("built-in")

    return host


class TestSelectEntryPoints:
    def test_python_39_dict_shape(self):
        given = "Python 3.9's entry_points(), a dict of group -> entry points"
        should = "return the entries for our group"
        eps = {ENTRY_POINT_GROUP: (_ep("demo", "x:y"),), "other": (_ep("o", "a:b"),)}

        assert [e.name for e in select_entry_points(eps, ENTRY_POINT_GROUP)] == ["demo"], f"{given}: {should}"

    def test_selectable_shape_from_this_interpreter(self):
        given = "this interpreter's entry_points() result"
        should = "be accepted without error"

        assert isinstance(select_entry_points(entry_points(), ENTRY_POINT_GROUP), list), f"{given}: {should}"


class TestLoadPlugins:
    def test_adds_plugin_commands(self):
        given = "an entry point naming a click group"
        should = "mount it on the host CLI"
        host = _host()

        loaded = load_plugins(host, [_ep("demo", "tests.test_plugins:demo")])
        result = CliRunner().invoke(host, ["demo", "hello"])

        assert (loaded, result.output) == (["demo"], "hi\n"), f"{given}: {should}"

    def test_broken_plugin_warns_and_keeps_built_ins(self, monkeypatch, capsys):
        given = "a plugin whose module cannot be imported"
        should = "print a one-line warning naming the plugin and keep built-in commands working"
        monkeypatch.delenv(STRICT_ENV, raising=False)
        host = _host()

        load_plugins(host, [_ep("broken", "no_such_module_xyz:group")])
        warning = capsys.readouterr().err
        result = CliRunner().invoke(host, ["run-tests"])

        assert ("'broken'" in warning, "no_such_module_xyz" in warning, result.output) == (True, True, "built-in\n"), (
            f"{given}: {should}"
        )

    def test_non_command_entry_point_is_rejected(self, monkeypatch, capsys):
        given = "an entry point that loads something other than a click command"
        should = "warn instead of mounting it"
        monkeypatch.delenv(STRICT_ENV, raising=False)
        host = _host()

        loaded = load_plugins(host, [_ep("notcmd", "json:dumps")])

        assert (loaded, "not a click command" in capsys.readouterr().err) == ([], True), f"{given}: {should}"

    def test_strict_mode_reraises_load_errors(self, monkeypatch):
        given = f"{STRICT_ENV}=1 and a broken plugin"
        should = "re-raise the load error so CI fails loudly"
        monkeypatch.setenv(STRICT_ENV, "1")

        with pytest.raises(ModuleNotFoundError) as exc:
            load_plugins(_host(), [_ep("broken", "no_such_module_xyz:group")])

        assert "no_such_module_xyz" in str(exc.value), f"{given}: {should}"

    def test_collision_keeps_the_built_in(self, capsys):
        given = "a plugin command named like a built-in"
        should = "keep the built-in and warn"
        host = _host()

        loaded = load_plugins(host, [_ep("impostor", "tests.test_plugins:impostor")])
        result = CliRunner().invoke(host, ["run-tests"])

        assert (loaded, result.output, "built in" in capsys.readouterr().err) == ([], "built-in\n", True), (
            f"{given}: {should}"
        )


class TestInstalledContractPlugin:
    def test_pql_test_mounts_the_contract_group_when_pql_odcs_is_installed(self):
        given = "pql-odcs installed alongside pql-test"
        should = "list the contract commands under `pql-test contract --help`"
        pytest.importorskip("pql_odcs")
        from pql_test.cli import cli

        result = CliRunner().invoke(cli, ["contract", "--help"])

        assert (result.exit_code, all(c in result.output for c in ("generate", "coverage", "lint", "trace"))) == (
            0,
            True,
        ), f"{given}: {should}\n{result.output}"
