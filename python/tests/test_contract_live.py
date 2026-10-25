# SPDX-License-Identifier: BUSL-1.1
"""
Live integration: `pql-test contract run` against examples/SampleModel.

Generates suites from the pql-odcs fixture contracts into a temporary copy of
SampleModel, runs them over XMLA, and checks the traced rule statuses:

  - marvel.odcs.yaml (good data): every mapped rule passes
  - marvel-must-fail.odcs.yaml: exactly the rules in EXPECTED_FAILURES fail

Needs pql-odcs (pip install pql-test[contracts]) and either a Power BI Desktop
instance with SampleModel open, or the PQL_TENANT_ID / PQL_WORKSPACE_ID /
PQL_DATASET_ID (+ client) service credentials used by test_live_service.py.
Skipped otherwise.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

# Same credential source as test_live_service.py; real env vars (CI secrets) win.
try:
    from dotenv import load_dotenv

    _env_file = Path(__file__).parent / ".env"
    if _env_file.exists():
        load_dotenv(_env_file, override=False)
except ImportError:
    pass

pytestmark = pytest.mark.live

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES = REPO_ROOT / "packages" / "pql-odcs" / "tests" / "fixtures"
EXAMPLES = REPO_ROOT / "examples"

# Rules in marvel-must-fail.odcs.yaml that must fail against SampleModel's data.
EXPECTED_FAILURES = {
    "marvel_fact_exactly_one_row",  # rowCount mustBe 1
    "DateDim.Year.unique",  # many dates share a year
    "date_dim_fewer_than_one_row",  # rowCount mustBeLessThan 1
    "ghost.exists",  # table NoSuchTable does not exist
    "ghost.columns",  # ...nor its columns
}


def _connection_available() -> bool:
    from pql_test.runner import HAS_PYADOMD

    if not HAS_PYADOMD:
        return False
    if all(os.environ.get(k, "").strip() for k in ("PQL_TENANT_ID", "PQL_WORKSPACE_ID", "PQL_DATASET_ID")):
        return True
    try:
        from pql_test.runner import resolve_local_xmla_connection_by_name

        return resolve_local_xmla_connection_by_name("SampleModel") is not None
    except Exception:  # psutil missing, no Desktop running, ...
        return False


@pytest.fixture
def sample_model_copy(tmp_path: Path) -> Path:
    """A throwaway copy of the SampleModel PBIP so generated suites never touch examples/."""
    pytest.importorskip("pql_odcs")
    if not _connection_available():
        pytest.skip("No XMLA connection: open SampleModel in Power BI Desktop or set PQL_* service credentials.")
    shutil.copytree(EXAMPLES / "SampleModel.SemanticModel", tmp_path / "SampleModel.SemanticModel")
    shutil.copy(EXAMPLES / "SampleModel.pbip", tmp_path / "SampleModel.pbip")
    return tmp_path


def _run(contract: str, model: Path, out: Path):
    from pql_odcs.api import plan_contract
    from pql_odcs.results import trace
    from pql_test.cli import cli

    result = CliRunner().invoke(
        cli, ["contract", "run", str(FIXTURES / contract), str(model), "--env", "DEV", "--output", str(out)]
    )
    report = trace(plan_contract(FIXTURES / contract), json.loads(out.read_text(encoding="utf-8")))
    return result, {r.rule_id: r.status for r in report.rules}


def test_good_contract_passes_every_mapped_rule(sample_model_copy, tmp_path):
    given = "the good-data SampleModel contract"
    should = "pass every mapped rule and exit 0"

    result, statuses = _run("marvel.odcs.yaml", sample_model_copy, tmp_path / "good.json")

    not_passed = {rid: s for rid, s in statuses.items() if s not in ("passed", "skipped")}
    assert (result.exit_code, not_passed) == (0, {}), f"{given}: {should}\n{result.output}"


def test_must_fail_contract_fails_exactly_the_planted_rules(sample_model_copy, tmp_path):
    given = "the must-fail SampleModel contract"
    should = "fail exactly the planted rules, each traced to its rule id, and exit 1"

    result, statuses = _run("marvel-must-fail.odcs.yaml", sample_model_copy, tmp_path / "fail.json")

    failed = {rid for rid, s in statuses.items() if s == "failed"}
    assert (result.exit_code, failed) == (1, EXPECTED_FAILURES), f"{given}: {should}\n{result.output}"
