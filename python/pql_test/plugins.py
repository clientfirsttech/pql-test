# SPDX-License-Identifier: BUSL-1.1
"""
Load extra CLI commands from the ``pql_test.commands`` entry point group.

Any installed package can add a command to ``pql-test`` without pql-test naming
it. pql-odcs (``pip install pql-test[contracts]``) registers its ``contract``
group this way::

    [project.entry-points."pql_test.commands"]
    contract = "pql_odcs.cli:contract"

A broken plugin must not break pql-test, so load errors become a one-line stderr
warning. Set ``PQL_TEST_STRICT_PLUGINS=1`` (e.g. in CI) to re-raise them instead.
A plugin can never replace a built-in command.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from importlib.metadata import EntryPoint, entry_points
from typing import Any

import click

ENTRY_POINT_GROUP = "pql_test.commands"
STRICT_ENV = "PQL_TEST_STRICT_PLUGINS"


def select_entry_points(eps: Any, group: str) -> list[EntryPoint]:
    """Return *group*'s entry points from any ``importlib.metadata.entry_points()`` shape.

    Python 3.10+ results have ``select()``; Python 3.9 returns a plain dict of
    group name -> tuple of entry points.
    """
    if hasattr(eps, "select"):
        return list(eps.select(group=group))
    if isinstance(eps, Mapping):
        return list(eps.get(group, ()))
    return [ep for ep in eps if getattr(ep, "group", None) == group]


def load_plugins(group: click.Group, eps: Iterable[EntryPoint] | None = None) -> list[str]:
    """Mount every plugin command on *group*; return the names that were added."""
    if eps is None:
        eps = select_entry_points(entry_points(), ENTRY_POINT_GROUP)
    loaded: list[str] = []
    for ep in eps:
        try:
            command = ep.load()
            if not isinstance(command, click.Command):
                raise TypeError(f"{ep.value} is not a click command")
        except Exception as exc:  # a broken plugin must not break pql-test
            if os.environ.get(STRICT_ENV) == "1":
                raise
            click.echo(f"warning: pql-test plugin {ep.name!r} failed to load: {exc}", err=True)
            continue
        name = command.name or ep.name
        if name in group.commands:
            click.echo(
                f"warning: pql-test plugin {ep.name!r} provides command {name!r}, which is built in; "
                "keeping the built-in.",
                err=True,
            )
            continue
        group.add_command(command, name)
        loaded.append(name)
    return loaded
