# SPDX-License-Identifier: MIT
"""Package metadata guards for pql-odcs (license boundary, dependency allowlist)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.9 / 3.10
    tomllib = pytest.importorskip("tomli")

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PACKAGE_ROOT.parent.parent


def _project() -> dict:
    return tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]


class TestPyproject:
    def test_declares_mit_with_license_files(self):
        given = "the pql-odcs pyproject"
        should = "declare license MIT and ship LICENSE and NOTICE as license files"
        project = _project()

        assert (project["license"], project["license-files"]) == ("MIT", ["LICENSE", "NOTICE"]), (
            f"{given}: {should}"
        )

    def test_supports_python_39(self):
        given = "the pql-odcs pyproject"
        should = "keep requires-python at >=3.9 like pql-test"

        assert _project()["requires-python"] == ">=3.9", f"{given}: {should}"

    def test_runtime_dependencies_are_limited_to_the_allowlist(self):
        given = "the pql-odcs runtime dependencies"
        should = "be limited to PyYAML, jsonschema, and click"
        names = {re.split(r"[<>=!~\[; ]", dep, maxsplit=1)[0].lower() for dep in _project()["dependencies"]}

        assert names == {"pyyaml", "jsonschema", "click"}, f"{given}: {should}"

    def test_does_not_depend_on_pql_test(self):
        given = "every pql-odcs dependency list, including extras"
        should = "never name pql-test (the dependency is one-way)"
        project = _project()
        all_deps = list(project["dependencies"])
        for extra in project.get("optional-dependencies", {}).values():
            all_deps.extend(extra)

        assert not [d for d in all_deps if d.lower().startswith("pql-test")], f"{given}: {should}"


class TestWorkspace:
    def test_root_workspace_links_both_packages(self):
        given = "the repo-root pyproject"
        should = "declare a uv workspace with python/ and packages/pql-odcs/ as members"
        root = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

        assert root["tool"]["uv"]["workspace"]["members"] == ["python", "packages/pql-odcs"], (
            f"{given}: {should}"
        )

    def test_pql_test_resolves_pql_odcs_from_the_workspace(self):
        given = "pql-test's pyproject"
        should = "offer a contracts extra and resolve pql-odcs from the workspace under uv"
        pql_test = tomllib.loads((REPO_ROOT / "python" / "pyproject.toml").read_text(encoding="utf-8"))

        assert pql_test["project"]["optional-dependencies"]["contracts"] == ["pql-odcs>=0.1,<0.2"], (
            f"{given}: {should}"
        )
        assert pql_test["tool"]["uv"]["sources"]["pql-odcs"] == {"workspace": True}, f"{given}: {should}"
