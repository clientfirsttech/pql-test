# SPDX-License-Identifier: AGPL-3.0-only
"""
Shared CLI presentation primitives.

Pure string-formatting helpers with no business logic and no command-specific
knowledge -- session banners, bordered tables, and the PASS/FAIL/SKIP color
vocabulary used across every `pql-test` command that prints a report to a
terminal. Extracted so `run-tests` and `code-coverage` (and any future
command) render through one shared style instead of each reinventing its own
presentation, per tasks/archive/2026-09-22-consistent-cli-output.md.
"""

from __future__ import annotations

import click

__all__ = [
    "DEFAULT_WIDTH",
    "STATUS_COLORS",
    "banner",
    "pad",
    "table_bottom",
    "table_mid",
    "table_row",
    "table_top",
    "truncate",
]

DEFAULT_WIDTH = 72

# The only status-color vocabulary in the CLI: PASS/full = green,
# FAIL/none = red, SKIP/partial = yellow. Any command coloring a
# status cell should draw from this map rather than inventing new
# color meanings.
STATUS_COLORS = {"PASS": "green", "FAIL": "red", "SKIP": "yellow"}


def banner(title: str = "", char: str = "=", fg: str | None = None, width: int = DEFAULT_WIDTH) -> str:
    """Render a pytest-style ``===== title =====`` banner line, optionally colored."""
    if not title:
        line = char * width
    else:
        inner = f" {title} "
        left = max(0, (width - len(inner)) // 2)
        right = max(0, width - left - len(inner))
        line = char * left + inner + char * right
    return click.style(line, fg=fg) if fg else line


def pad(text: str, width: int, align: str = "left") -> str:
    """Left- or right-pad *text* to *width* (visible-width padding, applied before coloring)."""
    return text.rjust(width) if align == "right" else text.ljust(width)


def truncate(text: str, n: int) -> str:
    """Truncate *text* to *n* characters, appending an ellipsis when it doesn't fit."""
    return text if len(text) <= n else text[: n - 1] + "…"


def table_top(widths: list[int]) -> str:
    return _table_border(widths, "┌", "┬", "┐")


def table_mid(widths: list[int]) -> str:
    return _table_border(widths, "├", "┼", "┤")


def table_bottom(widths: list[int]) -> str:
    return _table_border(widths, "└", "┴", "┘")


def table_row(cells: list[str]) -> str:
    """Join already-padded (and optionally colored) cell strings into one bordered row.

    Cells must be padded to their column width *before* calling this, so ANSI
    color codes applied afterward stay outside the visible-width math.
    """
    return "│ " + " │ ".join(cells) + " │"


def _table_border(widths: list[int], left: str, mid: str, right: str) -> str:
    parts = ["─" * (w + 2) for w in widths]
    return left + mid.join(parts) + right
