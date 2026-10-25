#!/usr/bin/env python3
# SPDX-License-Identifier: BUSL-1.1
"""
License-boundary checks for the mixed-license repository (see LICENSES.md).

    python .github/scripts/check_license_boundary.py spdx
    python .github/scripts/check_license_boundary.py wheel dist/pql_odcs-*.whl

`spdx` makes sure every .py file under python/ carries the BUSL-1.1 SPDX header
and every .py file under packages/pql-odcs/ carries the MIT one. `wheel` makes
sure a built pql-odcs wheel holds only pql_odcs/ and its own LICENSE and NOTICE.
Both exit 1 and list each violation.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Path prefix (relative to the repo root) -> required SPDX identifier.
SPDX_RULES = {
    "packages/pql-odcs": "MIT",
    "python": "BUSL-1.1",
}
SKIP_DIRS = {".venv", "venv", "__pycache__", "build", "dist", ".pytest_cache", ".hypothesis"}
ALLOWED_LICENSE_FILES = {"LICENSE", "NOTICE"}


def _header_ok(path: Path, identifier: str) -> bool:
    expected = f"# SPDX-License-Identifier: {identifier}"
    with path.open(encoding="utf-8") as fh:
        head = [fh.readline().rstrip("\r\n") for _ in range(2)]
    if head[0].startswith("#!"):
        return head[1] == expected
    return head[0] == expected


def _python_files(root: Path):
    for path in sorted(root.rglob("*.py")):
        parts = path.relative_to(root).parts
        if any(p in SKIP_DIRS or p.endswith(".egg-info") for p in parts):
            continue
        yield path


def spdx_violations(repo_root: Path = REPO_ROOT) -> list[str]:
    """Return one message per .py file whose SPDX header is missing or wrong."""
    problems: list[str] = []
    for prefix, identifier in SPDX_RULES.items():
        base = repo_root / prefix
        if not base.is_dir():
            continue
        for path in _python_files(base):
            if not _header_ok(path, identifier):
                rel = path.relative_to(repo_root).as_posix()
                problems.append(f"{rel}: expected '# SPDX-License-Identifier: {identifier}'")
    return sorted(problems)


def _wheel_entry_allowed(name: str) -> bool:
    top, _, rest = name.partition("/")
    if top == "pql_odcs":
        return True
    if top.startswith("pql_odcs-") and top.endswith(".dist-info"):
        if rest.startswith("licenses/"):
            return rest[len("licenses/"):] in ALLOWED_LICENSE_FILES
        return True
    return False


def wheel_violations(wheel: Path) -> list[str]:
    """Return every entry in *wheel* outside pql_odcs/ and its own license files."""
    with zipfile.ZipFile(wheel) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
    return sorted(n for n in names if not _wheel_entry_allowed(n))


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in {"spdx", "wheel"} or (argv[0] == "wheel" and len(argv) < 2):
        print(__doc__, file=sys.stderr)
        return 2
    if argv[0] == "spdx":
        problems = spdx_violations()
    else:
        problems = [f"{w}: {entry}" for w in argv[1:] for entry in wheel_violations(Path(w))]
    for line in problems:
        print(line, file=sys.stderr)
    if problems:
        print(f"{len(problems)} license-boundary violation(s).", file=sys.stderr)
        return 1
    print("License boundary OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
