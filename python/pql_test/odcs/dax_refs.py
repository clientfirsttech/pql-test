# SPDX-License-Identifier: AGPL-3.0-only
"""Which model names a piece of DAX references, read from its text alone.

`contract coverage` uses this for the DAX a contract wrote (``engine: pql-test`` rules) when it
does not ask the model (``--live``). It finds ``'Table'[Name]``, ``Table[Name]``, ``[Name]``,
``'Table'``, and bare ``Table`` words outside string literals and comments. Deciding what a
name means (a column, a measure, or nothing in the model) is the caller's job.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field

# A bare word: a table name, a variable, a keyword, or (followed by "(") a function, dots included.
_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")
_SPACE_RE = re.compile(r"\s*")
# DAX keywords, which an unquoted table name can never be: in `RETURN [Total]` the bracket is a bare name.
_KEYWORDS = frozenset(
    "VAR RETURN NOT IN AND OR TRUE FALSE DEFINE EVALUATE MEASURE COLUMN TABLE FUNCTION ORDER BY ASC DESC START AT".split()
)


@dataclass(frozen=True)
class DaxRef:
    """One reference: ``table`` and ``name`` for ``'T'[N]``; only ``name`` for ``[N]``; only ``table`` for a table."""

    table: str | None = None
    name: str | None = None
    quoted: bool = False  # the table was written 'quoted', so it can only be a table name
    span: tuple[int, int] = field(default=(0, 0), compare=False)  # where it sits in the text

    def __str__(self) -> str:
        table = "" if self.table is None else (f"'{self.table}'" if self.quoted else self.table)
        return table + ("" if self.name is None else f"[{self.name}]")


def _quoted(text: str, start: int, close: str) -> tuple[str, int] | None:
    """The unescaped contents of a quoted run starting at *start* (doubled *close* is a literal), and the index after it."""
    i, out = start + 1, []
    while i < len(text):
        if text[i] == close and text[i + 1 : i + 2] == close:
            out.append(close)
            i += 2
        elif text[i] == close:
            return "".join(out), i + 1
        else:
            out.append(text[i])
            i += 1
    return None


def _bracket_after(text: str, i: int) -> tuple[str, int] | None:
    """A ``[name]`` right after *i* (spaces allowed), and the index after it."""
    j = _SPACE_RE.match(text, i).end()
    return _quoted(text, j, "]") if text[j : j + 1] == "[" else None


def dax_references(text: str) -> list[DaxRef]:
    """Every table and bracketed name *text* references, in order, outside strings and comments."""
    return list(_scan(text))


def mask_references(text: str, measures: set[str]) -> str:
    """*text* with every reference to a measure named in *measures* (lower case), bare or table-qualified,
    replaced by ``BLANK()``. What is left references only what the text itself names directly."""
    if not measures:
        return text
    spans = [r.span for r in _scan(text) if r.name is not None and r.name.lower() in measures]
    for start, end in reversed(spans):
        text = text[:start] + "BLANK()" + text[end:]
    return text


def _scan(text: str) -> Iterator[DaxRef]:
    i = 0
    while i < len(text):
        ch, pair = text[i], text[i : i + 2]
        if pair in ("//", "--"):
            end = text.find("\n", i)
            i = len(text) if end < 0 else end
        elif pair == "/*":
            end = text.find("*/", i + 2)
            i = len(text) if end < 0 else end + 2
        elif ch == '"':
            found = _quoted(text, i, '"')
            i = len(text) if found is None else found[1]
        elif ch == "'":
            found = _quoted(text, i, "'")
            if found is None:
                return
            start, (table, i) = i, found
            column = _bracket_after(text, i)
            if column:
                yield DaxRef(table, column[0], quoted=True, span=(start, column[1]))
                i = column[1]
            else:
                yield DaxRef(table, quoted=True, span=(start, i))
        elif ch == "[":
            found = _quoted(text, i, "]")
            if found is None:
                return
            yield DaxRef(name=found[0], span=(i, found[1]))
            i = found[1]
        elif _WORD_RE.match(text, i) and not (i and (text[i - 1].isalnum() or text[i - 1] in "_.")):
            start, word = i, _WORD_RE.match(text, i)
            i = word.end()
            if word.group().upper() in _KEYWORDS:
                continue  # a bracket after it is read on its own, as a bare name
            column = _bracket_after(text, i)
            after = _SPACE_RE.match(text, i).end()
            if column:
                yield DaxRef(word.group(), column[0], span=(start, column[1]))
                i = column[1]
            elif text[after : after + 1] != "(":
                yield DaxRef(word.group(), span=(start, i))
        else:
            i += 1
