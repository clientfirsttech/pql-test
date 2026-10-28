# SPDX-License-Identifier: MIT
"""``doctor``: is this environment, and this PBIP model, ready for pql-odcs?

Offline only. The model's PQL.Assert version and functions are read from its TMDL, and
the recommended ``--pql-assert`` value is the newest catalog whose every function the
model defines. pql-test adds live checks (the deployed library) to ``pql-test contract doctor``.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version
from importlib.resources import files
from pathlib import Path

from pql_odcs import __version__
from pql_odcs.catalog import PQL_ASSERT_CATALOGS, load_catalog
from pql_odcs.pbip import ModelPathError, require_semantic_model_dir
from pql_odcs.udf import UdfFunction, library_versions, model_functions, version_key

OK, WARN, FAIL = "ok", "warn", "fail"
_DEPENDENCIES = ("PyYAML", "jsonschema", "click")


@dataclass(frozen=True)
class Check:
    name: str
    status: str  # ok | warn | fail
    detail: str


@dataclass
class DoctorReport:
    checks: list[Check] = field(default_factory=list)
    recommended: str | None = None  # the --pql-assert value for the model, when one was checked

    @property
    def ok(self) -> bool:
        return all(c.status != FAIL for c in self.checks)

    def to_json(self) -> dict:
        return {
            "ok": self.ok,
            "recommendedPqlAssert": self.recommended,
            "checks": [{"name": c.name, "status": c.status, "detail": c.detail} for c in self.checks],
        }


def _installed(package: str) -> str | None:
    try:
        return version(package)
    except PackageNotFoundError:
        return None


def environment_checks() -> list[Check]:
    python = ".".join(str(p) for p in sys.version_info[:3])
    checks = [
        Check("Python", OK if sys.version_info >= (3, 9) else FAIL, f"{python} (needs 3.9 or later)"),
        Check("pql-odcs", OK, __version__),
    ]
    for dep in _DEPENDENCIES:
        found = _installed(dep)
        checks.append(Check(dep, OK if found else FAIL, found or f"not installed: pip install {dep}"))
    schemas = sorted(
        p.name[len("odcs-json-schema-v") : -len(".json")]
        for p in files("pql_odcs.schemas").iterdir()
        if p.name.startswith("odcs-json-schema-v")
    )
    checks.append(Check("ODCS schemas", OK if schemas else FAIL, ", ".join(schemas) or "none bundled"))
    checks.append(Check("PQL.Assert catalogs", OK, ", ".join(sorted(PQL_ASSERT_CATALOGS, key=version_key))))
    pql_test = _installed("pql-test")
    checks.append(
        Check(
            "pql-test",
            OK,
            f"{pql_test} (`pql-test contract run` available)"
            if pql_test
            else "not installed; needed only to run suites: pip install pql-test[contracts]",
        )
    )
    return checks


def recommend_catalog(functions: list[UdfFunction]) -> tuple[str | None, dict[str, list[str]]]:
    """The newest ``--pql-assert`` catalog the model fully supports, and each catalog's missing functions."""
    names = {fn.name for fn in functions}
    missing = {
        choice: sorted({spec.fn for spec in load_catalog(catalog).ops.values()} - names)
        for choice, catalog in PQL_ASSERT_CATALOGS.items()
    }
    for choice in sorted(missing, key=version_key, reverse=True):
        if not missing[choice]:
            return choice, missing
    return None, missing


def _short(names: list[str], limit: int = 3) -> str:
    shown = ", ".join(n.removeprefix("PQL.Assert.") for n in names[:limit])
    return shown + (f", and {len(names) - limit} more" if len(names) > limit else "")


def model_checks(model_path: str | Path) -> tuple[list[Check], str | None]:
    """Checks for one PBIP model, and the ``--pql-assert`` value it supports."""
    try:
        model = require_semantic_model_dir(model_path)
    except ModelPathError as exc:
        return [Check("PBIP model", FAIL, str(exc))], None
    checks = [Check("PBIP model", OK, str(model))]
    queries = model / "DAXQueries"
    suites = sorted(queries.glob("*.Tests.dax")) if queries.is_dir() else []
    checks.append(
        Check("DAXQueries/", OK, f"{len(suites)} suite file(s)" if queries.is_dir() else "absent; generate creates it")
    )

    functions = model_functions(model)
    versions = library_versions(functions)
    if not versions:
        checks.append(
            Check(
                "PQL.Assert library",
                FAIL,
                "no PQL.Assert functions in definition/functions.tmdl; install PQL.Assert from DAX Lib "
                "(https://daxlib.org) into the model",
            )
        )
        return checks, None
    found = ", ".join(f"{v} ({n} functions)" for v, n in sorted(versions.items(), key=lambda kv: version_key(kv[0])))
    if len(versions) > 1:
        checks.append(Check("PQL.Assert library", WARN, f"mixed versions: {found}; reinstall one release"))
    else:
        checks.append(Check("PQL.Assert library", OK, found))

    choice, missing = recommend_catalog(functions)
    if choice is None:
        checks.append(
            Check("--pql-assert", FAIL, f"the model lacks functions every catalog calls: {_short(missing['0.7'])}")
        )
        return checks, None
    newer = [c for c in sorted(missing, key=version_key) if version_key(c) > version_key(choice)]
    detail = choice
    if newer:
        catalog = load_catalog(PQL_ASSERT_CATALOGS[newer[0]])
        detail += (
            f" ({newer[0]} needs {catalog.library} {catalog.min_version} or later; the model lacks "
            f"{len(missing[newer[0]])} of its functions, e.g. {_short(missing[newer[0]], 2)})"
        )
    checks.append(Check("--pql-assert", OK, detail))
    return checks, choice


def run_doctor(model_path: str | Path | None = None) -> DoctorReport:
    report = DoctorReport(environment_checks())
    if model_path is not None:
        checks, report.recommended = model_checks(model_path)
        report.checks.extend(checks)
    return report


_LABELS = {OK: "ok", WARN: "warn", FAIL: "FAIL"}


def format_text(report: DoctorReport) -> str:
    lines = [f"  {_LABELS[c.status]:<5} {c.name}: {c.detail}" for c in report.checks]
    failed = sum(c.status == FAIL for c in report.checks)
    lines.append("")
    lines.append(f"{failed} check(s) failed." if failed else "All checks passed.")
    if report.recommended:
        lines.append(f"Use --pql-assert {report.recommended} with generate, coverage, and trace for this model.")
    return "\n".join(lines) + "\n"
