# SPDX-License-Identifier: BUSL-1.1
"""
README-sync guard.

PyPI renders ``python/README.md`` (``readme = "README.md"`` in
``python/pyproject.toml``), while GitHub renders the repo-root ``README.md``.
The packaged copy exists only so setuptools can find it at build time; this
test fails the build when the two drift, so the PyPI project page always
matches the documentation on GitHub.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.mark.parametrize("name", ["README.md", "LICENSE.txt"])
def test_packaged_copy_matches_repo_root(name: str):
    given = f"python/{name}"
    should = f"be byte-for-byte identical to the repo-root {name} (copy it over)"

    assert (REPO_ROOT / "python" / name).read_bytes() == (REPO_ROOT / name).read_bytes(), (
        f"{given}: {should}"
    )
