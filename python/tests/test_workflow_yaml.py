# SPDX-License-Identifier: AGPL-3.0-only
"""GitHub Actions workflows: each file parses, with no key given twice in one mapping.

GitHub rejects a workflow whose mapping repeats a key (for example two ``env:`` blocks on one
step) before any job starts, so the run fails with only "workflow file issue" and no log.
"""

from __future__ import annotations

from pathlib import Path

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
