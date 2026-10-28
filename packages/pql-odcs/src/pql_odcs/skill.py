# SPDX-License-Identifier: MIT
"""The pql-odcs AI-agent skill: read it, and install it into a project for a coding agent.

The skill ships inside the wheel (``pql_odcs/skills/pql-odcs/SKILL.md``). Installing copies
it to ``<project>/<harness dir>/SKILL.md``. A file is pql-odcs's own when its frontmatter
says ``name: pql-odcs``; only those are upgraded or removed without ``force``. Symlinks are
never written through or removed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from pql_odcs.udf import version_key

SKILL_NAME = "pql-odcs"
# Harness -> skill folder, relative to the project root.
HARNESSES = {
    "claude": Path(".claude/skills/pql-odcs"),
    "copilot": Path(".github/skills/pql-odcs"),
    "cursor": Path(".cursor/skills/pql-odcs"),
    "windsurf": Path(".windsurf/skills/pql-odcs"),
}
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---", re.DOTALL)


def skill_text() -> str:
    return files("pql_odcs").joinpath("skills", SKILL_NAME, "SKILL.md").read_text(encoding="utf-8")


def frontmatter(text: str) -> dict[str, str]:
    """Top-level ``key: value`` pairs of a SKILL.md frontmatter block (empty when there is none)."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}
    pairs = (line.split(":", 1) for line in match.group(1).splitlines() if ":" in line and not line.startswith(" "))
    return {key.strip(): value.strip() for key, value in pairs}


def _installed(path: Path) -> dict[str, str] | None:
    """The frontmatter of the file at *path*, ``{}`` when it is unreadable as UTF-8, ``None`` when absent."""
    if not path.is_file():
        return None
    try:
        return frontmatter(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, OSError):
        return {}


@dataclass(frozen=True)
class Action:
    harness: str
    path: Path
    status: str  # installed | updated | current | refused | removed | absent | foreign | error
    detail: str = ""

    def line(self, dry_run: bool = False) -> str:
        verb = {"installed": "would install", "updated": "would update", "removed": "would remove"}
        status = verb.get(self.status, self.status) if dry_run else self.status
        return f"{self.harness:<9} {status:<13} {self.path}" + (f"  ({self.detail})" if self.detail else "")


def _target(root: Path, harness: str) -> Path:
    return Path(root) / HARNESSES[harness] / "SKILL.md"


def install(harness: str, root: Path, *, force: bool = False, dry_run: bool = False) -> Action:
    """Install the skill for one harness under project *root*."""
    text = skill_text()
    version = frontmatter(text).get("version", "?")
    path = _target(root, harness)
    if path.is_symlink():
        return Action(harness, path, "refused", "a symlink; replace it by hand")
    status = "installed"
    existing = _installed(path)
    if existing is not None:
        status = "updated"
        if not force:
            if existing.get("name") != SKILL_NAME:
                return Action(harness, path, "refused", "not a pql-odcs skill; pass --force to overwrite")
            found = existing.get("version", "")
            if found == version:
                return Action(harness, path, "current", f"v{version}")
            if version_key(found) > version_key(version):
                return Action(harness, path, "refused", f"v{found} is newer than v{version}; pass --force to downgrade")
    if not dry_run:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
        except OSError as exc:
            return Action(harness, path, "error", str(exc))
    return Action(harness, path, status, f"v{version}")


def uninstall(harness: str, root: Path, *, dry_run: bool = False) -> Action:
    """Remove the skill for one harness, and its folder when that leaves it empty."""
    path = _target(root, harness)
    if path.is_symlink():
        return Action(harness, path, "refused", "a symlink; left in place")
    existing = _installed(path)
    if existing is None:
        return Action(harness, path, "absent")
    if existing.get("name") != SKILL_NAME:
        return Action(harness, path, "refused", "not a pql-odcs skill; left in place")
    if not dry_run:
        try:
            path.unlink()
            if not any(path.parent.iterdir()):
                path.parent.rmdir()
        except OSError as exc:
            return Action(harness, path, "error", str(exc))
    return Action(harness, path, "removed")


def status(harness: str, root: Path) -> Action:
    path = _target(root, harness)
    existing = _installed(path)
    if existing is None:
        return Action(harness, path, "absent")
    if existing.get("name") != SKILL_NAME:
        return Action(harness, path, "foreign", "a different skill is at this path")
    current = frontmatter(skill_text()).get("version")
    stale = "" if existing.get("version") == current else f", this pql-odcs ships v{current}"
    return Action(harness, path, "installed", f"v{existing.get('version', '?')}{stale}")
