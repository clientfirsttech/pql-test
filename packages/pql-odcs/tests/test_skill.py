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


class TestEdgeCases:
    def test_newer_installed_version_is_not_downgraded(self, tmp_path):
        given = "an installed pql-odcs skill newer than this package's"
        should = "refuse with exit 1 and keep it, unless --force"
        target = tmp_path / HARNESSES["claude"] / "SKILL.md"
        target.parent.mkdir(parents=True)
        target.write_text("---\nname: pql-odcs\nversion: 99.0.0\n---\nnewer\n", encoding="utf-8")

        refused = _skill("--install", "claude", "--dir", tmp_path)
        kept = "newer" in target.read_text(encoding="utf-8")
        forced = _skill("--install", "claude", "--dir", tmp_path, "--force")

        assert (refused.exit_code, kept, forced.exit_code, target.read_text(encoding="utf-8") == skill_text()) == (
            1,
            True,
            0,
            True,
        ), f"{given}: {should}\n{refused.output}"

    def test_unreadable_file_is_foreign(self, tmp_path):
        given = "a UTF-16 SKILL.md at the target path"
        should = "be refused by install and uninstall, shown as foreign, and replaced by --force"
        target = tmp_path / HARNESSES["claude"] / "SKILL.md"
        target.parent.mkdir(parents=True)
        target.write_bytes("---\nname: pql-odcs\n---\n".encode("utf-16"))

        install, uninstall, show = (
            _skill("--install", "claude", "--dir", tmp_path),
            _skill("--uninstall", "--dir", tmp_path),
            _skill("--show", "--dir", tmp_path),
        )
        forced = _skill("--install", "claude", "--dir", tmp_path, "--force")

        assert (install.exit_code, uninstall.exit_code, "foreign" in show.output, forced.exit_code) == (1, 1, True, 0), (
            f"{given}: {should}\n{install.output}{uninstall.output}{show.output}{forced.output}"
        )

    def test_symlinked_target_is_never_written(self, tmp_path):
        given = "a SKILL.md that is a symlink to a file elsewhere"
        should = "be refused, even with --force, leaving the link target unchanged"
        outside = tmp_path / "outside.md"
        outside.write_text("---\nname: pql-odcs\nversion: 0.0.1\n---\n", encoding="utf-8")
        target = tmp_path / "proj" / HARNESSES["claude"] / "SKILL.md"
        target.parent.mkdir(parents=True)
        try:
            target.symlink_to(outside)
        except OSError:
            pytest.skip("creating symlinks needs extra privileges here")

        result = _skill("--install", "claude", "--dir", tmp_path / "proj", "--force")

        assert (result.exit_code, "symlink" in result.output, outside.read_text(encoding="utf-8").endswith("---\n")) == (
            1,
            True,
            True,
        ), f"{given}: {should}\n{result.output}"

    def test_a_failing_harness_does_not_hide_the_others(self, tmp_path):
        given = "--install all where .github is a file, so the Copilot folder cannot be created"
        should = "install the other harnesses, report the Copilot error on its own line, and exit 1"
        (tmp_path / ".github").write_text("not a folder", encoding="utf-8")

        result = _skill("--install", "all", "--dir", tmp_path)

        lines = {line.split()[0]: line.split()[1] for line in result.output.splitlines()}
        assert (result.exit_code, lines) == (
            1,
            {"claude": "installed", "copilot": "error", "cursor": "installed", "windsurf": "installed"},
        ), f"{given}: {should}\n{result.output}"

    def test_foreign_file_survives_uninstall(self, tmp_path):
        given = "a different skill at a pql-odcs path"
        should = "be left in place by --uninstall, which exits 1"
        target = tmp_path / HARNESSES["cursor"] / "SKILL.md"
        target.parent.mkdir(parents=True)
        target.write_text("---\nname: mine\n---\n", encoding="utf-8")

        result = _skill("--uninstall", "--dir", tmp_path)

        assert (result.exit_code, target.exists()) == (1, True), f"{given}: {should}\n{result.output}"

    def test_uninstall_dry_run_keeps_files(self, tmp_path):
        given = "an installed skill and --uninstall --dry-run"
        should = "say would remove and keep the file"
        _skill("--install", "claude", "--dir", tmp_path)

        result = _skill("--uninstall", "--dir", tmp_path, "--dry-run")

        assert ("would remove" in result.output, (tmp_path / HARNESSES["claude"] / "SKILL.md").exists()) == (
            True,
            True,
        ), f"{given}: {should}\n{result.output}"

    def test_show_reports_a_stale_install(self, tmp_path):
        given = "an older pql-odcs skill installed"
        should = "show it with the version this package ships"
        target = tmp_path / HARNESSES["claude"] / "SKILL.md"
        target.parent.mkdir(parents=True)
        target.write_text("---\nname: pql-odcs\nversion: 0.0.1\n---\n", encoding="utf-8")

        result = _skill("--show", "--dir", tmp_path)

        assert f"v0.0.1, this pql-odcs ships v{__version__}" in result.output, f"{given}: {should}\n{result.output}"

    def test_dry_run_without_a_change_is_a_usage_error(self, tmp_path):
        given = "--show --dry-run"
        should = "be a usage error rather than silently ignored"

        assert _skill("--show", "--dry-run", "--dir", tmp_path).exit_code == 2, f"{given}: {should}"
