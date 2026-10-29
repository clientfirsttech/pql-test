# SPDX-License-Identifier: AGPL-3.0-only
"""
Live integration: `pql-test contract run` against examples/SampleModel.

Generates suites from the tests/odcs fixture contracts into a temporary copy of
SampleModel, runs them over XMLA, and checks the traced rule statuses:

  - marvel.odcs.yaml (good data, PQL.Assert 0.7 catalog): every mapped rule passes
  - marvel-must-fail.odcs.yaml (0.7 catalog): exactly the rules in EXPECTED_FAILURES fail
  - marvel-0-8.odcs.yaml (0.8 catalog): every 0.8 op runs, with the outcomes in EXPECTED_0_8

The 0.8 run works on a model that still has an older PQL.Assert: the 0.8.0 functions the
model lacks are defined in each suite's query (see pql_assert_library.py). Separate tests
check that `--pql-assert auto` detects the library the repository commits for each
example model, which fails when the published model is behind the committed one.

Needs either a Power BI Desktop instance with SampleModel open, or the
PQL_TENANT_ID / PQL_WORKSPACE_ID / PQL_DATASET_ID (+ client) service credentials
used by test_live_service.py.
Skipped otherwise.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

# Same credential source as test_live_service.py; real env vars (CI secrets) win.
try:
    from dotenv import load_dotenv

    # python/tests/.env (optional override) first, then python/.env; the first value set wins.
    for _env_file in (Path(__file__).parent / ".env", Path(__file__).parent.parent / ".env"):
        if _env_file.exists():
            load_dotenv(_env_file, override=False)
except ImportError:
    pass

pytestmark = pytest.mark.live

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES = REPO_ROOT / "python" / "tests" / "odcs" / "fixtures"
EXAMPLES = REPO_ROOT / "examples"
SERVICE_VARS = ("PQL_TENANT_ID", "PQL_WORKSPACE_ID")

# Rules in marvel-must-fail.odcs.yaml that must fail against SampleModel's data. These 0.7
# expectations also hold once SampleModel runs PQL.Assert 0.8.0: the 0.7 catalog calls only
# functions whose 0.8.0 changes affect NULL actuals and all-NULL columns, which none of these
# rules involve.
EXPECTED_FAILURES = {
    "marvel_fact_exactly_one_row",  # rowCount mustBe 1
    "DateDim.Year.unique",  # many dates share a year
    "date_dim_fewer_than_one_row",  # rowCount mustBeLessThan 1
    "ghost.exists",  # table NoSuchTable does not exist
    "ghost.columns",  # ...nor its columns
    "ghost.Missing.type",  # ...so its column type cannot match (COLUMN NOT FOUND)
}

# Every mapped rule in marvel-0-8.odcs.yaml. The fixture comments give the SampleModel
# fact behind each outcome; "executed" means no fact is recorded, so passed or failed both do.
EXPECTED_0_8 = {
    "MarvelSource.exists": "passed",
    "MarvelSource.columns": "passed",
    "source_year_null_pct_at_most_5": "passed",
    "source_year_nulls_at_most_815": "passed",
    "source_year_nulls_below_815": "failed",
    "source_eye_ends_with_eyes": "failed",
    "source_eye_starts_with_lowercase": "executed",
    "source_eye_contains_eye": "executed",
    "DateDim.exists": "passed",
    "DateDim.columns": "passed",
    "DateDim.DateID.required": "passed",
    "DateDim.DateID.primaryKey": "passed",
    "DateDim.Year.unique": "failed",
    "date_year_duplicates_at_most_5": "failed",
    "date_year_duplicates_at_most_1000": "passed",
    "date_dim_rows_not_0_to_10": "passed",
    "date_dim_rows_not_1000_to_1100": "failed",
    "marvel_fact.exists": "passed",
    "marvel_fact.columns": "passed",
    "fact_date_eye_alignment_distinct": "failed",
    "slaProperties[0]": "failed",
    # Column types: each logicalType matches the deployed column (INFO.VIEW.COLUMNS, 2026-10-28).
    "MarvelSource.Year.type": "passed",
    "MarvelSource.EYE.type": "passed",
    "DateDim.DateID.type": "passed",
    "DateDim.Year.type": "passed",
    "DateDim.Date.type": "passed",
    "marvel_fact.DateID.type": "passed",
    "marvel_fact.EyeID.type": "passed",
    "marvel_fact.AlignmentID.type": "passed",
}


def _connect(model_dir: Path, dataset_var: str = "PQL_DATASET_ID"):
    """A live XMLA connection to *model_dir*'s deployed dataset (or its open Desktop instance), or None."""
    from pql_test.cli import _make_conn_opts
    from pql_test.runner import HAS_PYADOMD, resolve_xmla_connection

    if not HAS_PYADOMD:
        return None
    service = all(os.environ.get(k, "").strip() for k in (*SERVICE_VARS, dataset_var))
    opts = _make_conn_opts(
        os.environ.get("PQL_TENANT_ID"),
        os.environ.get("PQL_WORKSPACE_ID"),
        os.environ.get(dataset_var) if service else None,
        os.environ.get("PQL_CLIENT_ID"),
        os.environ.get("PQL_CLIENT_SECRET"),
    )
    try:
        return resolve_xmla_connection(str(model_dir.resolve()), opts)
    except Exception:  # noqa: BLE001 - psutil missing, no Desktop running, ...: no connection
        return None


def _connect_deployed(model: str, dataset_var: str):
    """A service XMLA connection to the deployed *model*, never the Desktop fallback; fails the test otherwise."""
    from pql_test.cli import _make_conn_opts
    from pql_test.runner.resolver import _resolve_service_xmla_connection

    opts = _make_conn_opts(
        *(os.environ.get(k) for k in ("PQL_TENANT_ID", "PQL_WORKSPACE_ID", dataset_var, "PQL_CLIENT_ID", "PQL_CLIENT_SECRET"))
    )
    try:
        return _resolve_service_xmla_connection(opts)
    except Exception as exc:  # noqa: BLE001 - an expired secret, a missing dataset, ...: say which
        pytest.fail(f"No XMLA connection to the deployed {model}: {type(exc).__name__}: {exc}")


def _connection_available() -> bool:
    from pql_test.runner import HAS_PYADOMD

    if not HAS_PYADOMD:
        return False
    if all(os.environ.get(k, "").strip() for k in (*SERVICE_VARS, "PQL_DATASET_ID")):
        return True
    try:
        from pql_test.runner import resolve_local_xmla_connection_by_name

        return resolve_local_xmla_connection_by_name("SampleModel") is not None
    except Exception:  # noqa: BLE001 - psutil missing, no Desktop running, ...: just skip
        return False


@pytest.fixture
def sample_model_copy(tmp_path: Path) -> Path:
    """A throwaway copy of the SampleModel PBIP so generated suites never touch examples/."""
    if not _connection_available():
        pytest.skip("No XMLA connection: open SampleModel in Power BI Desktop or set PQL_* service credentials.")
    shutil.copytree(EXAMPLES / "SampleModel.SemanticModel", tmp_path / "SampleModel.SemanticModel")
    shutil.copy(EXAMPLES / "SampleModel.pbip", tmp_path / "SampleModel.pbip")
    return tmp_path


def _run(contract: str, model: Path, out: Path, pql_assert: str):
    from pql_test.odcs.api import plan_contract
    from pql_test.odcs.results import trace
    from pql_test.cli import cli

    args = ["contract", "run", str(FIXTURES / contract), str(model), "--env", "DEV", "--output", str(out)]
    result = CliRunner().invoke(cli, [*args, "--pql-assert", pql_assert])
    assert out.exists(), f"contract run wrote no --output file\n{result.output}"
    report = trace(plan_contract(FIXTURES / contract, pql_assert=pql_assert), json.loads(out.read_text(encoding="utf-8")))
    return result, {r.rule_id: r.status for r in report.rules}


def _committed_catalog(model: str) -> str:
    """The `--pql-assert` catalog matching the PQL.Assert version committed in examples/<model>."""
    from pql_test.odcs.udf import library_versions, model_functions, version_key

    versions = library_versions(model_functions(EXAMPLES / f"{model}.SemanticModel"))
    assert len(versions) == 1, f"examples/{model} mixes PQL.Assert versions: {versions}"
    return "0.8" if version_key(next(iter(versions))) >= (0, 8) else "0.7"


# SampleModel's DataTypes table has one column of each type (INFO.VIEW.COLUMNS, 2026-10-28).
TYPES_CONTRACT = """apiVersion: v3.1.0
kind: DataContract
id: types
version: 1.0.0
status: active
schema:
  - name: DataTypes
    properties:
      - {name: Whole Number, logicalType: integer}
      - {name: Decimal Number, logicalType: number}
      - {name: Currency, logicalType: number}
      - {name: Boolean, logicalType: boolean}
      - {name: Date, logicalType: date}
      - name: Text
        logicalType: number
        customProperties: [{property: pbiDataType, value: Text}]
      - {name: text_as_number, logicalType: number, customProperties: [{property: pbiColumn, value: Text}]}
"""


def test_column_types_accept_either_number_type_and_name_a_mismatch(sample_model_copy, tmp_path):
    given = "type rules for every DataTypes column, including number on Number and Currency columns"
    should = "pass every type check except number on the Text column, which fails"
    contract = tmp_path / "types.odcs.yaml"
    contract.write_text(TYPES_CONTRACT, encoding="utf-8")

    result, statuses = _run(str(contract), sample_model_copy, tmp_path / "types.json", "0.7")

    types = {rid: s for rid, s in statuses.items() if rid.endswith(".type")}
    assert types == {
        "DataTypes.Whole Number.type": "passed",
        "DataTypes.Decimal Number.type": "passed",
        "DataTypes.Currency.type": "passed",
        "DataTypes.Boolean.type": "passed",
        "DataTypes.Date.type": "passed",
        "DataTypes.Text.type": "passed",
        "DataTypes.text_as_number.type": "failed",
    }, f"{given}: {should}\n{result.output}"


def test_good_contract_passes_every_mapped_rule(sample_model_copy, tmp_path):
    given = "the good-data SampleModel contract on the 0.7 catalog"
    should = "pass every mapped rule and exit 0"

    result, statuses = _run("marvel.odcs.yaml", sample_model_copy, tmp_path / "good.json", "0.7")

    not_passed = {rid: s for rid, s in statuses.items() if s not in ("passed", "skipped")}
    assert (result.exit_code, not_passed) == (0, {}), f"{given}: {should}\n{result.output}"


def test_must_fail_contract_fails_exactly_the_planted_rules(sample_model_copy, tmp_path):
    given = "the must-fail SampleModel contract on the 0.7 catalog"
    should = "fail exactly the planted rules, each traced to its rule id, and exit 1"

    result, statuses = _run("marvel-must-fail.odcs.yaml", sample_model_copy, tmp_path / "fail.json", "0.7")

    failed = {rid for rid, s in statuses.items() if s == "failed"}
    assert (result.exit_code, failed) == (1, EXPECTED_FAILURES), f"{given}: {should}\n{result.output}"


def test_0_8_contract_runs_every_op_with_the_pinned_outcomes(sample_model_copy, tmp_path, monkeypatch):
    given = "the PQL.Assert 0.8 SampleModel contract"
    should = "run every 0.8 op (none errored or not executed) with the outcomes in EXPECTED_0_8"
    from pql_test import contract_run
    from pql_test.contract_run import detect_pql_assert
    from pql_test.runner import _execute_dax_query
    from tests.pql_assert_library import load_library, missing_definitions, model_function_names, with_definitions

    conn = _connect(sample_model_copy / "SampleModel.SemanticModel")
    if conn is None:
        pytest.fail("No XMLA connection to SampleModel, although credentials or Desktop were detected.")
    if detect_pql_assert(conn) != "0.8":
        # Older PQL.Assert in the model: define the 0.8.0 functions it lacks in each suite's query.
        library, model_names = load_library(), model_function_names(conn, _execute_dax_query)
        suite_test = contract_run.suite_test

        def suite_test_with_library(suite_file):
            test = suite_test(suite_file)
            test.source = with_definitions(test.source, missing_definitions(test.source, model_names, library))
            return test

        monkeypatch.setattr(contract_run, "suite_test", suite_test_with_library)

    result, statuses = _run("marvel-0-8.odcs.yaml", sample_model_copy, tmp_path / "v08.json", "0.8")

    actual = {
        rid: "executed" if EXPECTED_0_8.get(rid) == "executed" and s in ("passed", "failed") else s
        for rid, s in statuses.items()
        if s != "skipped"
    }
    assert actual == EXPECTED_0_8, f"{given}: {should}\n{result.output}"


@pytest.mark.parametrize("model, dataset_var", [("SampleModel", "PQL_DATASET_ID"), ("RLS_Model", "PQL_DATASET_ID_RLS")])
def test_auto_detection_matches_the_committed_library(model, dataset_var):
    given = f"the deployed {model}"
    from pql_test.contract_run import detect_pql_assert

    expected = _committed_catalog(model)
    should = f"report the PQL.Assert {expected} catalog that examples/{model} commits"
    if not all(os.environ.get(k, "").strip() for k in (*SERVICE_VARS, dataset_var)):
        pytest.skip(f"Set {', '.join(SERVICE_VARS)} and {dataset_var} to check the deployed {model}.")
    from pql_test.runner import _execute_dax_query

    # Service only: a Desktop fallback would check the open .pbip, not the deployed model.
    conn = _connect_deployed(model, dataset_var)
    # A broken connection also reads as "0.7", so prove the connection queries first.
    _execute_dax_query(conn, "EVALUATE { 1 }")

    detected = detect_pql_assert(conn)

    assert detected == expected, (
        f"{given}: {should}, but it reports {detected}. Publish examples/{model} to the workspace "
        "so the deployed library matches the repository."
    )


LIBRARY_SMOKE = [
    # (call, passed, Actual or None). SampleModel facts (docs/pql-assert-gap-plan.md):
    # MarvelSource[Year] has 815 NULL rows of 16,376 (4.98%) and, being an integer column, no "".
    # MarvelSource[GSM] has 16,286 "" rows of 16,376 (99.45%) and no NULL (gap plan C5), so it
    # tells the NULL, blank, and NULL-or-blank rates apart.
    ("Col.NullRateShouldBeAtMostV2(\"t\", 'MarvelSource', 'MarvelSource'[Year], 5)", True, "4.98% (815 of 16376 rows)"),
    ("Col.NullRateShouldBeAtMostV2(\"t\", 'MarvelSource', 'MarvelSource'[Year], 4.9)", False, None),
    ("Col.NullRateShouldBeAtMostV2(\"t\", 'MarvelSource', 'MarvelSource'[GSM], 0)", True, "0% (0 of 16376 rows)"),
    ("Col.BlankRateShouldBeAtMostV2(\"t\", 'MarvelSource', 'MarvelSource'[GSM], 100)", True, "99.45% (16286 of 16376 rows)"),
    ("Col.BlankRateShouldBeAtMostV2(\"t\", 'MarvelSource', 'MarvelSource'[GSM], 99)", False, None),
    ("Col.BlankRateShouldBeAtMostV2(\"t\", 'MarvelSource', 'MarvelSource'[Year], 0)", True, "0% (0 of 16376 rows)"),
    ("Col.NullOrBlankRateShouldBeAtMostV2(\"t\", 'MarvelSource', 'MarvelSource'[GSM], 99)", False, "99.45% (16286 of 16376 rows)"),
    ("Col.NullOrBlankRateShouldBeAtMostV2(\"t\", 'MarvelSource', 'MarvelSource'[Year], 5)", True, "4.98% (815 of 16376 rows)"),
]


@pytest.mark.parametrize("call, passed, actual", LIBRARY_SMOKE)
def test_library_variants_on_sample_model(sample_model_copy, call, passed, actual):
    given = f"PQL.Assert.{call} on SampleModel"
    should = f"{'pass' if passed else 'fail'}" + (f" with Actual {actual!r}" if actual else "")

    ((got_passed, got_actual),) = _library_rows(sample_model_copy, [call])

    assert (got_passed, got_actual if actual else None) == (passed, actual), (
        f"{given}: {should}. If PQL.Assert disagrees with the gap plan's live checks "
        "(docs/pql-assert-gap-plan.md, C2 and C5), the bug is upstream in PQL.Assert."
    )


def test_match_case_makes_text_checks_case_sensitive(sample_model_copy):
    given = 'ShouldEndWith(MarvelSource[EYE], "EYES") with and without matchCase "Y"'
    should = (
        "count fewer non-matching values case-insensitively (most values end with \"Eyes\") than "
        "case-sensitively, where no value matches"
    )
    call = "Col.ShouldEndWith(\"t\", 'MarvelSource'[EYE], \"EYES\"%s)"

    (_, insensitive), (_, sensitive) = _library_rows(sample_model_copy, [call % "", call % ', "Y"'])

    counts = [re.search(r"\((\d+) of (\d+)\)", text) for text in (insensitive, sensitive)]
    assert all(counts), f"{given}: expected NON-MATCHING VALUES (n of N), got {insensitive!r} / {sensitive!r}"
    (bad_i, total_i), (bad_s, total_s) = ((int(m.group(1)), int(m.group(2))) for m in counts)
    assert (bad_i < bad_s, bad_s == total_s) == (True, True), f"{given}: {should} ({insensitive!r} / {sensitive!r})"


def _library_rows(model_copy: Path, calls: list[str]) -> list[tuple[bool, str]]:
    """``(Passed, Actual)`` for each PQL.Assert call, defining 0.8.0 functions the model lacks."""
    from pql_test.contract_run import detect_pql_assert
    from pql_test.runner import _execute_dax_query
    from tests.pql_assert_library import field, load_library, missing_definitions, model_function_names, with_definitions

    conn = _connect(model_copy / "SampleModel.SemanticModel")
    if conn is None:
        pytest.fail("No XMLA connection to SampleModel, although credentials or Desktop were detected.")
    library = load_library()
    model_names = set(library) if detect_pql_assert(conn) == "0.8" else model_function_names(conn, _execute_dax_query)
    out = []
    for call in calls:
        query = f"EVALUATE PQL.Assert.{call}"
        rows = _execute_dax_query(conn, with_definitions(query, missing_definitions(query, model_names, library)))
        out.append((bool(field(rows[0], "Passed")), str(field(rows[0], "Actual"))))
    return out
