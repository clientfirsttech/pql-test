# SPDX-License-Identifier: MIT
"""The pql-odcs AI-agent skill and the standalone `pql-odcs skill` command."""

from __future__ import annotations

import re
import sys

import pytest
from click.testing import CliRunner

from pql_odcs import __version__
from pql_odcs.cli import contract, standalone
from pql_odcs.skill import HARNESSES, frontmatter, skill_text

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.9 / 3.10
    tomllib = pytest.importorskip("tomli")


def _skill(*args):
    return CliRunner().invoke(standalone(), ["skill", *[str(a) for a in args]])


class TestContent:
    def test_frontmatter_names_the_skill_and_the_package_version(self):
        given = "the packaged SKILL.md"
        should = "be named pql-odcs (not pql-test's `contract`) and carry the pql-odcs version"
        from pathlib import Path

        pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
        version = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
        meta = frontmatter(skill_text())

        assert (meta["name"], meta["version"], meta["version"] == __version__) == ("pql-odcs", version, True), (
            f"{given}: {should}"
        )

    def test_every_standalone_command_is_documented(self):
        given = "the standalone pql-odcs commands"
        should = "each appear in the skill's command table"
        documented = set(re.findall(r"^\| `(\w+)", skill_text(), re.MULTILINE))

        assert documented == set(standalone().commands), f"{given}: {should}"

    def test_skill_is_standalone_only(self):
        given = "the contract group pql-test mounts as `pql-test contract`"
        should = "not include `skill` (pql-test has its own `pql-test skill`)"

        assert ("skill" in standalone().commands, "skill" in contract.commands) == (True, False), f"{given}: {should}"


class TestInstall:
    def test_print_by_default(self):
        given = "`pql-odcs skill` with no options"
        should = "print the skill"

        result = _skill()

        assert (result.exit_code, result.output) == (0, skill_text()), f"{given}: {should}"

    def test_install_writes_the_skill_and_is_idempotent(self, tmp_path):
        given = "--install claude twice"
        should = "write .claude/skills/pql-odcs/SKILL.md, then report it current"

        first, second = _skill("--install", "claude", "--dir", tmp_path), _skill("--install", "claude", "--dir", tmp_path)

        target = tmp_path / ".claude" / "skills" / "pql-odcs" / "SKILL.md"
        assert (first.exit_code, target.read_text(encoding="utf-8") == skill_text(), "current" in second.output) == (
            0,
            True,
            True,
        ), f"{given}: {should}\n{first.output}{second.output}"

    def test_older_version_is_updated(self, tmp_path):
        given = "an installed pql-odcs skill with an older version"
        should = "be updated"
        target = tmp_path / HARNESSES["cursor"] / "SKILL.md"
        target.parent.mkdir(parents=True)
        target.write_text("---\nname: pql-odcs\nversion: 0.0.1\n---\nold\n", encoding="utf-8")

        result = _skill("--install", "cursor", "--dir", tmp_path)

        assert ("updated" in result.output, target.read_text(encoding="utf-8") == skill_text()) == (True, True), (
            f"{given}: {should}\n{result.output}"
        )

    def test_foreign_file_is_refused_unless_forced(self, tmp_path):
        given = "a different skill already at the target path"
        should = "refuse with exit 1, and overwrite only with --force"
        target = tmp_path / HARNESSES["windsurf"] / "SKILL.md"
        target.parent.mkdir(parents=True)
        target.write_text("---\nname: mine\n---\nkeep me\n", encoding="utf-8")

        refused = _skill("--install", "windsurf", "--dir", tmp_path)
        kept = target.read_text(encoding="utf-8")
        forced = _skill("--install", "windsurf", "--dir", tmp_path, "--force")

        assert (refused.exit_code, "keep me" in kept, forced.exit_code, target.read_text(encoding="utf-8") == skill_text()) == (
            1,
            True,
            0,
            True,
        ), f"{given}: {should}\n{refused.output}{forced.output}"

    def test_dry_run_changes_nothing(self, tmp_path):
        given = "--install all --dry-run"
        should = "list every harness as would install and write nothing"

        result = _skill("--install", "all", "--dir", tmp_path, "--dry-run")

        assert (result.exit_code, result.output.count("would install"), list(tmp_path.iterdir())) == (
            0,
            len(HARNESSES),
            [],
        ), f"{given}: {should}\n{result.output}"

    def test_show_and_uninstall(self, tmp_path):
        given = "a skill installed for every harness, plus a foreign skill folder"
        should = "show each install, then remove only pql-odcs files and their empty folders"
        _skill("--install", "all", "--dir", tmp_path)
        other = tmp_path / ".claude" / "skills" / "other" / "SKILL.md"
        other.parent.mkdir(parents=True)
        other.write_text("---\nname: other\n---\n", encoding="utf-8")

        shown = _skill("--show", "--dir", tmp_path)
        removed = _skill("--uninstall", "--dir", tmp_path)

        leftovers = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("SKILL.md"))
        assert (shown.output.count(f"v{__version__}"), removed.output.count("removed"), leftovers) == (
            len(HARNESSES),
            len(HARNESSES),
            [".claude/skills/other/SKILL.md"],
        ), f"{given}: {should}\n{shown.output}{removed.output}"

    def test_one_action_at_a_time(self, tmp_path):
        given = "--install together with --uninstall"
        should = "be a usage error"

        assert _skill("--install", "claude", "--uninstall", "--dir", tmp_path).exit_code == 2, f"{given}: {should}"
