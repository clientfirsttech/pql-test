"""Skill file resolution for pql-test.

Resolves skill directories from local workspace overrides (skills/) or falls back
to packaged resources (pql_test/skills/).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional
import importlib.resources as pkg_resources


def resolve_skill_dir(name: str, repo_root: Optional[Path] = None) -> Path:
    """Resolve the directory containing a skill's SKILL.md file.
    
    Args:
        name: The skill name (e.g., "run-tests")
        repo_root: Optional repository root path. If provided, checks for local
                   override in {repo_root}/skills/{name}/. Defaults to cwd.
    
    Returns:
        Path to the skill directory containing SKILL.md
        
    Raises:
        FileNotFoundError: If the skill is not found in local override or package
    """
    # Try local override first (repo's skills/ directory)
    if repo_root is None:
        repo_root = Path.cwd()
    
    local_skill_dir = repo_root / "skills" / name
    if local_skill_dir.is_dir() and (local_skill_dir / "SKILL.md").is_file():
        return local_skill_dir
    
    # Fall back to packaged resource
    try:
        # Python 3.9+ importlib.resources.files
        if hasattr(pkg_resources, 'files'):
            pkg_skill_dir = pkg_resources.files('pql_test') / 'skills' / name  # type: ignore
            if pkg_skill_dir.is_dir() and (pkg_skill_dir / 'SKILL.md').is_file():  # type: ignore
                return Path(str(pkg_skill_dir))  # type: ignore
        else:
            # Python 3.9 fallback: importlib.resources.path (deprecated but available)
            with pkg_resources.path('pql_test.skills', name) as pkg_skill_path:  # type: ignore
                if pkg_skill_path.is_dir() and (pkg_skill_path / "SKILL.md").is_file():
                    return pkg_skill_path
    except (FileNotFoundError, ModuleNotFoundError, AttributeError):
        pass
    
    raise FileNotFoundError(
        f"Skill '{name}' not found. Checked:\n"
        f"  - Local override: {local_skill_dir}\n"
        f"  - Packaged resource: pql_test/skills/{name}\n"
        f"Available skills may be listed with: pql-test skill"
    )


def list_available_skills(repo_root: Optional[Path] = None) -> list[dict[str, str]]:
    """List all available skills from local override or package.
    
    Args:
        repo_root: Optional repository root path for local overrides
        
    Returns:
        List of dicts with keys: name, description, version, source (local|packaged)
    """
    skills: dict[str, dict[str, str]] = {}
    
    # Check packaged skills first
    try:
        if hasattr(pkg_resources, 'files'):
            pkg_skills_dir = pkg_resources.files('pql_test') / 'skills'  # type: ignore
            if pkg_skills_dir.is_dir():  # type: ignore
                for skill_dir in pkg_skills_dir.iterdir():  # type: ignore
                    if skill_dir.is_dir():  # type: ignore
                        skill_md = skill_dir / 'SKILL.md'  # type: ignore
                        if skill_md.is_file():  # type: ignore
                            skills[skill_dir.name] = _parse_skill_metadata(Path(str(skill_md)), 'packaged')  # type: ignore
    except (FileNotFoundError, ModuleNotFoundError, AttributeError):
        pass
    
    # Check local overrides (overwrite packaged entries)
    if repo_root is None:
        repo_root = Path.cwd()
    
    local_skills_dir = repo_root / "skills"
    if local_skills_dir.is_dir():
        for skill_dir in local_skills_dir.iterdir():
            if skill_dir.is_dir():
                skill_md = skill_dir / "SKILL.md"
                if skill_md.is_file():
                    skills[skill_dir.name] = _parse_skill_metadata(skill_md, 'local')
    
    return list(skills.values())


def _parse_skill_metadata(skill_md_path: Path, source: str) -> dict[str, str]:
    """Parse YAML frontmatter from a SKILL.md file.
    
    Args:
        skill_md_path: Path to SKILL.md file
        source: Either 'local' or 'packaged'
        
    Returns:
        Dict with keys: name, description, version, source
    """
    import re
    
    content = skill_md_path.read_text(encoding='utf-8')
    
    # Extract YAML frontmatter
    frontmatter_match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if not frontmatter_match:
        return {
            'name': skill_md_path.parent.name,
            'description': '(no description)',
            'version': 'unknown',
            'source': source
        }
    
    frontmatter = frontmatter_match.group(1)
    
    # Simple YAML parsing for name, description, version
    name_match = re.search(r'^name:\s*(.+)$', frontmatter, re.MULTILINE)
    desc_match = re.search(r'^description:\s*(.+)$', frontmatter, re.MULTILINE)
    ver_match = re.search(r'^version:\s*(.+)$', frontmatter, re.MULTILINE)
    
    return {
        'name': name_match.group(1).strip() if name_match else skill_md_path.parent.name,
        'description': desc_match.group(1).strip() if desc_match else '(no description)',
        'version': ver_match.group(1).strip() if ver_match else 'unknown',
        'source': source
    }
