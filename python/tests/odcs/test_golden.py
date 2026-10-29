# SPDX-License-Identifier: AGPL-3.0-only
"""Golden files: fixture contracts must regenerate byte-identical DAX and coverage JSON.

Regenerate after an intended change with:

    PQL_TEST_UPDATE_GOLDEN=1 pytest tests/odcs/test_golden.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from pql_test.odcs.api import plan_contract, render
from pql_test.odcs.coverage import build_report

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
GOLDEN = HERE / "golden"
VERSION = "GOLDEN"  # keeps golden files stable across pql-test version bumps
UPDATE = os.environ.get("PQL_TEST_UPDATE_GOLDEN") == "1"

CASES = {
    "marvel": {"contract": "marvel.odcs.yaml"},
    "marvel-must-fail": {"contract": "marvel-must-fail.odcs.yaml"},
    "every-row": {"contract": "every-row.odcs.yaml", "closed_schema": True},
    "every-row-0-8": {"contract": "every-row.odcs.yaml", "closed_schema": True, "pql_assert": "0.8"},
    "rule-coverage": {"contract": "rule-coverage.odcs.yaml"},
    "rule-coverage-0-8": {"contract": "rule-coverage.odcs.yaml", "pql_assert": "0.8"},
}


def _expected_files(case: str) -> dict[str, bytes]:
    options = CASES[case]
    plan = plan_contract(
        FIXTURES / options["contract"],
        closed_schema=options.get("closed_schema", False),
        pql_assert=options.get("pql_assert", "0.7"),
    )
    files = {f.file_name: f.content.encode("utf-8") for f in render(plan, env="DEV", version=VERSION)}
    report = build_report(plan.contract, plan.outcomes, catalog=plan.catalog, version=VERSION)
    files["coverage.json"] = (json.dumps(report, indent=2) + "\n").encode("utf-8")
    return files


@pytest.mark.parametrize("case", sorted(CASES))
def test_fixture_regenerates_byte_identical_output(case):
    given = f"the {case} fixture contract"
    should = "regenerate byte-identical golden DAX suites and coverage JSON"
    actual = _expected_files(case)
    folder = GOLDEN / case
    if UPDATE:
        folder.mkdir(parents=True, exist_ok=True)
        for stale in folder.iterdir():
            stale.unlink()
        for name, data in actual.items():
            (folder / name).write_bytes(data)

    golden = {p.name: p.read_bytes() for p in sorted(folder.iterdir())} if folder.is_dir() else {}

    assert actual == golden, f"{given}: {should} (set PQL_TEST_UPDATE_GOLDEN=1 after an intended change)"
