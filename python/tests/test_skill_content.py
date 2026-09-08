"""Mode A skill content assertions.

Verifies each SKILL.md documents the actual CLI surface so LLMs never receive
stale or incomplete instructions. Uses Click's introspection as the source of
truth for flag names.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from pql_test.runner import TestSuite
from pql_test.skills_resolver import _parse_skill_metadata, list_available_skills, resolve_skill_dir


SKILLS_DIR = Path(__file__).parent.parent / "pql_test" / "skills"


def _skill_content(name: str) -> str:
    path = SKILLS_DIR / name / "SKILL.md"
    assert path.exists(), f"Skill file not found: {path}"
    return path.read_text(encoding="utf-8")


def _skill_body(name: str) -> str:
    """Skill content with YAML frontmatter stripped (description text can contain false-positive matches)."""
    content = _skill_content(name)
    m = re.match(r"^---\s*\n.*?\n---\s*\n(.*)", content, re.DOTALL)
    return m.group(1) if m else content


def _click_flags(command_name: str) -> set[str]:
    """Return the set of long-form Click flags declared on a command."""
    from pql_test import cli as cli_module

    command = cli_module.cli.commands[command_name]
    flags: set[str] = set()
    for param in command.params:
        for opt in param.opts:
            if opt.startswith("--"):
                flags.add(opt)
    return flags


def test_testsuite_dataclass_is_not_collected_by_pytest():
    """The runner summary model should not be mistaken for a pytest test class."""
    assert TestSuite.__test__ is False


def test_resolve_skill_dir_prefers_local_override(tmp_path):
    """Local skills should win over the packaged defaults when both exist."""
    local_dir = tmp_path / "skills" / "demo" / "SKILL.md"
    local_dir.parent.mkdir(parents=True)
    local_dir.write_text("---\nname: demo\ndescription: local demo\nversion: 1.2.3\n---\n", encoding="utf-8")

    resolved = resolve_skill_dir("demo", repo_root=tmp_path)

    assert resolved == local_dir.parent
    assert resolved.joinpath("SKILL.md").read_text(encoding="utf-8") == local_dir.read_text(encoding="utf-8")


def test_list_available_skills_and_metadata_parse_local_override(tmp_path):
    """Skill metadata should parse from a local override and be returned by the resolver."""
    local_dir = tmp_path / "skills" / "demo" / "SKILL.md"
    local_dir.parent.mkdir(parents=True)
    local_dir.write_text(
        "---\nname: demo\ndescription: demo skill\nversion: 9.9.9\n---\ncontent here\n",
        encoding="utf-8",
    )

    parsed = _parse_skill_metadata(local_dir, "local")
    skills = list_available_skills(repo_root=tmp_path)

    assert parsed["name"] == "demo"
    assert parsed["description"] == "demo skill"
    assert parsed["version"] == "9.9.9"
    assert any(skill["name"] == "demo" and skill["source"] == "local" for skill in skills)


def test_resolve_skill_dir_raises_helpful_error_for_unknown_skill(tmp_path):
    """Missing skill names should raise a clear FileNotFoundError for end users."""
    with pytest.raises(FileNotFoundError, match="Skill 'missing-skill' not found"):
        resolve_skill_dir("missing-skill", repo_root=tmp_path)


def test_parse_skill_metadata_without_frontmatter_uses_defaults():
    """SKILL.md files without frontmatter should still return sensible metadata."""
    path = SKILLS_DIR / "run-tests" / "SKILL.md"
    body = path.read_text(encoding="utf-8")
    stripped = body.split("---\n", 2)[-1] if body.startswith("---") else body
    tmp_path = Path(__file__).parent / "tmp-skill-no-frontmatter.md"
    tmp_path.write_text(stripped, encoding="utf-8")
    try:
        parsed = _parse_skill_metadata(tmp_path, "packaged")
        assert parsed["name"] == tmp_path.parent.name
        assert parsed["description"] == "(no description)"
        assert parsed["version"] == "unknown"
    finally:
        tmp_path.unlink(missing_ok=True)


def test_resolve_skill_dir_handles_packaged_lookup_failure(monkeypatch, tmp_path):
    """When packaged skills are unavailable, resolve_skill_dir should still raise a clear error."""
    import pql_test.skills_resolver as skills_resolver

    def raise_file_not_found(*args, **kwargs):
        raise FileNotFoundError("missing package")

    monkeypatch.setattr(skills_resolver.pkg_resources, "files", raise_file_not_found)

    with pytest.raises(FileNotFoundError, match="Skill 'missing-skill' not found"):
        skills_resolver.resolve_skill_dir("missing-skill", repo_root=tmp_path)


def test_list_available_skills_handles_packaged_lookup_failure(monkeypatch, tmp_path):
    """Missing packaged metadata should not crash listing; it should fall back cleanly to local skills only."""
    import pql_test.skills_resolver as skills_resolver

    def raise_file_not_found(*args, **kwargs):
        raise FileNotFoundError("missing package")

    monkeypatch.setattr(skills_resolver.pkg_resources, "files", raise_file_not_found)

    skills = skills_resolver.list_available_skills(repo_root=tmp_path)
    assert isinstance(skills, list)
    assert skills == []


# ---------------------------------------------------------------------------
# run-tests skill
# ---------------------------------------------------------------------------


def test_run_tests_documents_all_click_flags():
    """Every long-form flag on cmd_run_tests must appear in run-tests SKILL.md."""
    content = _skill_content("run-tests")
    flags = _click_flags("run-tests")
    missing = [f for f in flags if f not in content]
    assert not missing, (
        f"run-tests SKILL.md is missing flags: {missing}. "
        f"Update SKILL.md when adding CLI flags."
    )


def test_run_tests_documents_all_model_path_formats():
    """run-tests must document filesystem, local/<name>, and workspace.Workspace paths."""
    content = _skill_content("run-tests")
    assert "local/" in content, "run-tests missing local/<name> format"
    assert ".Workspace/" in content and ".SemanticModel" in content, (
        "run-tests missing canonical Fabric path format"
    )
    assert re.search(r"[Ff]ilesystem path", content), (
        "run-tests missing filesystem path description"
    )


def test_run_tests_has_sudolang_interface_block():
    """SudoLang Interface block declares exit_code, output_format, log_annotations."""
    content = _skill_content("run-tests")
    assert "Interface RunTests" in content, "Missing Interface RunTests block"
    assert "exit_code" in content, "Interface missing exit_code field"
    assert "output_format" in content, "Interface missing output_format field"
    assert "log_annotations" in content, "Interface missing log_annotations field"


def test_run_tests_has_sudolang_constraints_block():
    """Constraints block covers MODEL_PATH resolution, credentials, env filtering."""
    content = _skill_content("run-tests")
    assert "Constraints" in content, "Missing Constraints block"
    assert "MODEL_PATH" in content, "Constraints missing MODEL_PATH resolution"
    assert re.search(r"[Cc]redential", content), "Constraints missing credential precedence"
    assert re.search(r"--env|PQL_TEST_ENV", content), "Constraints missing env filtering"


def test_run_tests_documents_exit_codes():
    """Must state exit code 0 = pass, 1 = fail so LLMs interpret CI results correctly."""
    content = _skill_content("run-tests")
    assert re.search(r"`?0`?\s*=\s*.*(passed|pass)", content, re.IGNORECASE), (
        "run-tests missing exit code 0 = passed"
    )
    assert re.search(r"`?1`?\s*=\s*.*(fail)", content, re.IGNORECASE), (
        "run-tests missing exit code 1 = failed"
    )


def test_run_tests_documents_environment_variables():
    """All PQL_* env vars that map to CLI flags must be documented."""
    content = _skill_content("run-tests")
    required = [
        "PQL_TENANT_ID",
        "PQL_WORKSPACE_ID",
        "PQL_DATASET_ID",
        "PQL_CLIENT_ID",
        "PQL_CLIENT_SECRET",
        "PQL_ENVIRONMENT",
        "PQL_TEST_ENV",
    ]
    missing = [v for v in required if v not in content]
    assert not missing, f"run-tests missing env vars: {missing}"


def test_run_tests_documents_log_format_values():
    """Both --log-format values (github, azuredevops) must be documented."""
    content = _skill_content("run-tests")
    assert "github" in content, "run-tests missing --log-format github"
    assert "azuredevops" in content, "run-tests missing --log-format azuredevops"


# ---------------------------------------------------------------------------
# retrieve-tests skill
# ---------------------------------------------------------------------------


def test_retrieve_tests_documents_all_click_flags():
    content = _skill_content("retrieve-tests")
    flags = _click_flags("retrieve-tests")
    missing = [f for f in flags if f not in content]
    assert not missing, f"retrieve-tests SKILL.md is missing flags: {missing}"


def test_retrieve_tests_documents_env_filter():
    content = _skill_content("retrieve-tests")
    assert "--env" in content, "retrieve-tests missing --env flag"
    assert re.search(r"DEV|PROD|ANY", content), "retrieve-tests missing env value examples"


def test_retrieve_tests_documents_all_model_path_formats():
    content = _skill_content("retrieve-tests")
    assert "local/" in content
    assert ".Workspace/" in content and ".SemanticModel" in content


# ---------------------------------------------------------------------------
# retrieve-test skill
# ---------------------------------------------------------------------------


def test_retrieve_test_documents_all_click_flags():
    content = _skill_content("retrieve-test")
    flags = _click_flags("retrieve-test")
    missing = [f for f in flags if f not in content]
    assert not missing, f"retrieve-test SKILL.md is missing flags: {missing}"


def test_retrieve_test_documents_verbose_dax_source():
    """--verbose must be described as showing the full DAX source."""
    content = _skill_content("retrieve-test")
    assert "--verbose" in content, "retrieve-test missing --verbose flag"
    assert re.search(r"DAX source|full DAX", content), (
        "retrieve-test must describe --verbose as showing DAX source"
    )


# ---------------------------------------------------------------------------
# check-prereqs skill
# ---------------------------------------------------------------------------


def test_check_prereqs_lists_all_dependencies():
    """All four prereqs must be documented so users know what to install."""
    content = _skill_content("check-prereqs")
    for prereq in ("Python", "pyadomd", "msal", "psutil"):
        assert prereq in content, f"check-prereqs SKILL.md missing '{prereq}'"


def test_check_prereqs_documents_python_version_floor():
    content = _skill_content("check-prereqs")
    assert re.search(r"3\.9|>=\s*3\.9", content), (
        "check-prereqs must state Python >= 3.9 minimum"
    )


# ---------------------------------------------------------------------------
# skill command (self-referential)
# ---------------------------------------------------------------------------


def test_skill_command_has_documented_skill_file():
    """The skill command itself has no SKILL.md yet (it manages the others)."""
    path = SKILLS_DIR / "skill" / "SKILL.md"
    if path.exists():
        content = path.read_text(encoding="utf-8")
        for harness in ("claude", "copilot", "cursor", "windsurf"):
            assert harness in content.lower(), f"skill SKILL.md missing harness: {harness}"


# ---------------------------------------------------------------------------
# Cross-skill invariants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "skill_name",
    ["check-prereqs", "retrieve-tests", "retrieve-test", "run-tests"],
)
def test_skill_has_runnable_usage_example(skill_name: str):
    """Every skill must include at least one `pql-test <command>` example."""
    content = _skill_content(skill_name)
    pattern = rf"pql-test\s+{re.escape(skill_name)}"
    assert re.search(pattern, content), (
        f"{skill_name} SKILL.md missing a `pql-test {skill_name}` example"
    )


@pytest.mark.parametrize(
    "skill_name",
    ["check-prereqs", "retrieve-tests", "retrieve-test", "run-tests"],
)
def test_skill_does_not_reference_removed_local_flag(skill_name: str):
    """The --local flag was removed; no skill should mention it as a valid flag."""
    content = _skill_content(skill_name)
    matches = re.findall(r"--local\b", content)
    assert not matches, (
        f"{skill_name} SKILL.md references removed flag `--local`. "
        f"Use `local/<name>` MODEL_PATH syntax instead."
    )


@pytest.mark.parametrize(
    "skill_name",
    ["check-prereqs", "retrieve-tests", "retrieve-test", "run-tests"],
)
def test_skill_only_uses_real_command_names(skill_name: str):
    """Any `pql-test <word>` reference must be a real CLI command."""
    from pql_test import cli as cli_module

    real_commands = set(cli_module.cli.commands.keys())
    content = _skill_body(skill_name)
    referenced = set(re.findall(r"pql-test\s+([a-z][a-z-]+)", content))
    referenced -= {"auth"}  # auth is a group with subcommands, handled separately
    invented = referenced - real_commands
    assert not invented, (
        f"{skill_name} SKILL.md references non-existent commands: {invented}. "
        f"Real commands: {sorted(real_commands)}"
    )
