# SPDX-License-Identifier: MIT
"""Translate the simple regexes that PQL.Assert 0.8 column checks can express."""

from __future__ import annotations

_META = frozenset("\\.^$*+?{}[]|()")
# PQL.Assert's matchCase value for a case-sensitive comparison, as a regex is.
MATCH_CASE = "Y"


def simple_pattern(pattern: object) -> tuple[str, str] | str:
    """``(ir_op, literal)`` for ``^literal``, ``literal$`` or a bare literal; otherwise a skip reason.

    A bare literal is a regex search, so it means "contains". ``^literal$`` is an exact match,
    which PQL.Assert has no function for, so it stays skipped like any other regex.
    """
    if not isinstance(pattern, str) or not pattern:
        return "the pattern is empty or not text"
    anchored_start = pattern.startswith("^")
    anchored_end = pattern.endswith("$") and not pattern.endswith("\\$")
    core = pattern[1 if anchored_start else 0 : len(pattern) - 1 if anchored_end else len(pattern)]
    if anchored_start and anchored_end:
        return "an exact-match pattern (^literal$) has no PQL.Assert column function"
    if not core:
        return "the pattern has no literal text"
    if any(ch in _META for ch in core):
        return "regular expressions beyond ^literal, literal$, and a bare literal are not translated to DAX"
    if anchored_start:
        return "col.starts_with", core
    if anchored_end:
        return "col.ends_with", core
    return "col.contains", core
