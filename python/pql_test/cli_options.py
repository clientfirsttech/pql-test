# SPDX-License-Identifier: AGPL-3.0-only
"""Shared CLI options, so the same option means the same thing on every command.

Conventions (see CONTRIBUTING.md, "CLI Argument Conventions"):

- ``-v/--verbose`` and ``-q/--quiet`` on every command that prints a report. Quiet prints
  only the report's summary line on stdout; warnings and errors still go to stderr, and the
  exit code never changes. A result printed on stdout (JSON, a contract, DAX) is never
  suppressed.
- ``--format text|json`` is the one way to ask for machine-readable output.
- ``--output FILE`` / ``-o FILE`` writes the command's result to FILE.
- Old spellings stay as hidden aliases (``deprecated_alias``): left out of ``--help``, they
  warn once on stderr and behave exactly as before.
"""

from __future__ import annotations

import contextlib
import functools
import inspect
import io
import sys
from collections.abc import Callable
from typing import Any

import click

_MISSING = object()
_summary: list[str] = []
_result_streams: list[Any] = []  # the real stdout while a --format json command runs


def emit_result(text: str) -> None:
    """Print the command's machine-readable result on stdout, even while --format json sends other lines to stderr."""
    click.echo(text, file=_result_streams[-1] if _result_streams else None)


def record_summary(line: str) -> None:
    """Mark *line* as the report's summary: the one line ``--quiet`` prints (the last one recorded wins)."""
    _summary.append(click.unstyle(line).strip())


def verbosity_options(result_on_stdout: Callable[[dict], bool] | None = None) -> Callable:
    """Add ``-v/--verbose`` and ``-q/--quiet`` to a command.

    *result_on_stdout(kwargs)* says when stdout carries the command's result (JSON, a file's
    content) rather than a report; quiet then leaves stdout alone. JSON output always counts.
    A command that has no extra detail to show accepts ``--verbose`` and ignores it.
    """

    def decorator(f: Callable) -> Callable:
        takes_verbose = "verbose" in inspect.signature(f).parameters

        @functools.wraps(f)
        def wrapper(*args: Any, quiet: bool, verbose: bool, **kwargs: Any) -> Any:
            if quiet and verbose:
                raise click.UsageError("Use only one of --quiet and --verbose.")
            if takes_verbose:
                kwargs["verbose"] = verbose
            if kwargs.get("output_format") == "json":
                # stdout carries only the JSON (via emit_result); every other line goes to stderr.
                _result_streams.append(sys.stdout)
                try:
                    with contextlib.redirect_stdout(sys.stderr):
                        return f(*args, **kwargs)
                finally:
                    _result_streams.pop()
            if not quiet or (result_on_stdout and result_on_stdout(kwargs)):
                return f(*args, **kwargs)
            _summary.clear()
            captured = io.StringIO()
            try:
                with contextlib.redirect_stdout(captured):
                    return f(*args, **kwargs)
            finally:
                lines = [line.strip() for line in click.unstyle(captured.getvalue()).splitlines() if line.strip()]
                line = _summary[-1] if _summary else (lines[-1] if lines else "")
                if line:
                    click.echo(line)

        wrapper = click.option("--quiet", "-q", is_flag=True, help="Print only the summary line.")(wrapper)
        return click.option("--verbose", "-v", is_flag=True, help="Show more detail.")(wrapper)

    return decorator


def format_option(default: str = "text", help: str | None = None) -> Callable:
    """``--format text|json``, passed to the command as ``output_format``."""
    return click.option(
        "--format",
        "output_format",
        type=click.Choice(["text", "json"]),
        default=default,
        show_default=True,
        help=help or "Output format: a report (text) or machine-readable JSON.",
    )


def output_option(help: str) -> Callable:
    """``--output FILE`` / ``-o FILE``, passed to the command as ``output``."""
    return click.option("--output", "-o", "output", default=None, metavar="FILE", help=help)


def deprecated_alias(*names: str, to: str, use: str, value: Any = _MISSING, **option_kwargs: Any) -> Callable:
    """A hidden old spelling of the option whose parameter is *to* (shown as *use* in the warning).

    The alias is left out of ``--help``. When given, it warns on stderr and fills *to*, unless
    *to* was also given with a different value, which is a usage error. With *value*, the alias
    is a flag that sets *to* to that value (e.g. ``--human`` for ``--format text``).

    Place it above the option it aliases, so that option is already declared when it is applied.
    """
    dest = "deprecated_" + names[-1].lstrip("-").replace("-", "_")

    def decorator(f: Callable) -> Callable:
        default = _parameter_default(f, to)

        @functools.wraps(f)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            given = kwargs.pop(dest)
            if given not in (None, False):
                old = max(names, key=len)  # the long spelling, e.g. --user rather than -u
                click.echo(f"Warning: {old} is deprecated; use {use}.", err=True)
                new = value if value is not _MISSING else given
                current = kwargs.get(to)
                if current not in (None, False, default) and current != new:
                    raise click.UsageError(f"{old} and {use} disagree; pass only {use}.")
                kwargs[to] = new
            return f(*args, **kwargs)

        if value is not _MISSING:
            option_kwargs.setdefault("is_flag", True)
        return click.option(*names, dest, hidden=True, **option_kwargs)(wrapper)

    return decorator


def _parameter_default(f: Callable, name: str) -> Any:
    """The click default of *f*'s already-declared parameter *name*, if any (so an alias can tell it from a value)."""
    for param in getattr(f, "__click_params__", []):
        if param.name == name:
            return param.default
    return None
