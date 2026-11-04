# SPDX-License-Identifier: AGPL-3.0-only
"""Every third-party GitHub Action is pinned to a full commit SHA.

A tag such as ``@v4`` can be moved to new code; a commit SHA cannot, so a compromised action
repository cannot change what a workflow runs without a visible edit here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

GITHUB = Path(__file__).resolve().parents[2] / ".github"
FILES = sorted([*(GITHUB / "workflows").glob("*.yml"), *GITHUB.glob("*.yml")])
USES = re.compile(r"^\s*(?:-\s*)?uses:\s*(\S+)", re.MULTILINE)
PINNED = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")


def test_workflow_files_were_found():
    assert len(FILES) >= 10


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_actions_are_pinned_to_commit_shas(path):
    unpinned = [
        ref for ref in USES.findall(path.read_text(encoding="utf-8")) if not ref.startswith("./") and not PINNED.match(ref)
    ]
    assert not unpinned, f"{path.name}: pin to a commit SHA: {unpinned}"
