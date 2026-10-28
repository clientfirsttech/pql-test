# SPDX-License-Identifier: BUSL-1.1
"""
Query-scoped PQL.Assert 0.8.0 for live tests against a model that has an older library.

The released 0.8.0 package is vendored (MIT) under
packages/pql-odcs/tests/fixtures/pql-assert-0.8.0/. A suite that calls 0.8-only
functions can run on a model with an older PQL.Assert when those functions are defined in the query's own
DEFINE block, the same way docs/pql-assert-gap-plan.md's live checks were run. Only
functions the model lacks are defined: whether a query may redefine a model function is
not known, so that is never relied on.
"""

from __future__ import annotations

import re
from pathlib import Path

from pql_odcs.udf import UdfFunction, parse_functions

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LIBRARY_DIR = REPO_ROOT / "packages" / "pql-odcs" / "tests" / "fixtures" / "pql-assert-0.8.0" / "lib"
_CALL_RE = re.compile(r"\b(PQL\.Assert\.[\w.]+)\s*\(")


def load_library(lib_dir: Path = LIBRARY_DIR) -> dict[str, UdfFunction]:
    """Every function in the vendored PQL.Assert 0.8.0 package, by name."""
    functions = {}
    for tmdl in sorted(lib_dir.glob("*.tmdl")):
        functions.update((fn.name, fn) for fn in parse_functions(tmdl.read_text(encoding="utf-8-sig")))
    return functions


def called_functions(dax: str) -> set[str]:
    return set(_CALL_RE.findall(dax))


def missing_definitions(dax: str, model_names: set[str], library: dict[str, UdfFunction]) -> list[UdfFunction]:
    """Library functions *dax* needs (directly or through other library functions) that the model lacks.

    Dependencies come first, so each definition only refers to functions defined above it
    or in the model.
    """
    ordered: list[UdfFunction] = []
    seen: set[str] = set()

    def visit(name: str) -> None:
        if name in seen or name in model_names or name not in library:
            return
        seen.add(name)
        for dependency in sorted(called_functions(library[name].expression) - {name}):
            visit(dependency)
        ordered.append(library[name])

    for name in sorted(called_functions(dax)):
        visit(name)
    return ordered


def with_definitions(dax: str, functions: list[UdfFunction]) -> str:
    """*dax* with *functions* added at the top of its DEFINE block (one is created if absent)."""
    if not functions:
        return dax
    block = "\n".join(fn.define() for fn in functions)
    lines = dax.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.strip().upper() == "DEFINE":
            return "".join(lines[: i + 1]) + block + "\n" + "".join(lines[i + 1 :])
    evaluate = re.search(r"^\s*EVALUATE\b", dax, re.MULTILINE | re.IGNORECASE)
    at = evaluate.start() if evaluate else 0
    return dax[:at] + "DEFINE\n" + block + "\n\n" + dax[at:]


def model_function_names(conn, execute) -> set[str]:
    """Names of the user-defined functions in the connected model.

    *execute* is pql-test's ``_execute_dax_query``. ``INFO.FUNCTIONS()`` is tried first, then
    the ``TMSCHEMA_FUNCTIONS`` DMV.

    Raises:
        RuntimeError: neither query works on this model.
    """
    errors = []
    for query in ("EVALUATE SELECTCOLUMNS(INFO.FUNCTIONS(), \"Name\", [Name])", "SELECT [Name] FROM $SYSTEM.TMSCHEMA_FUNCTIONS"):
        try:
            return {str(next(iter(row.values()))) for row in execute(conn, query)}
        except Exception as exc:  # noqa: BLE001 - try the next way of listing functions
            errors.append(f"{query}: {exc}")
    raise RuntimeError("Cannot list the model's functions:\n" + "\n".join(errors))


def field(row: dict, name: str):
    """A column of an ADOMD result row by its bare name (``[Passed]`` and ``Passed`` both match)."""
    for key, value in row.items():
        if key.strip("[]").split("[")[-1].strip("]") == name:
            return value
    raise KeyError(f"{name} not in {sorted(row)}")
