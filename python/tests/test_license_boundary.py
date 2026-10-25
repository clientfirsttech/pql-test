# SPDX-License-Identifier: BUSL-1.1
"""
License-boundary guards for the mixed-license repository (see LICENSES.md).

Runs the same checker the pql-odcs CI workflow runs
(.github/scripts/check_license_boundary.py), so a missing or wrong SPDX header
also fails the local pytest run.
"""

from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / ".github" / "scripts" / "check_license_boundary.py"


def _checker():
    spec = importlib.util.spec_from_file_location("check_license_boundary", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_tree(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


class TestSpdxHeaders:
    def test_repository_has_no_violations(self):
        given = "every .py file under python/ and packages/pql-odcs/"
        should = "carry the SPDX header for the license that covers its path"

        assert _checker().spdx_violations(REPO_ROOT) == [], f"{given}: {should}"

    def test_reports_missing_and_wrong_headers(self, tmp_path):
        given = "a BUSL file without a header and an MIT-path file tagged BUSL"
        should = "report both files with the expected license"
        root = _make_tree(
            tmp_path,
            {
                "python/pql_test/a.py": '"""no header"""\n',
                "packages/pql-odcs/src/pql_odcs/b.py": "# SPDX-License-Identifier: BUSL-1.1\n",
                "python/pql_test/ok.py": "# SPDX-License-Identifier: BUSL-1.1\n",
            },
        )

        actual = _checker().spdx_violations(root)

        assert actual == [
            "packages/pql-odcs/src/pql_odcs/b.py: expected '# SPDX-License-Identifier: MIT'",
            "python/pql_test/a.py: expected '# SPDX-License-Identifier: BUSL-1.1'",
        ], f"{given}: {should}"

    def test_header_may_follow_a_shebang(self, tmp_path):
        given = "a script whose first line is a shebang"
        should = "accept the SPDX header on the second line"
        root = _make_tree(
            tmp_path,
            {"python/tool.py": "#!/usr/bin/env python3\n# SPDX-License-Identifier: BUSL-1.1\n"},
        )

        assert _checker().spdx_violations(root) == [], f"{given}: {should}"

    def test_virtualenvs_and_build_output_are_ignored(self, tmp_path):
        given = "third-party files inside .venv/ and build/"
        should = "not be checked"
        root = _make_tree(
            tmp_path,
            {
                "python/.venv/Lib/site-packages/x.py": "",
                "packages/pql-odcs/build/lib/pql_odcs/y.py": "",
            },
        )

        assert _checker().spdx_violations(root) == [], f"{given}: {should}"


class TestWheelContents:
    def _wheel(self, tmp_path: Path, names: list[str]) -> Path:
        wheel = tmp_path / "pql_odcs-0.1.0-py3-none-any.whl"
        with zipfile.ZipFile(wheel, "w") as zf:
            for name in names:
                zf.writestr(name, "")
        return wheel

    def test_accepts_package_and_its_own_license_files(self, tmp_path):
        given = "a wheel holding pql_odcs/ plus dist-info with LICENSE and NOTICE"
        should = "report no violations"
        wheel = self._wheel(
            tmp_path,
            [
                "pql_odcs/__init__.py",
                "pql_odcs/catalog/pql_assert_0_7.yaml",
                "pql_odcs-0.1.0.dist-info/METADATA",
                "pql_odcs-0.1.0.dist-info/licenses/LICENSE",
                "pql_odcs-0.1.0.dist-info/licenses/NOTICE",
                "pql_odcs-0.1.0.dist-info/RECORD",
            ],
        )

        assert _checker().wheel_violations(wheel) == [], f"{given}: {should}"

    def test_rejects_pql_test_code_and_foreign_licenses(self, tmp_path):
        given = "a wheel that picked up pql_test/ and the BUSL LICENSE.txt"
        should = "report each stray file"
        wheel = self._wheel(
            tmp_path,
            [
                "pql_odcs/__init__.py",
                "pql_test/cli.py",
                "pql_odcs-0.1.0.dist-info/licenses/LICENSE.txt",
            ],
        )

        assert _checker().wheel_violations(wheel) == [
            "pql_odcs-0.1.0.dist-info/licenses/LICENSE.txt",
            "pql_test/cli.py",
        ], f"{given}: {should}"
