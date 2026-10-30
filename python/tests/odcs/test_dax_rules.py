# SPDX-License-Identifier: AGPL-3.0-only
"""``type: custom``, ``engine: pql-test`` rules: DAX written in the contract."""

from __future__ import annotations

import pytest
import yaml
from click.testing import CliRunner

from pql_test.odcs.api import plan_contract, render
from pql_test.odcs.cli import contract as cli
from pql_test.odcs.coverage import build_report, format_text
from pql_test.odcs.ir import Status
from pql_test.odcs.mapping.dax_rules import dax_problem
from tests.odcs.factories import contract_dict, prop, schema_object

MEASURE = "CALCULATE([Number of Characters], FILTER(ALL('DateDim'), 'DateDim'[Year] = -1))"


def _rule(implementation, **extra) -> dict:
    return {"type": "custom", "engine": "pql-test", "implementation": implementation, **extra}


def _plan(*rules, version: str = "0.8"):
    schema = [schema_object("T", [prop("a")], quality=list(rules))]
    return plan_contract(contract_dict(schema=schema), pql_assert=version)


def _outcome(rule, version: str = "0.8"):
    return _plan(rule, version=version).outcomes[-1]


def _dax(*rules, version: str = "0.8") -> str:
    return "".join(f.content for f in render(_plan(*rules, version=version), env="DEV"))


class TestExpressionForm:
    @pytest.mark.parametrize(
        ("comparator", "op", "args"),
        [
            ({"mustBe": 0}, "dax.equal", {"expected": 0}),
            ({"mustBe": "Open"}, "dax.equal_exactly", {"expected": "Open"}),
            ({"mustBe": True}, "dax.equal", {"expected": True}),
            ({"mustNotBe": 0}, "dax.not_equal", {"expected": 0}),
            ({"mustBeGreaterThan": 1000}, "dax.gt", {"threshold": 1000}),
            ({"mustBeLessOrEqualTo": 5}, "dax.le", {"threshold": 5}),
            ({"mustBeBetween": [10, 1]}, "dax.between", {"lower": 1, "upper": 10}),
            ({"mustNotBeBetween": [1, 2]}, "dax.not_between", {"lower": 1, "upper": 2}),
        ],
    )
    def test_comparators_map_to_scalar_assertions(self, comparator, op, args):
        given = f"an expression with {comparator}"
        should = f"map to {op} with {args}, marked as contract DAX"

        outcome = _outcome(_rule({"expression": MEASURE, **comparator}))
        a = outcome.assertions[0]

        assert (outcome.status, outcome.source, a.op, dict(a.args)) == (
            Status.MAPPED,
            "contract-dax",
            op,
            {**args, "expression": MEASURE},
        ), f"{given}: {should}"

    def test_case_sensitive_inequality_is_approximated(self):
        given = "mustNotBe with a text value"
        should = "be approximated, because ShouldNotEqual compares text without regard to case"

        outcome = _outcome(_rule({"expression": "[Status]", "mustNotBe": "Closed"}))

        assert outcome.status is Status.APPROXIMATED, f"{given}: {should}"

    def test_expression_rules_work_on_0_7(self):
        given = "an expression rule under the 0.7 catalog"
        should = "map, because the scalar assertions predate 0.7.1"

        outcome = _outcome(_rule({"expression": MEASURE, "mustBe": 0}), version="0.7")

        assert outcome.status is Status.MAPPED, f"{given}: {should}"

    @pytest.mark.parametrize(
        ("comparator", "status"),
        [
            ({"mustBeLessThan": 10}, Status.APPROXIMATED),
            ({"mustBeBetween": [1, 2]}, Status.APPROXIMATED),
            ({"mustBe": "Open"}, Status.APPROXIMATED),
            ({"mustBe": 0}, Status.MAPPED),
        ],
    )
    def test_0_7_comparisons_that_pass_on_blank_are_approximated(self, comparator, status):
        given = f"{comparator} on an expression under the 0.7 catalog"
        should = f"be {status.value}: 0.7 compares a BLANK result as 0 or an empty string, except in ShouldEqual"

        outcome = _outcome(_rule({"expression": "BLANK()", **comparator}), version="0.7")

        assert outcome.status is status, f"{given}: {should}"

    @pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
    def test_non_finite_values_are_skipped(self, value):
        given = f"a comparator value of {value}"
        should = "be skipped, because DAX has no literal for it"

        outcome = _outcome(_rule({"expression": "1", "mustBeGreaterThan": value}))

        assert (outcome.status, "finite" in outcome.reason) == (Status.SKIPPED, True), f"{given}: {should}"

    def test_not_between_needs_0_8(self):
        given = "mustNotBeBetween on an expression under the 0.7 catalog"
        should = "be skipped, naming --pql-assert 0.8"

        outcome = _outcome(_rule({"expression": "1", "mustNotBeBetween": [1, 2]}), version="0.7")

        assert "--pql-assert 0.8" in outcome.reason, f"{given}: {should}"

    def test_renders_the_expression_unchanged(self):
        given = "the sample model's 'returns 0, not blank' scenario"
        should = "render ShouldEqual with the contract's DAX as the actual value"
        rule = _rule({"expression": MEASURE, "mustBe": 0}, description="Zero, not blank, for a year with no data")

        assert (
            'PQL.Assert.ShouldEqual("ODCS marvel-contract T.quality[0]: Zero, not blank, for a year with no data", '
            f"0, {MEASURE})" in _dax(rule)
        ), f"{given}: {should}"

    def test_a_final_line_comment_cannot_swallow_the_call(self):
        given = "an expression ending in a // comment"
        should = "end the expression's line, so the closing parenthesis is on the next line"

        text = _dax(_rule({"expression": "[Total] // the measure", "mustBe": 1}))

        assert "[Total] // the measure\n\t\t\t)" in text, f"{given}: {should}"

    @pytest.mark.parametrize(
        "implementation",
        [
            {"expression": "1"},
            {"expression": "1", "mustBe": 1, "mustNotBe": 2},
            {"expression": "", "mustBe": 1},
            {"expression": "1", "mustBeGreaterThan": "big"},
            {"expression": "1", "mustBeBetween": [1]},
            {"expression": "1", "function": "PQL.Assert.ShouldBeTrue", "mustBe": 1},
            "not a mapping",
        ],
    )
    def test_malformed_rules_are_skipped(self, implementation):
        given = f"implementation {implementation!r}"
        should = "be skipped with a reason, still marked as contract DAX"

        outcome = _outcome(_rule(implementation))

        assert (outcome.status, bool(outcome.reason), outcome.source) == (
            Status.SKIPPED,
            True,
            "contract-dax",
        ), f"{given}: {should}"


class TestDaxProblem:
    @pytest.mark.parametrize(
        "text",
        [
            MEASURE,
            'IF([A] > 0, "EVALUATE, DEFINE", BLANK())',
            "'Define Table'[Evaluate Column]",
            "[A] /* EVALUATE (, */ + 1",
            "SUMX({1, 2}, [Value])",
            '"say ""hi""" & \'it\'\'s\'[x]',
        ],
    )
    def test_one_expression_passes(self, text):
        given = f"the expression {text!r}"
        should = "have no problem (keywords and brackets inside literals and comments do not count)"

        assert dax_problem(text) is None, f"{given}: {should}"

    @pytest.mark.parametrize(
        ("text", "problem"),
        [
            ('EVALUATE ROW("x", 1)', "EVALUATE"),
            ("DEFINE VAR x = 1", "DEFINE"),
            ("SUM('T'[a]", "unclosed ("),
            ("SUM('T'[a]))", "unbalanced )"),
            ("1, 2", "top-level comma"),
            ('"open', 'unterminated "'),
            ("[A] /* never closed", "unterminated /*"),
            ("(1}", "unbalanced }"),
            ("1 ]", "unbalanced ]"),
            ('1 // c\r), PQL.Assert.ShouldEqual("fake", 1, 1', "control character (U+000D)"),
            ("1 // c\u2028+ 2", "control character (U+2028)"),
            ("1 + \x00 2", "control character (U+0000)"),
        ],
    )
    def test_text_that_would_break_the_suite_is_rejected(self, text, problem):
        given = f"the expression {text!r}"
        should = f"be rejected for {problem}"

        assert problem in (dax_problem(text) or ""), f"{given}: {should}"


class TestFunctionForm:
    def test_call_renders_with_test_name_first(self):
        given = "a direct call of Col.MeanShouldBeInRange"
        should = "render the call with the generated test name, then the contract's arguments"
        rule = _rule({"function": "PQL.Assert.Col.MeanShouldBeInRange", "args": ["'T'[a]", 0, 2.5]})

        assert (
            'PQL.Assert.Col.MeanShouldBeInRange("ODCS marvel-contract T.quality[0]: T PQL.Assert.Col.MeanShouldBeInRange", '
            "'T'[a], 0, 2.5)" in _dax(rule)
        ), f"{given}: {should}"

    def test_optional_arguments_may_be_left_out(self):
        given = "Col.ShouldStartWith without its optional matchCase"
        should = "map"

        outcome = _outcome(_rule({"function": "PQL.Assert.Col.ShouldStartWith", "args": ["'T'[a]", '"AB"']}))

        assert outcome.status is Status.MAPPED, f"{given}: {should}"

    @pytest.mark.parametrize(
        ("implementation", "reason"),
        [
            ({"function": "PQL.Assert.Col.NoSuchCheck", "args": []}, "is not a PQL.Assert function"),
            ({"function": "PQL.Assert.BP.CheckPerformance", "args": []}, "is not an assertion a contract can call"),
            ({"function": "PQL.Assert.RetrieveTests", "args": []}, "is not an assertion a contract can call"),
            (
                {"function": "PQL.Assert.Col.ShouldBePositive", "args": []},
                "takes 2-2 arguments including testName, got 1",
            ),
            ({"function": "PQL.Assert.Col.ShouldBePositive", "args": ["EVALUATE 1"]}, "args[0] has EVALUATE"),
            ({"function": "PQL.Assert.Col.ShouldBePositive", "args": [None]}, "args[0] must be DAX text"),
            ({"function": "PQL.Assert.Col.ShouldBePositive", "args": "'T'[a]"}, "args needs a list"),
            ({"function": ["PQL.Assert.Col.ShouldBePositive"], "args": []}, "needs a PQL.Assert function name"),
            ({"function": "PQL.Assert.Col.ShouldBeInRange", "args": ["'T'[a]", 0, float("nan")]}, "finite number"),
        ],
    )
    def test_invalid_calls_are_skipped(self, implementation, reason):
        given = f"implementation {implementation}"
        should = f"be skipped because it {reason}"

        outcome = _outcome(_rule(implementation))

        assert (outcome.status, reason in outcome.reason) == (Status.SKIPPED, True), f"{given}: {should}"

    def test_direct_calls_need_0_8(self):
        given = "a direct call under the 0.7 catalog"
        should = "be skipped, naming --pql-assert 0.8"

        outcome = _outcome(_rule({"function": "PQL.Assert.Col.ShouldBePositive", "args": ["'T'[a]"]}), version="0.7")

        assert "--pql-assert 0.8" in outcome.reason, f"{given}: {should}"


class TestReporting:
    def test_other_engines_keep_their_skip(self):
        given = "a type: custom rule for soda"
        should = "stay skipped with the custom-engine reason and no contract-DAX marker"
        rule = {"type": "custom", "engine": "soda", "implementation": "checks for T: [row_count > 0]"}

        outcome = _outcome(rule)

        assert (outcome.status, "their own engine" in outcome.reason, outcome.source) == (
            Status.SKIPPED,
            True,
            None,
        ), f"{given}: {should}"

    def test_coverage_marks_contract_dax(self):
        given = "a mapped contract-DAX rule"
        should = "stay status mapped, with source contract-dax in JSON and a marker in text"
        plan = _plan(_rule({"expression": "1", "mustBe": 1}))

        report = build_report(plan.contract, plan.outcomes, catalog=plan.catalog)
        rule = report["rules"][-1]

        assert (rule["status"], rule["source"], "(contract DAX)" in format_text(report)) == (
            "mapped",
            "contract-dax",
            True,
        ), f"{given}: {should}"

    def test_translated_rules_have_no_source_key(self):
        given = "a rule pql-test translated"
        should = "have no source key, so existing coverage JSON is unchanged"
        plan = _plan({"metric": "rowCount", "mustBeGreaterThan": 0})

        report = build_report(plan.contract, plan.outcomes, catalog=plan.catalog)

        assert "source" not in report["rules"][-1], f"{given}: {should}"

    def test_contract_dax_runs_in_its_own_suite(self):
        given = "a contract-DAX rule next to a translated rule"
        should = "render in the ContractDax suite, so its mistakes cannot error the translated rules"
        plan = _plan(_rule({"expression": "1", "mustBe": 1}), {"metric": "rowCount", "mustBeGreaterThan": 0})

        suites = {f.function_name: f.content for f in render(plan, env="DEV")}

        assert (
            "ShouldEqual" in suites["MarvelCharacters.ContractDax.DEV.Tests"],
            "ShouldEqual" in suites["MarvelCharacters.DataQuality.DEV.Tests"],
        ) == (True, False), f"{given}: {should}"

    def test_warning_rules_go_to_the_warn_suite(self):
        given = "a contract-DAX rule with severity warning"
        should = "render in the ContractDax WARN suite"

        files = render(_plan(_rule({"expression": "1", "mustBe": 1}, severity="warning")), env="DEV")

        assert [f.function_name for f in files if "ShouldEqual" in f.content] == [
            "MarvelCharacters.ContractDax.DEVWARN.Tests"
        ], f"{given}: {should}"

    def test_lint_reports_a_broken_dax_rule(self, tmp_path):
        given = "a contract with an engine: pql-test rule whose DAX has a top-level comma"
        should = "fail lint and name the rule"
        schema = [schema_object("T", [prop("a")], quality=[_rule({"expression": "1, 2", "mustBe": 1})])]
        path = tmp_path / "c.odcs.yaml"
        path.write_text(yaml.safe_dump(contract_dict(schema=schema), sort_keys=False), encoding="utf-8")

        result = CliRunner().invoke(cli, ["lint", str(path)])

        assert (result.exit_code, "T.quality[0]: implementation.expression has a top-level comma" in result.output) == (
            1,
            True,
        ), f"{given}: {should}\n{result.output}"
