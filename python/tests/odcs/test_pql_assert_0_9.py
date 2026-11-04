# SPDX-License-Identifier: AGPL-3.0-only
"""PQL.Assert 0.9 catalog: the native refresh-recency function, and the direct-call version bump."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from pql_test.odcs.api import plan_contract, render
from pql_test.odcs.catalog import catalog_for
from pql_test.odcs.cli import contract as cli
from pql_test.odcs.coverage import build_report
from pql_test.odcs.ir import Status, Target
from tests.odcs.factories import contract_dict, prop, schema_object


def _table(*props, **extra) -> list:
    return [schema_object("T", list(props), **extra)]


def _sla(value=2, unit="d", element="T", prop_name="frequency"):
    return {"property": prop_name, "value": value, "unit": unit, "element": element}


def _outcomes(schema: list, version: str = "0.9", **overrides) -> dict:
    plan = plan_contract(contract_dict(schema=schema, **overrides), pql_assert=version)
    return {o.rule_id: o for o in plan.outcomes}


def _call(outcome):
    a = outcome.assertions[0]
    return a.op, a.target, dict(a.args)


def _rendered(plan) -> str:
    return "".join(f.content for f in render(plan, env="DEV"))


class TestCatalogSelection:
    def test_0_9_inherits_every_0_8_op_and_overrides_one(self):
        given = "the 0.9 catalog"
        should = "keep every 0.8 op, overriding only the refresh-age one"
        old, new = catalog_for("0.8"), catalog_for("0.9")

        assert (set(old.ops) <= set(new.ops), new.min_version, new.op("tbl.refresh_age_at_most").fn) == (
            True,
            "0.9.0",
            "PQL.Assert.Tbl.LastRefreshShouldBeWithinHours",
        ), f"{given}: {should}"

    def test_suite_header_names_the_catalog_version(self):
        given = "a contract rendered with the 0.9 catalog"
        should = "say it targets PQL.Assert >= 0.9.0"
        plan = plan_contract(contract_dict(schema=_table(prop("a"))), pql_assert="0.9")

        assert "targets PQL.Assert >= 0.9.0" in _rendered(plan), f"{given}: {should}"


class TestFrequency:
    def test_frequency_still_approximates_in_its_own_suite(self):
        given = "a frequency SLA of 2 days on table T under 0.9"
        should = "stay approximated (the semantics are the same; only the implementation changed) in RefreshAge"

        outcome = _outcomes(_table(prop("a", "date")), slaProperties=[_sla(2, "d")])["slaProperties[0]"]
        (assertion,) = outcome.assertions

        assert (outcome.status, assertion.suite, _call(outcome)) == (
            Status.APPROXIMATED,
            "RefreshAge",
            ("tbl.refresh_age_at_most", Target("T"), {"maxAgeHours": 48}),
        ), f"{given}: {should}"

    def test_frequency_renders_the_native_refresh_function(self):
        given = "a frequency SLA rendered for PQL.Assert 0.9"
        should = "call Tbl.LastRefreshShouldBeWithinHours(testName, tableName, maxAgeHours) directly, no inline INFO.PARTITIONS()"
        contract = contract_dict(schema=_table(prop("a", "date")), slaProperties=[_sla(3, "h")])

        files = render(plan_contract(contract, pql_assert="0.9"), env="DEV")
        refresh = next(f for f in files if f.suite == "RefreshAge")

        assert (
            refresh.function_name,
            'PQL.Assert.Tbl.LastRefreshShouldBeWithinHours(' in refresh.content,
            '"T", 3)' in refresh.content,
            "INFO.PARTITIONS()" in refresh.content,
        ) == ("MarvelCharacters.RefreshAge.DEV.Tests", True, True, False), f"{given}: {should}\n{refresh.content}"

    def test_frequency_still_skipped_on_0_8(self):
        given = "the same frequency SLA under 0.8"
        should = "keep rendering the 0.8 inline INFO.PARTITIONS() expression (no behavior change)"
        contract = contract_dict(schema=_table(prop("a", "date")), slaProperties=[_sla(3, "h")])

        files = render(plan_contract(contract, pql_assert="0.8"), env="DEV")
        refresh = next(f for f in files if f.suite == "RefreshAge")

        assert (
            "PQL.Assert.ShouldBeLessOrEqual(" in refresh.content,
            "[RefreshedTime]" in refresh.content,
            "Tbl.LastRefreshShouldBeWithinHours" in refresh.content,
        ) == (True, True, False), f"{given}: {should}"


class TestDirectCalls:
    def test_direct_calls_now_need_0_9(self):
        given = "a direct engine: pql-test function call under 0.8"
        should = "be skipped, naming --pql-assert 0.9 (the signatures moved with the vendored library)"
        rule = {
            "type": "custom",
            "engine": "pql-test",
            "implementation": {"function": "PQL.Assert.Col.ShouldBePositive", "args": ["'T'[a]"]},
        }

        plan = plan_contract(contract_dict(schema=[schema_object("T", [prop("a")], quality=[rule])]), pql_assert="0.8")
        outcome = next(o for o in plan.outcomes if o.rule_id == "T.quality[0]")

        assert (outcome.status, "--pql-assert 0.9" in outcome.reason) == (Status.SKIPPED, True), f"{given}: {should}"

    def test_direct_calls_work_on_0_9(self):
        given = "the same direct call under 0.9"
        should = "map"
        rule = {
            "type": "custom",
            "engine": "pql-test",
            "implementation": {"function": "PQL.Assert.Col.ShouldBePositive", "args": ["'T'[a]"]},
        }

        plan = plan_contract(contract_dict(schema=[schema_object("T", [prop("a")], quality=[rule])]), pql_assert="0.9")
        outcome = next(o for o in plan.outcomes if o.rule_id == "T.quality[0]")

        assert outcome.status is Status.MAPPED, f"{given}: {should}"


class TestEveryFixture:
    @pytest.mark.parametrize("name", ["marvel", "marvel-must-fail", "marvel-0-8", "every-row", "rule-coverage"])
    def test_every_mapped_rule_renders_against_0_9(self, name):
        given = f"the {name} fixture planned for PQL.Assert 0.9"
        should = "render every assertion and report each function from the 0.9 catalog"
        path = Path(__file__).resolve().parent / "fixtures" / f"{name}.odcs.yaml"
        plan = plan_contract(path, closed_schema=True, pql_assert="0.9")

        files = render(plan, env="DEV")
        report = build_report(plan.contract, plan.outcomes, catalog=plan.catalog)

        assert (bool(files), len(report["rules"]) == len(plan.outcomes)) == (True, True), f"{given}: {should}"


class TestCli:
    def _run(self, tmp_path, command, *args):
        path = tmp_path / "c.odcs.yaml"
        path.write_text(yaml.safe_dump(contract_dict(schema=_table(prop("a", required=True)))), encoding="utf-8")
        argv = [command, str(path), *args] if command != "generate" else [command, str(path), "model", *args]
        return CliRunner().invoke(cli, argv)

    def test_generate_dry_run_uses_the_0_9_catalog(self, tmp_path):
        given = "generate --dry-run --pql-assert 0.9"
        should = "print 0.8-inherited calls (0.9 only changes the frequency SLA mapping)"

        result = self._run(tmp_path, "generate", "--env", "DEV", "--dry-run", "--pql-assert", "0.9")

        assert "Col.NullCountShouldBeAtMost" in result.output, f"{given}: {should}"

    def test_coverage_json_names_the_0_9_catalog_version(self, tmp_path):
        given = "coverage --format json --pql-assert 0.9"
        should = "report minVersion 0.9.0"

        result = self._run(tmp_path, "coverage", "--format", "json", "--pql-assert", "0.9")

        data = json.loads(result.output)
        assert data["catalog"]["minVersion"] == "0.9.0", f"{given}: {should}"
