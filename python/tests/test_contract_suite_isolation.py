# SPDX-License-Identifier: AGPL-3.0-only
"""A suite that fails to run is re-run one call at a time (tasks/contract-suite-error-isolation-epic.md).

The XMLA runner is stubbed: a query whose text contains ``[Bad]`` fails as a whole, the way
Analysis Services rejects a query when one expression in it cannot run; any other query
returns one passing row per assertion it calls.
"""

from __future__ import annotations

import json
import re
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from pql_test.runner import TestResult

CONTRACT = """\
apiVersion: v3.1.0
kind: DataContract
id: c
version: '1'
status: active
schema:
  - name: T
    properties:
      - name: a
        logicalType: integer
    quality:
{rules}
"""
RULE = """\
      - id: {id}
        type: custom
        engine: pql-test
        implementation:
          expression: '{expression}'
          mustBeGreaterThan: 0
"""
_CALL = re.compile(r'PQL\.Assert[\w.]*\("((?:[^"]|"")*)"')


def _contract(tmp_path, **rules: str):
    path = tmp_path / "c.odcs.yaml"
    body = "".join(RULE.format(id=rule_id, expression=expression) for rule_id, expression in rules.items())
    path.write_text(CONTRACT.format(rules=body), encoding="utf-8")
    model = tmp_path / "M.SemanticModel"
    (model / "definition").mkdir(parents=True)
    return path, model


def _fake_engine(queries: list[str]):
    def run(tests, *_a, **_k):
        results = []
        for t in tests:
            queries.append(t.source)
            if "[Bad]" in t.source:
                error = "Cannot convert value 'Test' of type Text to type Number."
                results.append(TestResult(t.name, False, "Test execution failed", error=error, suite_name=t.name))
                continue
            for name in _CALL.findall(t.source):
                results.append(TestResult(name.replace('""', '"'), True, "", suite_name=t.name))
        return results

    return run


@pytest.fixture
def queries(monkeypatch):
    """A connected model on PQL.Assert 0.9.0 whose queries go to the fake engine; collects every query."""
    sent: list[str] = []
    monkeypatch.setattr("pql_test.contract_run.xmla_unavailable", lambda: None)
    monkeypatch.delenv("PQL_DATASET_ID", raising=False)
    monkeypatch.setattr("pql_test.contract_run.resolve_xmla_connection", lambda *_a, **_k: SimpleNamespace(server="s", catalog="c"))
    monkeypatch.setattr("pql_test.contract_run.deployed_library_version", lambda _conn: "0.9.0")
    monkeypatch.setattr("pql_test.contract_run.run_tests", _fake_engine(sent))
    return sent


def _rules(contract, model) -> dict[str, str]:
    from pql_test.cli import cli

    result = CliRunner().invoke(cli, ["contract", "run", str(contract), str(model), "--env", "DEV", "--format", "json"])
    payload = json.loads(result.stdout)
    return {r["ruleId"]: r["status"] for r in payload["contract"]["rules"]}


class TestFailedSuiteIsRerunCallByCall:
    def test_error_lands_on_the_rule_that_has_it(self, tmp_path, queries):
        given = "a contract DAX suite whose second call cannot run"
        should = "report the error on that rule only, and the other rule's real result"
        contract, model = _contract(tmp_path, good="[Good]", bad="[Bad]")

        rules = _rules(contract, model)

        assert (rules["good"], rules["bad"]) == ("passed", "error"), f"{given}: {should}: {rules}"

    def test_a_suite_of_one_call_is_not_run_again(self, tmp_path, queries):
        given = "a contract DAX suite of one call that cannot run"
        should = "report the error on its rule and send no second query for it"
        contract, model = _contract(tmp_path, bad="[Bad]")

        rules = _rules(contract, model)

        assert (rules["bad"], sum("[Bad]" in q for q in queries)) == ("error", 1), f"{given}: {should}"

    def test_suites_that_run_are_not_run_again(self, tmp_path, queries):
        given = "every suite running"
        should = "send one query per suite"
        contract, model = _contract(tmp_path, good="[Good]", other="[Other]")

        _rules(contract, model)

        assert len(queries) == 2, f"{given}: {should}: {queries}"
