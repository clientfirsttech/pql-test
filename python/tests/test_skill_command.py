"""Tests for pql-test skill command."""

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


def test_skill_list_shows_all_skills(runner):
    """Given pql-test skill, should list all available skills with descriptions."""
    result = runner.invoke(cli, ['skill'])
    
    assert result.exit_code == 0
    assert 'check-prereqs' in result.output
    assert 'retrieve-test' in result.output
    assert 'retrieve-tests' in result.output
    assert 'run-tests' in result.output


def test_skill_print_single_skill(runner):
    """Given pql-test skill run-tests, should print the SKILL.md content."""
    result = runner.invoke(cli, ['skill', 'run-tests'])
    
    assert result.exit_code == 0
    assert 'run-tests' in result.output
    assert 'MODEL_PATH' in result.output
    assert 'Execute all DAX test suites' in result.output


def test_skill_print_with_json_format(runner):
    """Given pql-test skill run-tests --format json, should output JSON."""
    from importlib.metadata import version as _pkg_version

    result = runner.invoke(cli, ['skill', 'run-tests', '--format', 'json'])
    
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data['name'] == 'run-tests'
    assert data['version'] == _pkg_version('pql-test')
    assert 'content' in data


def test_skill_list_flag_shows_names_only(runner):
    """Given pql-test skill --list, should output skill names only (one per line)."""
    result = runner.invoke(cli, ['skill', '--list'])
    
    assert result.exit_code == 0
    lines = result.output.strip().split('\n')
    assert 'check-prereqs' in lines
    assert 'run-tests' in lines
    # Should not include descriptions
    assert 'Execute all DAX' not in result.output


def test_skill_nonexistent_fails(runner):
    """Given a nonexistent skill name, should exit with code 1 and helpful error."""
    result = runner.invoke(cli, ['skill', 'nonexistent-skill'])
    
    assert result.exit_code == 1
    assert 'not found' in result.output.lower()
    assert 'pql-test skill' in result.output  # Suggest how to list skills


def test_skill_version_flag(runner):
    """Given pql-test skill --version, should print package version."""
    from importlib.metadata import version as _pkg_version

    result = runner.invoke(cli, ['skill', '--version'])
    
    assert result.exit_code == 0
    assert _pkg_version('pql-test') in result.output
