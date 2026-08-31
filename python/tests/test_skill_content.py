"""Mode A skill content assertions.

Verifies each SKILL.md documents the actual CLI surface so LLMs never receive
stale or incomplete instructions. Uses Click's introspection as the source of
truth for flag names.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


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
