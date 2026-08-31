"""Tests for skill packaging and format validation."""

from __future__ import annotations

import pytest
from pathlib import Path
import re


def test_source_and_packaged_skills_match():
    """Given packaged skills, should match source skills/ directory byte-for-byte."""
    source_skills_dir = Path(__file__).parent.parent.parent / 'skills'
    packaged_skills_dir = Path(__file__).parent.parent / 'pql_test' / 'skills'
    
    # Get all SKILL.md files from source
    source_files = list(source_skills_dir.glob('*/SKILL.md'))
    assert len(source_files) > 0, "No source skills found"
    
    for source_file in source_files:
        skill_name = source_file.parent.name
        packaged_file = packaged_skills_dir / skill_name / 'SKILL.md'
        
        assert packaged_file.exists(), f"Packaged skill missing: {skill_name}"
        
        source_content = source_file.read_text(encoding='utf-8')
        packaged_content = packaged_file.read_text(encoding='utf-8')
        
        # Normalize line endings for comparison
        source_normalized = source_content.replace('\r\n', '\n')
        packaged_normalized = packaged_content.replace('\r\n', '\n')
        
        assert source_normalized == packaged_normalized, \
            f"Skill content mismatch: {skill_name}\nSource and packaged files differ"


def test_all_skills_have_required_frontmatter():
    """Given all SKILL.md files, should have name and description in YAML frontmatter."""
    skills_dir = Path(__file__).parent.parent / 'pql_test' / 'skills'
    skill_files = list(skills_dir.glob('*/SKILL.md'))
    
    assert len(skill_files) > 0, "No packaged skills found"
    
    for skill_file in skill_files:
        content = skill_file.read_text(encoding='utf-8')
        
        # Check for YAML frontmatter
        assert content.startswith('---'), \
            f"{skill_file.name} missing YAML frontmatter"
        
        # Extract frontmatter
        frontmatter_match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
        assert frontmatter_match, f"{skill_file.name} has invalid frontmatter"
        
        frontmatter = frontmatter_match.group(1)
        
        # Check required fields
        assert re.search(r'^name:\s*\S+', frontmatter, re.MULTILINE), \
            f"{skill_file.name} missing 'name' field"
        assert re.search(r'^description:\s*.+', frontmatter, re.MULTILINE), \
            f"{skill_file.name} missing 'description' field"


def test_skill_versions_match_package_version():
    """Given skill frontmatter version fields, should match pyproject.toml version."""
    import tomli
    
    # Read package version from pyproject.toml
    pyproject_path = Path(__file__).parent.parent / 'pyproject.toml'
    with open(pyproject_path, 'rb') as f:
        pyproject = tomli.load(f)
    
    package_version = pyproject['project']['version']
    
    # Check all skills
    skills_dir = Path(__file__).parent.parent / 'pql_test' / 'skills'
    skill_files = list(skills_dir.glob('*/SKILL.md'))
    
    for skill_file in skill_files:
        content = skill_file.read_text(encoding='utf-8')
        
        # Extract version from frontmatter
        version_match = re.search(r'^version:\s*(.+)$', content, re.MULTILINE)
        if version_match:
            skill_version = version_match.group(1).strip()
            assert skill_version == package_version, \
                f"{skill_file.name} version mismatch: {skill_version} != {package_version}"


def test_run_tests_skill_has_sudolang_contract():
    """Given run-tests SKILL.md, should have SudoLang Interface and Constraints blocks."""
    skills_dir = Path(__file__).parent.parent / 'pql_test' / 'skills'
    run_tests_file = skills_dir / 'run-tests' / 'SKILL.md'
    
    assert run_tests_file.exists(), "run-tests SKILL.md not found"
    
    content = run_tests_file.read_text(encoding='utf-8')
    
    # Check for SudoLang constructs
    assert 'Interface RunTests' in content, \
        "run-tests SKILL.md missing Interface block"
    assert 'Constraints {' in content, \
        "run-tests SKILL.md missing Constraints block"
    assert 'exit_code:' in content, \
        "run-tests SKILL.md missing exit_code specification"


def test_all_skills_are_packaged():
    """Given source skills/ directory, all skills should be in packaged pql_test/skills/."""
    source_skills_dir = Path(__file__).parent.parent.parent / 'skills'
    packaged_skills_dir = Path(__file__).parent.parent / 'pql_test' / 'skills'
    
    source_skill_names = {d.name for d in source_skills_dir.iterdir() if d.is_dir()}
    packaged_skill_names = {d.name for d in packaged_skills_dir.iterdir() if d.is_dir()}
    
    missing = source_skill_names - packaged_skill_names
    assert not missing, f"Skills not packaged: {missing}"


def test_pyproject_includes_package_data():
    """Given pyproject.toml, should include skills/**/*.md in package-data."""
    import tomli
    
    pyproject_path = Path(__file__).parent.parent / 'pyproject.toml'
    with open(pyproject_path, 'rb') as f:
        pyproject = tomli.load(f)
    
    package_data = pyproject.get('tool', {}).get('setuptools', {}).get('package-data', {})
    pql_test_data = package_data.get('pql_test', [])
    
    assert 'skills/**/*.md' in pql_test_data, \
        "pyproject.toml missing skills/**/*.md in package-data"
