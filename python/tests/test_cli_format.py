# SPDX-License-Identifier: AGPL-3.0-only
"""
Unit tests for [python/pql_test/runner/cli_format.py](../pql_test/runner/cli_format.py).

Pure string-formatting helpers -- no Click runner, no CLI invocation needed.
"""

from __future__ import annotations

import click

from pql_test.runner.cli_format import (
    STATUS_COLORS,
    banner,
    pad,
    table_bottom,
    table_mid,
    table_row,
    table_top,
    truncate,
)


class TestBanner:
    def test_empty_title_fills_the_full_width_with_char(self):
        given = "an empty title"
        should = "the banner is one repeated separator char at the requested width"

        actual = banner(width=10)

        assert actual == "==========", f"{given}: {should}"

    def test_title_is_centered_between_repeated_chars(self):
        given = "a short title narrower than the requested width"
        should = "the title is wrapped in single spaces and centered with = on both sides"

        actual = banner("hi", width=10)

        assert actual == "=== hi ===", f"{given}: {should}"

    def test_custom_char_is_used_instead_of_equals(self):
        given = "a custom separator character"
        should = "that character fills the banner instead of the default ="

        actual = banner("hi", char="-", width=10)

        assert actual == "--- hi ---", f"{given}: {should}"

    def test_fg_wraps_the_line_in_ansi_color_codes(self):
        given = "an fg color argument"
        should = "the returned line is styled with click.style using that color"

        actual = banner("hi", width=10, fg="red")

        assert actual == click.style("=== hi ===", fg="red"), f"{given}: {should}"

    def test_no_fg_returns_plain_text(self):
        given = "no fg argument"
        should = "the returned line has no ANSI escape codes"

        actual = banner("hi", width=10)

        assert actual == "=== hi ===", f"{given}: {should}"


class TestPad:
    def test_left_align_is_the_default(self):
        given = "no align argument"
        should = "text is left-justified to the requested width"

        actual = pad("ab", 5)

        assert actual == "ab   ", f"{given}: {should}"

    def test_right_align_pads_on_the_left(self):
        given = "align='right'"
        should = "text is right-justified to the requested width"

        actual = pad("ab", 5, align="right")

        assert actual == "   ab", f"{given}: {should}"


class TestTruncate:
    def test_text_shorter_than_limit_is_unchanged(self):
        given = "text shorter than the truncation limit"
        should = "the text is returned verbatim"

        actual = truncate("abc", 10)

        assert actual == "abc", f"{given}: {should}"

    def test_text_longer_than_limit_is_ellipsized(self):
        given = "text longer than the truncation limit"
        should = "the text is cut and suffixed with a single ellipsis character, total length == n"

        actual = truncate("abcdefgh", 5)

        assert actual == "abcd…", f"{given}: {should}"
        assert len(actual) == 5, f"{given}: {should}"


class TestTableBorders:
    def test_top_border_uses_box_drawing_corners_and_tee_joints(self):
        given = "column widths for a 2-column table"
        should = "the top border starts/ends with rounded corners and joins columns with a top tee"

        actual = table_top([3, 5])

        assert actual == "┌" + "─" * 5 + "┬" + "─" * 7 + "┐", f"{given}: {should}"

    def test_mid_border_uses_cross_joints(self):
        given = "column widths for a 2-column table"
        should = "the mid border joins columns with a cross, not a top/bottom tee"

        actual = table_mid([3, 5])

        assert actual == "├" + "─" * 5 + "┼" + "─" * 7 + "┤", f"{given}: {should}"

    def test_bottom_border_uses_bottom_tee_and_corners(self):
        given = "column widths for a 2-column table"
        should = "the bottom border starts/ends with corners and joins columns with a bottom tee"

        actual = table_bottom([3, 5])

        assert actual == "└" + "─" * 5 + "┴" + "─" * 7 + "┘", f"{given}: {should}"

    def test_row_joins_pre_padded_cells_with_vertical_bars(self):
        given = "already-padded cell strings"
        should = "the row wraps each cell in a leading/trailing space and joins with a vertical bar"

        actual = table_row(["abc", "de "])

        assert actual == "│ abc │ de  │", f"{given}: {should}"


class TestStatusColors:
    def test_status_colors_covers_pass_fail_skip(self):
        given = "the shared status-color vocabulary"
        should = "PASS is green, FAIL is red, and SKIP is yellow -- the only status colors in the CLI"

        assert STATUS_COLORS == {"PASS": "green", "FAIL": "red", "SKIP": "yellow"}, f"{given}: {should}"


class TestCiLogEscaping:
    """Model data (test names, Expected/Actual, errors) must not forge CI logging commands."""

    def test_github_data_escapes_percent_and_line_breaks(self):
        given = "a message with %, CR, and LF"
        should = "encode them as %25, %0D, %0A so the text stays one workflow command"
        from pql_test.runner.cli_format import github_data

        actual = github_data("50%\r\n::add-mask::x")

        assert actual == "50%25%0D%0A::add-mask::x", f"{given}: {should}"

    def test_github_property_also_escapes_colon_and_comma(self):
        given = "a title with ':' and ','"
        should = "encode them as %3A and %2C so the title cannot end the property list"
        from pql_test.runner.cli_format import github_property

        actual = github_property("a:b,c%\n")

        assert actual == "a%3Ab%2Cc%25%0A", f"{given}: {should}"

    def test_azure_text_cannot_start_a_logging_command(self):
        given = "a message with a line break and an embedded ##vso[ command"
        should = "join the lines and break the ##vso[ / ##[ prefixes, in any case"
        from pql_test.runner.cli_format import azure_text

        actual = azure_text("x\r\n##vso[task.setvariable variable=A]1 ##VSO[y] ##[error]z")

        assert actual == "x ##vso [task.setvariable variable=A]1 ##VSO [y] ## [error]z", f"{given}: {should}"

    def test_azure_text_escapes_percent_for_vso_data(self):
        given = "a message with % passed as ##vso command data"
        should = "encode % as %AZP25 so the agent does not decode %0A into a line break"
        from pql_test.runner.cli_format import azure_text

        actual = azure_text("100%0A", vso_data=True)

        assert actual == "100%AZP250A", f"{given}: {should}"
