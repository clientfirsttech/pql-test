# SPDX-License-Identifier: AGPL-3.0-only
"""
SPDX header guard.

Every project source file (Python and PowerShell) carries
``# SPDX-License-Identifier: AGPL-3.0-only`` on its first line, or on the
second line after a shebang. See LICENSES.md and CONTRIBUTING.md. Third-party
files (the vendored AIDD framework under ``ai/``) keep their own license and
are not scanned.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HEADER = "# SPDX-License-Identifier: AGPL-3.0-only"
SOURCE_DIRS = ["python/pql_test", "python/tests", "scripts", ".github/scripts", "tests"]
PATTERNS = ["*.py", "*.ps1"]

SOURCE_FILES = sorted(
    {path for folder in SOURCE_DIRS for pattern in PATTERNS for path in (REPO_ROOT / folder).rglob(pattern)}
)


def test_source_files_found():
    assert SOURCE_FILES, f"No source files found under {SOURCE_DIRS}"


@pytest.mark.parametrize("path", SOURCE_FILES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_source_file_starts_with_spdx_header(path: Path):
    given = str(path.relative_to(REPO_ROOT))
    should = f"start with '{HEADER}' (after the shebang, when there is one)"
    lines = path.read_text(encoding="utf-8-sig").splitlines()[:2]
    if lines and lines[0].startswith("#!"):
        lines = lines[1:]

    assert lines and lines[0].strip() == HEADER, f"{given}: {should}"
