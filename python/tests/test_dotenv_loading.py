# SPDX-License-Identifier: AGPL-3.0-only
"""The CLI loads the .env of the folder it runs in (tasks/dotenv-from-working-directory-epic.md).

Each test imports ``pql_test.cli`` in a fresh interpreter from a script file, as a real run
does: python-dotenv searches differently under ``python -c`` or a REPL.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

VAR = "PQL_DOTENV_PROBE"
SCRIPT = f"import os, pql_test.cli\nprint(os.environ.get({VAR!r}, '<unset>'))\n"


def _probe(cwd: Path, scripts: Path, **env: str) -> str:
    """The value of VAR after importing the CLI with *cwd* as the working directory."""
    script = scripts / "probe.py"
    script.write_text(SCRIPT, encoding="utf-8")
    child = {k: v for k, v in os.environ.items() if k not in (VAR, "PQL_TEST_HERMETIC")}
    child.update(env)
    out = subprocess.run(  # noqa: S603 - fixed interpreter and script
        [sys.executable, str(script)], cwd=cwd, env=child, capture_output=True, text=True, timeout=60, check=True
    )
    return out.stdout.strip()


def _project(tmp_path: Path) -> tuple[Path, Path]:
    project, scripts = tmp_path / "project", tmp_path / "scripts"
    project.mkdir()
    scripts.mkdir()
    (project / ".env").write_text(f"{VAR}=from-project\n", encoding="utf-8")
    return project, scripts


class TestDotenvFromWorkingDirectory:
    def test_loads_the_env_file_where_the_cli_runs(self, tmp_path):
        given = "a .env in the working directory"
        should = "load its variables"
        project, scripts = _project(tmp_path)

        assert _probe(project, scripts) == "from-project", f"{given}: {should}"

    def test_loads_the_env_file_of_a_parent_folder(self, tmp_path):
        given = "a .env in a parent of the working directory"
        should = "load its variables"
        project, scripts = _project(tmp_path)
        (project / "models").mkdir()

        assert _probe(project / "models", scripts) == "from-project", f"{given}: {should}"

    def test_the_environment_wins_over_the_env_file(self, tmp_path):
        given = "the variable already set in the environment"
        should = "keep the environment's value"
        project, scripts = _project(tmp_path)

        assert _probe(project, scripts, **{VAR: "from-environment"}) == "from-environment", f"{given}: {should}"

    def test_hermetic_mode_loads_nothing(self, tmp_path):
        given = "PQL_TEST_HERMETIC set"
        should = "load no .env"
        project, scripts = _project(tmp_path)

        assert _probe(project, scripts, PQL_TEST_HERMETIC="1") == "<unset>", f"{given}: {should}"
