# SPDX-License-Identifier: AGPL-3.0-only
"""
Version-alignment guard.

A release ships one version across every manifest: ``python/pyproject.toml``
(the source of truth), ``plugin.json`` (the Copilot CLI plugin manifest),
and the ``version:`` frontmatter of every SKILL.md in both ``skills/`` and
``python/pql_test/skills/``. The bump procedure lives in
aidd-custom/skills/pql-test-version-bump/SKILL.md; this test fails the build
when any one of those is missed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PYPROJECT = REPO_ROOT / "python" / "pyproject.toml"
PLUGIN_JSON = REPO_ROOT / "plugin.json"
SKILL_FILES = sorted(
    list((REPO_ROOT / "skills").glob("*/SKILL.md"))
    + list((REPO_ROOT / "python" / "pql_test" / "skills").glob("*/SKILL.md"))
)


def _pyproject_version() -> str:
    text = PYPROJECT.read_text(encoding="utf-8")
    # Scope the search to the [project] table so a `version = "..."` key in
    # some other table (e.g. a future [tool.x]) can't be picked up instead.
    table = re.search(r"^\[project\]\n(.*?)(?=^\[|\Z)", text, re.MULTILINE | re.DOTALL)
    assert table, f"No [project] table found in {PYPROJECT}"
    match = re.search(r'^version\s*=\s*"([^"]+)"', table.group(1), re.MULTILINE)
    assert match, f"No version found in the [project] table of {PYPROJECT}"
    return match.group(1)


def test_plugin_json_version_matches_pyproject():
    given = "plugin.json and python/pyproject.toml"
    should = "carry the same version, so the Copilot plugin and the PyPI package release together"
    plugin_version = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))["version"]

    assert plugin_version == _pyproject_version(), f"{given}: {should}"


def test_skill_files_found():
    assert SKILL_FILES, "No SKILL.md files found under skills/ or python/pql_test/skills/"


@pytest.mark.parametrize("skill_path", SKILL_FILES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_skill_version_matches_pyproject(skill_path: Path):
    given = f"{skill_path.relative_to(REPO_ROOT)}"
    should = "declare the same version: as python/pyproject.toml"
    match = re.search(r"^version:\s*(\S+)", skill_path.read_text(encoding="utf-8"), re.MULTILINE)

    assert match, f"{given}: missing version: frontmatter"
    assert match.group(1) == _pyproject_version(), f"{given}: {should}"


def test_package_dunder_version_matches_pyproject():
    given = "pql_test.__version__ (public, in __all__)"
    should = "equal the pyproject version instead of a hard-coded string"
    import pql_test

    assert pql_test.__version__ == _pyproject_version(), f"{given}: {should}"
