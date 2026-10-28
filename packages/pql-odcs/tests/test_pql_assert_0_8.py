# SPDX-License-Identifier: MIT
"""PQL.Assert 0.8 catalog: selection, exact mappings, and the 0.7 fallbacks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner
from factories import contract_dict, prop, schema_object

from pql_odcs.api import plan_contract, render
from pql_odcs.catalog import CatalogError, catalog_for
from pql_odcs.cli import contract as cli
from pql_odcs.coverage import build_report
from pql_odcs.ir import Status, Target


def _outcomes(schema: list, version: str = "0.8", **overrides) -> dict:
    plan = plan_contract(contract_dict(schema=schema, **overrides), pql_assert=version)
    return {o.rule_id: o for o in plan.outcomes}


def _table(*props, **extra) -> list:
    return [schema_object("T", list(props), **extra)]


def _call(outcome):
    a = outcome.assertions[0]
    return a.op, a.target, dict(a.args)


def _column_rule(rule: dict, version: str = "0.8", **prop_extra):
    out = _outcomes(_table(prop("a", quality=[rule], **prop_extra)), version)
    return out["T.a.quality[0]"]


def _rendered(plan) -> str:
    return "".join(f.content for f in render(plan, env="DEV"))


class TestCatalogSelection:
    def test_0_8_inherits_every_0_7_op_and_adds_its_own(self):
        given = "the 0.8 catalog"
        should = "keep all 0.7 ops and add the 0.8 functions"
        old, new = catalog_for("0.7"), catalog_for("0.8")

        assert set(old.ops) < set(new.ops) and new.min_version == "0.8.0", f"{given}: {should}"

    def test_unknown_version_names_the_choices(self):
        given = "an unbundled PQL.Assert version"
        should = "fail with the supported choices"

        with pytest.raises(CatalogError) as exc:
            catalog_for("0.9")

        assert "0.7, 0.8" in str(exc.value), f"{given}: {should}"

    def test_default_plan_targets_0_7(self):
        given = "plan_contract without pql_assert"
        should = "use the 0.7 catalog"

        plan = plan_contract(contract_dict(schema=_table(prop("a"))))

        assert plan.catalog.min_version == "0.7.1", f"{given}: {should}"

    def test_suite_header_names_the_catalog_version(self):
        given = "a contract rendered with the 0.8 catalog"
        should = "say it targets PQL.Assert >= 0.8.0"
        plan = plan_contract(contract_dict(schema=_table(prop("a"))), pql_assert="0.8")

        assert "targets PQL.Assert >= 0.8.0" in _rendered(plan), f"{given}: {should}"


class TestNullsAndKeys:
    def test_required_text_column_is_mapped_to_a_true_null_count(self):
        given = "required: true on a string column under 0.8"
        should = "map exactly to a null count of 0, not approximate"

        outcome = _outcomes(_table(prop("a", required=True)))["T.a.required"]

        assert (outcome.status, _call(outcome)) == (
            Status.MAPPED,
            ("col.null_count_at_most", Target("T", "a"), {"maxCount": 0}),
        ), f"{given}: {should}"

    def test_required_text_column_stays_approximated_on_0_7(self):
        given = "required: true on a string column under 0.7"
        should = "remain approximated"

        outcome = _outcomes(_table(prop("a", required=True)), "0.7")["T.a.required"]

        assert outcome.status is Status.APPROXIMATED, f"{given}: {should}"

    def test_single_primary_key_uses_the_primary_key_check(self):
        given = "primaryKey on one column under 0.8"
        should = "map to col.primary_key"

        outcome = _outcomes(_table(prop("id", primaryKey=True)))["T.id.primaryKey"]

        assert (outcome.status, outcome.assertions[0].op) == (Status.MAPPED, "col.primary_key"), f"{given}: {should}"

    def test_unique_ignores_blanks(self):
        given = "unique: true under 0.8"
        should = "map to the NULL-safe distinct check"

        outcome = _outcomes(_table(prop("a", unique=True)))["T.a.unique"]

        assert (outcome.status, outcome.assertions[0].op) == (
            Status.MAPPED,
            "col.non_null_distinct",
        ), f"{given}: {should}"

    def test_composite_primary_key_is_one_shared_row_distinct_check(self):
        given = "primaryKey on two columns under 0.8"
        should = "map both properties to a single tbl.rows_distinct assertion"

        out = _outcomes(_table(prop("a", primaryKey=True), prop("b", primaryKey=True)))

        first, second = out["T.a.primaryKey"], out["T.b.primaryKey"]
        assert (first.status, second.status, first.assertions == second.assertions) == (
            Status.MAPPED,
            Status.MAPPED,
            True,
        ), f"{given}: {should}"
        assert _call(first) == ("tbl.rows_distinct", Target("T"), {"columns": ["a", "b"]}), f"{given}: {should}"

    def test_composite_primary_key_is_skipped_on_0_7(self):
        given = "a composite primaryKey under 0.7"
        should = "stay skipped"

        out = _outcomes(_table(prop("a", primaryKey=True), prop("b", primaryKey=True)), "0.7")

        assert out["T.a.primaryKey"].status is Status.SKIPPED, f"{given}: {should}"


class TestThresholds:
    @pytest.mark.parametrize(
        "rule, expected",
        [
            ({"metric": "nullValues", "mustBeLessOrEqualTo": 5}, 5),
            ({"metric": "nullValues", "mustBeLessThan": 5}, 4),
            ({"metric": "nullValues", "mustBeLessThan": 5.5}, 5),
        ],
    )
    def test_absolute_null_ceilings_become_a_count(self, rule, expected):
        given = f"nullValues {rule}"
        should = f"map to a null count of at most {expected}"

        outcome = _column_rule(rule)

        assert (_call(outcome)[0], _call(outcome)[2]) == ("col.null_count_at_most", {"maxCount": expected}), (
            f"{given}: {should}"
        )

    @pytest.mark.parametrize(
        "rule",
        [
            {"metric": "nullValues", "mustBe": 3},
            {"metric": "nullValues", "mustBeGreaterThan": 3},
            {"metric": "nullValues", "mustBeLessThan": 0},
        ],
    )
    def test_non_ceiling_null_comparators_stay_skipped(self, rule):
        given = f"nullValues {rule}"
        should = "be skipped with a reason"

        outcome = _column_rule(rule)

        assert (outcome.status, bool(outcome.reason)) == (Status.SKIPPED, True), f"{given}: {should}"

    def test_percent_null_ceiling_uses_the_row_based_rate(self):
        given = "nullValues mustBeLessOrEqualTo 2.5 percent"
        should = "map to the V2 rate with the percentage unchanged"

        outcome = _column_rule({"metric": "nullValues", "mustBeLessOrEqualTo": 2.5, "unit": "percent"})

        assert (_call(outcome)[0], _call(outcome)[2]) == ("col.null_pct_at_most", {"maxPct": 2.5}), f"{given}: {should}"

    def test_percent_above_100_is_skipped(self):
        given = "a percent null ceiling of 150"
        should = "be skipped"

        outcome = _column_rule({"metric": "nullValues", "mustBeLessOrEqualTo": 150, "unit": "percent"})

        assert outcome.status is Status.SKIPPED, f"{given}: {should}"

    def test_null_thresholds_stay_skipped_on_0_7(self):
        given = "an absolute null threshold under 0.7"
        should = "keep the v0.2 skip"

        outcome = _column_rule({"metric": "nullValues", "mustBeLessOrEqualTo": 5}, "0.7")

        assert outcome.status is Status.SKIPPED, f"{given}: {should}"

    def test_duplicate_ceiling_on_a_column(self):
        given = "duplicateValues mustBeLessOrEqualTo 5 on a column"
        should = "map to the duplicate count threshold"

        outcome = _column_rule({"metric": "duplicateValues", "mustBeLessOrEqualTo": 5})

        assert (_call(outcome)[0], _call(outcome)[2]) == ("col.duplicates_at_most", {"maxCount": 5}), (
            f"{given}: {should}"
        )

    def test_zero_duplicates_are_blank_safe_and_exact(self):
        given = "duplicateValues mustBe 0 under 0.8"
        should = "map (not approximate) to the non-null distinct check"

        outcome = _column_rule({"metric": "duplicateValues", "mustBe": 0})

        assert (outcome.status, outcome.assertions[0].op) == (
            Status.MAPPED,
            "col.non_null_distinct",
        ), f"{given}: {should}"

    def test_schema_level_duplicates_over_three_columns(self):
        given = "a schema-level duplicateValues over three properties"
        should = "map to tbl.rows_distinct over the resolved columns in the given order"
        rule = {"metric": "duplicateValues", "mustBe": 0, "arguments": {"properties": ["c", "a", "b"]}}
        renamed = prop("c", customProperties=[{"property": "pbiColumn", "value": "C Col"}])
        schema = [schema_object("T", [prop("a"), prop("b"), renamed], quality=[rule])]

        outcome = _outcomes(schema)["T.quality[0]"]

        assert _call(outcome) == ("tbl.rows_distinct", Target("T"), {"columns": ["C Col", "a", "b"]}), (
            f"{given}: {should}"
        )

    def test_schema_level_duplicates_name_an_unknown_property(self):
        given = "a schema-level duplicateValues naming a missing property"
        should = "be skipped naming it"
        rule = {"metric": "duplicateValues", "mustBe": 0, "arguments": {"properties": ["a", "nope"]}}

        outcome = _outcomes(_table(prop("a"), quality=[rule]))["T.quality[0]"]

        assert (outcome.status, "nope" in outcome.reason) == (Status.SKIPPED, True), f"{given}: {should}"

    def test_row_count_not_between(self):
        given = "rowCount mustNotBeBetween [10, 0]"
        should = "map to tbl.rows_not_between with ordered bounds"
        rule = {"metric": "rowCount", "mustNotBeBetween": [10, 0]}

        outcome = _outcomes(_table(prop("a"), quality=[rule]))["T.quality[0]"]

        assert (_call(outcome)[0], _call(outcome)[2]) == ("tbl.rows_not_between", {"lower": 0, "upper": 10}), (
            f"{given}: {should}"
        )


class TestPatterns:
    @pytest.mark.parametrize(
        "pattern, op",
        [("^ABC", "col.starts_with"), ("ABC$", "col.ends_with"), ("ABC", "col.contains")],
    )
    def test_simple_patterns_map_to_case_sensitive_column_checks(self, pattern, op):
        given = f"an invalidValues pattern {pattern!r}"
        should = f"map exactly to {op}, case-sensitive like the regex"
        rule = {"metric": "invalidValues", "mustBe": 0, "arguments": {"pattern": pattern}}

        outcome = _column_rule(rule)

        assert (outcome.status, _call(outcome)[0], _call(outcome)[2]) == (
            Status.MAPPED,
            op,
            {"text": "ABC", "matchCase": "Y"},
        ), f"{given}: {should}"

    @pytest.mark.parametrize("pattern", ["^A.C", "^ABC$", "a|b", "[a-z]+", "^", "\\d+"])
    def test_other_patterns_stay_skipped_with_a_reason(self, pattern):
        given = f"the regex {pattern!r}"
        should = "be skipped, naming the pattern"
        rule = {"metric": "invalidValues", "mustBe": 0, "arguments": {"pattern": pattern}}

        outcome = _column_rule(rule)

        assert (outcome.status, repr(pattern) in outcome.reason) == (Status.SKIPPED, True), f"{given}: {should}"

    def test_non_zero_pattern_ceiling_stays_skipped(self):
        given = "an invalidValues pattern rule with a ceiling of 3"
        should = "be skipped"
        rule = {"metric": "invalidValues", "mustBeLessOrEqualTo": 3, "arguments": {"pattern": "ABC"}}

        assert _column_rule(rule).status is Status.SKIPPED, f"{given}: {should}"

    def test_pattern_rules_stay_skipped_on_0_7(self):
        given = "a simple pattern under 0.7"
        should = "keep the v0.3 skip"
        rule = {"metric": "invalidValues", "mustBe": 0, "arguments": {"pattern": "ABC"}}

        assert _column_rule(rule, "0.7").status is Status.SKIPPED, f"{given}: {should}"

    def test_property_logical_type_pattern_maps_separately(self):
        given = "a property with logicalTypeOptions pattern and minLength"
        should = "map the pattern, and leave only minLength in the skipped options rule"

        out = _outcomes(_table(prop("a", logicalTypeOptions={"pattern": "^AB", "minLength": 2})))

        assert (out["T.a.pattern"].status, "pattern" in out["T.a.logicalTypeOptions"].reason) == (
            Status.MAPPED,
            False,
        ), f"{given}: {should}"


def _sla(value=2, unit="d", element="T.a", prop_name="latency"):
    return {"property": prop_name, "value": value, "unit": unit, "element": element}


class TestFreshness:
    def test_latency_in_hours_converts_to_days(self):
        given = "a latency SLA of 36 hours on T.a"
        should = "map to a 1.5-day freshness check on T.a"

        outcome = _outcomes(_table(prop("a", "date")), slaProperties=[_sla(36, "h")])["slaProperties[0]"]

        assert (outcome.status, _call(outcome)) == (
            Status.APPROXIMATED,
            ("col.max_date_within_days", Target("T", "a"), {"maxAgeDays": 1.5}),
        ), f"{given}: {should}"

    @pytest.mark.parametrize(
        "sla",
        [
            _sla(prop_name="frequency"),
            _sla(unit="y"),
            _sla(value="soon"),
            _sla(value=-1),
            _sla(element="Nope.a"),
            _sla(element="T.nope"),
            _sla(element="a"),
        ],
    )
    def test_other_slas_stay_skipped_with_a_reason(self, sla):
        given = f"the SLA {sla}"
        should = "be skipped with a reason"

        outcome = _outcomes(_table(prop("a", "date")), slaProperties=[sla])["slaProperties[0]"]

        assert (outcome.status, bool(outcome.reason)) == (Status.SKIPPED, True), f"{given}: {should}"

    def test_slas_stay_skipped_on_0_7(self):
        given = "a latency SLA under 0.7"
        should = "keep the v0.1 skip"

        outcome = _outcomes(_table(prop("a", "date")), "0.7", slaProperties=[_sla()])["slaProperties[0]"]

        assert outcome.status is Status.SKIPPED, f"{given}: {should}"


class TestRendering:
    def test_composite_key_renders_a_selectcolumns_projection(self):
        given = "a composite primary key under 0.8"
        should = "render Tbl.RowsShouldBeDistinct over SELECTCOLUMNS of the key columns"
        schema = _table(prop("a", primaryKey=True), prop("b c", primaryKey=True))
        plan = plan_contract(contract_dict(schema=schema), pql_assert="0.8")

        text = _rendered(plan)

        assert "Tbl.RowsShouldBeDistinct(" in text, f"{given}: {should}"
        assert "SELECTCOLUMNS('T', \"k1\", 'T'[a], \"k2\", 'T'[b c])" in text, f"{given}: {should}"

    def test_every_0_8_op_renders_a_complete_call(self):
        given = "one assertion per 0.8-only mapping"
        should = "render each PQL.Assert 0.8 function"
        schema = [
            schema_object(
                "T",
                [
                    prop("a", required=True, primaryKey=True, unique=True, logicalTypeOptions={"pattern": "x"}),
                    prop("d", "date"),
                ],
                quality=[{"metric": "rowCount", "mustNotBeBetween": [1, 2]}],
            )
        ]
        plan = plan_contract(contract_dict(schema=schema, slaProperties=[_sla(element="T.d")]), pql_assert="0.8")

        text = _rendered(plan)

        for fn in (
            "Col.NullCountShouldBeAtMost",
            "Col.ShouldBePrimaryKey",
            "Col.NonNullValuesShouldBeDistinct",
            "Col.ShouldContainString",
            "ShouldNotBeBetween",
            "Col.MaxDateShouldBeWithinDays",
        ):
            assert fn in text, f"{given}: {should} ({fn})"


class TestEveryFixture:
    @pytest.mark.parametrize("version", ["0.7", "0.8"])
    @pytest.mark.parametrize("name", ["marvel", "marvel-must-fail", "marvel-0-8", "every-row"])
    def test_every_mapped_rule_renders_against_its_catalog(self, name, version):
        given = f"the {name} fixture planned for PQL.Assert {version}"
        should = "render every assertion and report each function from that catalog"
        path = Path(__file__).resolve().parent / "fixtures" / f"{name}.odcs.yaml"
        plan = plan_contract(path, closed_schema=True, pql_assert=version)

        files = render(plan, env="DEV")
        report = build_report(plan.contract, plan.outcomes, catalog=plan.catalog)

        assert (bool(files), len(report["rules"]) == len(plan.outcomes)) == (True, True), f"{given}: {should}"


class TestCli:
    def _run(self, tmp_path, command, *args):
        path = tmp_path / "c.odcs.yaml"
        path.write_text(yaml.safe_dump(contract_dict(schema=_table(prop("a", required=True)))), encoding="utf-8")
        argv = [command, str(path), *args] if command != "generate" else [command, str(path), "model", *args]
        return CliRunner().invoke(cli, argv)

    def test_generate_dry_run_uses_the_chosen_catalog(self, tmp_path):
        given = "generate --dry-run --pql-assert 0.8"
        should = "print 0.8 calls"

        result = self._run(tmp_path, "generate", "--env", "DEV", "--dry-run", "--pql-assert", "0.8")

        assert "Col.NullCountShouldBeAtMost" in result.output, f"{given}: {should}"

    def test_generate_defaults_to_0_7(self, tmp_path):
        given = "generate --dry-run without --pql-assert"
        should = "print the 0.7 null-rate call"

        result = self._run(tmp_path, "generate", "--env", "DEV", "--dry-run")

        assert "Col.NullRateShouldBeAtMost" in result.output, f"{given}: {should}"

    def test_coverage_json_names_the_catalog_version(self, tmp_path):
        given = "coverage --format json --pql-assert 0.8"
        should = "report minVersion 0.8.0 and no approximated rules"

        result = self._run(tmp_path, "coverage", "--format", "json", "--pql-assert", "0.8")

        data = json.loads(result.output)
        assert (data["catalog"]["minVersion"], data["summary"]["approximated"]) == ("0.8.0", 0), f"{given}: {should}"

    def test_unknown_version_is_a_usage_error(self, tmp_path):
        given = "--pql-assert 0.9"
        should = "exit 2"

        result = self._run(tmp_path, "coverage", "--pql-assert", "0.9")

        assert result.exit_code == 2, f"{given}: {should}"
