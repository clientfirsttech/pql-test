# SPDX-License-Identifier: AGPL-3.0-only
"""GitHub Actions workflows: each file parses, with no key given twice in one mapping.

GitHub rejects a workflow whose mapping repeats a key (for example two ``env:`` blocks on one
step) before any job starts, so the run fails with only "workflow file issue" and no log.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))


class _NoDuplicateKeys(yaml.SafeLoader):
    """SafeLoader that records repeated mapping keys instead of keeping the last one."""

    duplicates: list[str]


def _mapping(loader: _NoDuplicateKeys, node: yaml.MappingNode, deep: bool = False) -> dict:
    seen: set[object] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            loader.duplicates.append(f"{key!r} at line {key_node.start_mark.line + 1}")
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


_NoDuplicateKeys.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def _duplicate_keys(path: Path) -> list[str]:
    loader = _NoDuplicateKeys(path.read_text(encoding="utf-8"))
    loader.duplicates = []
    try:
        loader.get_single_data()  # nosec B506 - SafeLoader subclass
    finally:
        loader.dispose()
    return loader.duplicates


def test_workflows_have_no_duplicate_keys():
    given = "every workflow in .github/workflows"
    should = "parse with no key repeated in a mapping (GitHub rejects the file otherwise)"
    assert WORKFLOWS, "no workflow files found"

    problems = [f"{path.name}: {dup}" for path in WORKFLOWS for dup in _duplicate_keys(path)]

    assert not problems, f"Given {given}, should {should}: {problems}"


def test_duplicate_key_check_catches_a_repeated_env():
    given = "a step with two env: blocks"
    should = "be reported as a duplicate key"
    text = "steps:\n  - run: echo\n    env:\n      A: 1\n    env:\n      B: 2\n"
    loader = _NoDuplicateKeys(text)
    loader.duplicates = []
    loader.get_single_data()  # nosec B506 - SafeLoader subclass
    loader.dispose()

    assert loader.duplicates == ["'env' at line 5"], f"Given {given}, should {should}"


def test_security_checks_lockfile_before_exporting_frozen_dependencies():
    given = "the security workflow exports frozen dependencies"
    should = "first reject a stale lockfile with a required freshness check"
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "security.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["security"]["steps"]
    lock_checks = [
        index
        for index, step in enumerate(steps)
        if step.get("run", "").strip() == "uv lock --check"
    ]

    assert len(lock_checks) == 1, f"Given {given}, should {should}"
    lock_index = lock_checks[0]
    lock_step = steps[lock_index]
    assert not lock_step.get("continue-on-error", False), should
    assert "if" not in lock_step, should
    export_indices = [
        index
        for index, step in enumerate(steps)
        if "uv export --frozen" in step.get("run", "")
    ]
    assert export_indices, "Expected the locked dependency audit export"
    assert all(lock_index < index for index in export_indices), should


@pytest.mark.parametrize(
    ("event_name", "target", "ref", "expected_code"),
    [
        ("workflow_dispatch", "pypi", "refs/heads/main", 1),
        ("workflow_dispatch", "pypi", "refs/heads/dev", 1),
        ("workflow_dispatch", "pypi", "refs/tags/0.2.1", 1),
        ("workflow_dispatch", "pypi", "refs/tags/v0.2.1", 0),
        ("workflow_dispatch", "testpypi", "refs/heads/main", 0),
        ("workflow_dispatch", "testpypi", "refs/tags/v0.2.1", 0),
        ("push", "", "refs/tags/v0.2.1", 0),
    ],
)
def test_release_validates_publish_target_before_building(
    event_name: str, target: str, ref: str, expected_code: int
):
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["build"]["steps"]
    validations = [
        (index, step)
        for index, step in enumerate(steps)
        if step.get("name") == "Validate publish target and ref"
    ]
    assert len(validations) == 1, "Release must validate the requested publish target"
    validation_index, validation = validations[0]
    assert validation["shell"] == "python"
    assert validation["env"]["PUBLISH_TARGET"] == "${{ inputs.target }}"
    assert "if" not in validation
    assert not validation.get("continue-on-error", False)
    build_indices = [
        index
        for index, step in enumerate(steps)
        if step.get("name")
        in {"Install build tooling", "Build sdist + wheel", "Upload distribution artifacts"}
    ]
    assert build_indices and all(validation_index < index for index in build_indices)

    result = subprocess.run(
        [sys.executable, "-c", validation["run"]],
        env={
            **os.environ,
            "GITHUB_EVENT_NAME": event_name,
            "PUBLISH_TARGET": target,
            "GITHUB_REF": ref,
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == expected_code, result.stdout + result.stderr
    if expected_code:
        assert "::error::" in result.stdout
        assert "release tag" in result.stdout
        assert "python/pyproject.toml" in result.stdout
