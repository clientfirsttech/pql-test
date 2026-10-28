# SPDX-License-Identifier: MIT
"""DAX user-defined functions in TMDL: read them, and the PQL.Assert version they carry.

Reads both a PBIP model's ``definition/functions.tmdl`` and a DAX Lib package's
``createOrReplace`` scripts. DAX Lib marks each installed function with the
``DAXLIB_PackageId`` and ``DAXLIB_PackageVersion`` annotations, which is how a model's
PQL.Assert version is known without connecting to it.
"""

from __future__ import annotations

import re
import textwrap
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from pql_odcs.pbip import _tmdl_name

PQL_ASSERT = "PQL.Assert"
_FUNCTION_RE = re.compile(r"^(\s*)function\s+('(?:[^']|'')+'|\S+)\s*=\s*(.*)$")
# Function properties that end the expression. Matched by keyword, not indent: hand-edited
# TMDL (PQL.Assert 0.8.0 included) sometimes indents an annotation with mixed tabs and spaces.
_PROPERTY_RE = re.compile(r"^((annotation|extendedProperty|changedProperty)\s|(lineageTag|sourceLineageTag|isHidden):)")
_ANNOTATION_RE = re.compile(r"^annotation\s+(\S+)\s*=\s*(.*)$")
_PLAIN_NAME_RE = re.compile(r"^[A-Za-z_][\w.]*$")


@dataclass(frozen=True)
class Parameter:
    name: str
    type: str
    optional: bool


@dataclass(frozen=True)
class UdfFunction:
    name: str
    expression: str  # "(params) => body", dedented
    annotations: dict = field(default_factory=dict)

    @property
    def package(self) -> str | None:
        return self.annotations.get("DAXLIB_PackageId")

    @property
    def version(self) -> str | None:
        return self.annotations.get("DAXLIB_PackageVersion")

    @property
    def parameters(self) -> tuple[Parameter, ...]:
        params = _strip_comments(_parameter_list(self.expression))
        return tuple(_parameter(p) for p in _split_top_level(params))

    def define(self) -> str:
        """This function as one ``FUNCTION`` entry of a DAX query's ``DEFINE`` block."""
        name = self.name if _PLAIN_NAME_RE.match(self.name) else "'" + self.name.replace("'", "''") + "'"
        return f"\tFUNCTION {name} = " + self.expression.replace("\n", "\n\t")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def parse_functions(text: str) -> list[UdfFunction]:
    """Every ``function`` declared in a TMDL document, in file order."""
    lines = text.splitlines()
    functions = []
    i = 0
    while i < len(lines):
        match = _FUNCTION_RE.match(lines[i])
        i += 1
        if not match:
            continue
        indent, rest = len(match.group(1)), match.group(3).strip()
        body: list[str] = []
        if rest.startswith("```"):
            while i < len(lines) and lines[i].strip() != "```":
                body.append(lines[i])
                i += 1
            i += 1
        else:
            if rest:
                body.append(rest)
            while i < len(lines):
                line = lines[i]
                if line.strip() and (_indent(line) <= indent or _PROPERTY_RE.match(line.strip())):
                    break
                body.append(line)
                i += 1
        annotations = {}
        while i < len(lines) and (not lines[i].strip() or _indent(lines[i]) > indent):
            found = _ANNOTATION_RE.match(lines[i].strip())
            if found:
                annotations[found.group(1)] = found.group(2).strip()
            i += 1
        expression = textwrap.dedent("\n".join(body)).strip("\n")
        functions.append(UdfFunction(_tmdl_name(match.group(2)), expression, annotations))
    return functions


def _parameter_list(expression: str) -> str:
    """The text between the expression's leading ``(`` and its matching ``)``."""
    if not expression.startswith("("):
        return ""
    depth, in_string = 0, False
    for pos, ch in enumerate(expression):
        if ch == '"':
            in_string = not in_string
        elif not in_string and ch == "(":
            depth += 1
        elif not in_string and ch == ")":
            depth -= 1
            if depth == 0:
                return expression[1:pos]
    return ""


def _strip_comments(text: str) -> str:
    """*text* without DAX ``//``, ``--``, and ``/* */`` comments (string literals are kept)."""
    out, pos, in_string = [], 0, False
    while pos < len(text):
        ch = text[pos]
        if ch == '"':
            in_string = not in_string
        elif not in_string and text.startswith(("//", "--"), pos):
            end = text.find("\n", pos)
            pos = len(text) if end == -1 else end
            continue
        elif not in_string and text.startswith("/*", pos):
            end = text.find("*/", pos + 2)
            pos = len(text) if end == -1 else end + 2
            continue
        out.append(ch)
        pos += 1
    return "".join(out)


def _split_top_level(text: str, sep: str = ",") -> list[str]:
    parts, depth, in_string, start = [], 0, False, 0
    for pos, ch in enumerate(text):
        if ch == '"':
            in_string = not in_string
        elif not in_string and ch in "([{":
            depth += 1
        elif not in_string and ch in ")]}":
            depth -= 1
        elif not in_string and depth == 0 and ch == sep:
            parts.append(text[start:pos])
            start = pos + 1
    parts.append(text[start:])
    return [p.strip() for p in parts if p.strip()]


def _parameter(text: str) -> Parameter:
    declaration, *default = _split_top_level(text, "=")
    name, _, kind = declaration.partition(":")
    return Parameter(name.strip(), kind.strip(), bool(default))


def model_functions(semantic_model_dir: str | Path) -> list[UdfFunction]:
    """The functions in a ``*.SemanticModel`` folder's ``definition/functions.tmdl`` (none if absent)."""
    path = Path(semantic_model_dir) / "definition" / "functions.tmdl"
    return parse_functions(path.read_text(encoding="utf-8-sig")) if path.is_file() else []


def library_versions(functions: Iterable[UdfFunction], package: str = PQL_ASSERT) -> dict[str, int]:
    """``version -> number of functions`` for one DAX Lib package (``"?"`` when unannotated)."""
    return dict(Counter(fn.version or "?" for fn in functions if fn.package == package))


def version_key(version: str) -> tuple[int, ...]:
    """``"0.10.1"`` -> ``(0, 10, 1)`` for numeric ordering; stops at the first non-number part."""
    key = []
    for part in version.split("."):
        if not part.isdigit():
            break
        key.append(int(part))
    return tuple(key)
