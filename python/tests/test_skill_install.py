"""Tests for pql-test skill install/uninstall functionality."""

from __future__ import annotations

import json
import pytest
from pathlib import Path
from click.testing import CliRunner
from pql_test.cli import cli


@pytest.fixture
def runner():
    """Provide a Click CLI test runner."""
    return CliRunner()


@pytest.fixture
def temp_workspace(tmp_path):
    """Create a temporary workspace directory."""
    return tmp_path


def test_skill_install_copilot_creates_instructions_file(runner, temp_workspace):
    """Given pql-test skill --install copilot, should create .github/copilot-instructions.md."""
    with runner.isolated_filesystem(temp_dir=temp_workspace):
        result = runner.invoke(cli, ['skill', '--install', 'copilot'])
        
        assert result.exit_code == 0
        copilot_file = Path('.github/copilot-instructions.md')
        assert copilot_file.exists()
        content = copilot_file.read_text()
        assert 'pql-test' in content.lower()
        assert 'run-tests' in content


def test_skill_install_claude_creates_skills_directory(runner, temp_workspace):
    """Given pql-test skill --install claude, should create .github/skills/pql-test/."""
    with runner.isolated_filesystem(temp_dir=temp_workspace):
        result = runner.invoke(cli, ['skill', '--install', 'claude'])
        
        assert result.exit_code == 0
        assert Path('.github/skills/pql-test/run-tests/SKILL.md').exists()
        assert Path('.github/skills/pql-test/check-prereqs/SKILL.md').exists()


def test_skill_install_cursor_creates_cursor_directory(runner, temp_workspace):
    """Given pql-test skill --install cursor, should create .cursor/skills/pql-test/."""
    with runner.isolated_filesystem(temp_dir=temp_workspace):
        result = runner.invoke(cli, ['skill', '--install', 'cursor'])
        
        assert result.exit_code == 0
        assert Path('.cursor/skills/pql-test/run-tests/SKILL.md').exists()


def test_skill_install_windsurf_creates_windsurf_directory(runner, temp_workspace):
    """Given pql-test skill --install windsurf, should create .windsurf/skills/pql-test/."""
    with runner.isolated_filesystem(temp_dir=temp_workspace):
        result = runner.invoke(cli, ['skill', '--install', 'windsurf'])
        
        assert result.exit_code == 0
        assert Path('.windsurf/skills/pql-test/run-tests/SKILL.md').exists()


def test_skill_install_adds_marker_comment(runner, temp_workspace):
    """Given installed skill files, should contain marker comment with version."""
    from importlib.metadata import version as _pkg_version

    with runner.isolated_filesystem(temp_dir=temp_workspace):
        runner.invoke(cli, ['skill', '--install', 'claude'])
        
        skill_file = Path('.github/skills/pql-test/run-tests/SKILL.md')
        content = skill_file.read_text()
        marker = f'<!-- Installed by pql-test skill v{_pkg_version("pql-test")} -->'
        assert marker in content


def test_skill_install_dry_run_reports_changes_without_writing(runner, temp_workspace):
    """Given pql-test skill --install claude --dry-run, should report what would change without writing."""
    with runner.isolated_filesystem(temp_dir=temp_workspace):
        result = runner.invoke(cli, ['skill', '--install', 'claude', '--dry-run'])
        
        assert result.exit_code == 0
        assert 'would create' in result.output.lower() or 'would install' in result.output.lower()
        assert not Path('.github/skills/pql-test/').exists()


def test_skill_install_reports_created_files(runner, temp_workspace):
    """Given pql-test skill --install, should report created/updated/unchanged per file."""
    with runner.isolated_filesystem(temp_dir=temp_workspace):
        result = runner.invoke(cli, ['skill', '--install', 'claude'])
        
        assert result.exit_code == 0
        assert 'created' in result.output.lower() or 'installed' in result.output.lower()
        assert 'run-tests' in result.output


def test_skill_install_is_idempotent(runner, temp_workspace):
    """Given pql-test skill --install run twice, should not error and report unchanged."""
    with runner.isolated_filesystem(temp_dir=temp_workspace):
        result1 = runner.invoke(cli, ['skill', '--install', 'claude'])
        result2 = runner.invoke(cli, ['skill', '--install', 'claude'])
        
        assert result1.exit_code == 0
        assert result2.exit_code == 0
        assert 'unchanged' in result2.output.lower() or 'already' in result2.output.lower()


def test_skill_show_reports_install_status(runner, temp_workspace):
    """Given pql-test skill --show, should report install state per harness."""
    with runner.isolated_filesystem(temp_dir=temp_workspace):
        # Install to one harness
        runner.invoke(cli, ['skill', '--install', 'claude'])
        
        result = runner.invoke(cli, ['skill', '--show'])
        
        assert result.exit_code == 0
        assert 'claude' in result.output.lower()
        assert 'copilot' in result.output.lower()
        # Should show installed status for claude
        assert 'installed' in result.output.lower() or '✓' in result.output or '✅' in result.output


def test_skill_uninstall_removes_installed_files(runner, temp_workspace):
    """Given pql-test skill --uninstall, should remove files with pql-test marker."""
    with runner.isolated_filesystem(temp_dir=temp_workspace):
        # Install first
        runner.invoke(cli, ['skill', '--install', 'claude'])
        assert Path('.github/skills/pql-test/run-tests/SKILL.md').exists()
        
        # Uninstall
        result = runner.invoke(cli, ['skill', '--uninstall'])
        
        assert result.exit_code == 0
        assert not Path('.github/skills/pql-test/').exists()


def test_skill_install_invalid_harness_fails(runner, temp_workspace):
    """Given pql-test skill --install invalid-name, should list valid harnesses and exit 1."""
    with runner.isolated_filesystem(temp_dir=temp_workspace):
        result = runner.invoke(cli, ['skill', '--install', 'invalid-harness'])
        
        assert result.exit_code == 1
        assert 'claude' in result.output.lower()
        assert 'copilot' in result.output.lower()
        assert 'cursor' in result.output.lower()
        assert 'windsurf' in result.output.lower()


def test_skill_install_all_installs_to_all_harnesses(runner, temp_workspace):
    """Given pql-test skill --all, should install to all detected harnesses."""
    with runner.isolated_filesystem(temp_dir=temp_workspace):
        result = runner.invoke(cli, ['skill', '--all'])
        
        assert result.exit_code == 0
        # Should create files for all harnesses
        assert Path('.github/copilot-instructions.md').exists()
        assert Path('.github/skills/pql-test/run-tests/SKILL.md').exists()
        assert Path('.cursor/skills/pql-test/run-tests/SKILL.md').exists()
        assert Path('.windsurf/skills/pql-test/run-tests/SKILL.md').exists()


def test_skill_show_detects_version_mismatch(runner, temp_workspace):
    """Given installed skill with different version, should report version mismatch."""
    from importlib.metadata import version as _pkg_version

    with runner.isolated_filesystem(temp_dir=temp_workspace):
        runner.invoke(cli, ['skill', '--install', 'claude'])
        
        skill_file = Path('.github/skills/pql-test/run-tests/SKILL.md')
        content = skill_file.read_text()
        current = f'v{_pkg_version("pql-test")}'
        modified = content.replace(current, 'v0.1.0')
        skill_file.write_text(modified)
        
        result = runner.invoke(cli, ['skill', '--show'])
        
        assert result.exit_code == 0
        assert 'mismatch' in result.output.lower() or 'outdated' in result.output.lower()
