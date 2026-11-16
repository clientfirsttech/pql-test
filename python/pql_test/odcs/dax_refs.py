# SPDX-License-Identifier: AGPL-3.0-only
"""Which model names a piece of DAX references, read from its text alone.

`contract coverage` uses this for the DAX a contract wrote (``engine: pql-test`` rules) when it
does not ask the model (``--live``). It finds ``'Table'[Name]``, ``Table[Name]``, ``[Name]``,
``'Table'``, and bare ``Table`` words outside string literals and comments. Deciding what a
name means (a column, a measure, or nothing in the model) is the caller's job.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# A bare word: a table name, a variable, a keyword, or (followed by "(") a function, dots included.
_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")
_SPACE_RE = re.compile(r"\s*")


@dataclass(frozen=True)
class DaxRef:
    """One reference: ``table`` and ``name`` for ``'T'[N]``; only ``name`` for ``[N]``; only ``table`` for a table."""

    table: str | None = None
    name: str | None = None
    quoted: bool = False  # the table was written 'quoted', so it can only be a table name

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
    refs: list[DaxRef] = []
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
                break
            table, i = found
            column = _bracket_after(text, i)
            if column:
                refs.append(DaxRef(table, column[0], quoted=True))
                i = column[1]
            else:
                refs.append(DaxRef(table, quoted=True))
        elif ch == "[":
            found = _quoted(text, i, "]")
            if found is None:
                break
            refs.append(DaxRef(name=found[0]))
            i = found[1]
        elif _WORD_RE.match(text, i) and not (i and (text[i - 1].isalnum() or text[i - 1] in "_.")):
            word = _WORD_RE.match(text, i)
            i = word.end()
            column = _bracket_after(text, i)
            if column:
                refs.append(DaxRef(word.group(), column[0]))
                i = column[1]
            elif text[_SPACE_RE.match(text, i).end() : _SPACE_RE.match(text, i).end() + 1] != "(":
                refs.append(DaxRef(word.group()))
        else:
            i += 1
    return refs
