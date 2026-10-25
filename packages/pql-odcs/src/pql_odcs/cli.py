# SPDX-License-Identifier: MIT
"""The ``contract`` click group, mounted as ``pql-odcs`` and ``pql-test contract``."""

from __future__ import annotations

import click

from pql_odcs import __version__


@click.group(name="contract")
@click.version_option(version=__version__, prog_name="pql-odcs")
def contract() -> None:
    """Generate and trace PQL.Assert tests from ODCS data contracts."""


def main() -> None:
    contract()
