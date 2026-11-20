# SPDX-License-Identifier: AGPL-3.0-only
"""Relationship settings: cardinality, cross-filter direction, active, security filter (tasks/relationship-settings-epic.md)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from pql_test.odcs.api import plan_contract, render
from pql_test.odcs.ir import Status
from tests.odcs.factories import contract_dict, custom, prop, schema_object

REPO = Path(__file__).resolve().parents[3]
CODE_COVERAGE = REPO / "examples" / "CodeCoverage.SemanticModel"
RULE = "orders.customer_id.relationships[0]"
ENDS = {"fromTable": "Orders", "fromColumn": "CustomerKey", "toTable": "Customer", "toColumn": "id"}


def _schema(**settings) -> list:
    relationship = {"to": "customers.id"}
    if settings:
        relationship["customProperties"] = custom(**settings)
    fk = prop("customer_id", "integer", customProperties=custom(pbiColumn="CustomerKey"), relationships=[relationship])
    orders = schema_object("orders", [fk], customProperties=custom(pbiTable="Orders"))
    customers = schema_object("customers", [prop("id", "integer")], customProperties=custom(pbiTable="Customer"))
    return [orders, customers]


def _outcome(version: str = "0.9.1", **settings):
    plan = plan_contract(contract_dict(schema=_schema(**settings)), pql_assert=version)
    return next(o for o in plan.outcomes if o.rule_id == RULE)


def _call(outcome) -> tuple[str, dict]:
    (a,) = outcome.assertions
    return a.op, dict(a.args)


class TestMappingOnPqlAssert091:
    def test_every_setting_goes_to_one_call(self):
        given = "a relationship pinning all four settings, under --pql-assert 0.9.1"
        should = "pass each one to ShouldExist with its TMDL name"

        outcome = _outcome(
            pbiCardinality="manyToOne",
            pbiCrossFilteringBehavior="both",
            pbiIsActive=True,
            pbiSecurityFilteringBehavior="oneDirection",
        )

        assert (outcome.status, _call(outcome)) == (
            Status.MAPPED,
            (
                "rel.settings",
                {
                    **ENDS,
                    "fromCardinality": "Many",
                    "toCardinality": "One",
                    "securityFilteringBehavior": "OneDirection",
                    "crossFilteringBehavior": "BothDirections",
                    "isActive": "TRUE",
                },
            ),
        ), f"{given}: {should}"

    def test_unstated_settings_are_passed_empty(self):
        given = "a relationship pinning only cross-filter single"
        should = "pass OneDirection and an empty string for every other setting, so ShouldExist skips them"

        outcome = _outcome(pbiCrossFilteringBehavior="single")

        assert _call(outcome)[1] == {
            **ENDS,
            "fromCardinality": "",
            "toCardinality": "",
            "securityFilteringBehavior": "",
            "crossFilteringBehavior": "OneDirection",
            "isActive": "",
        }, f"{given}: {should}"

    @pytest.mark.parametrize(
        ("settings", "expected"),
        [
            ({"pbiCardinality": "OneToMany"}, {"fromCardinality": "One", "toCardinality": "Many"}),
            ({"pbiCardinality": "oneToOne"}, {"fromCardinality": "One", "toCardinality": "One"}),
            ({"pbiCardinality": "manytomany"}, {"fromCardinality": "Many", "toCardinality": "Many"}),
            ({"pbiCrossFilteringBehavior": "BothDirections"}, {"crossFilteringBehavior": "BothDirections"}),
            ({"pbiCrossFilteringBehavior": "automatic"}, {"crossFilteringBehavior": "Automatic"}),
            ({"pbiIsActive": "false"}, {"isActive": "FALSE"}),
            ({"pbiIsActive": False}, {"isActive": "FALSE"}),
            ({"pbiSecurityFilteringBehavior": "none"}, {"securityFilteringBehavior": "None"}),
            ({"pbiSecurityFilteringBehavior": "BOTHDIRECTIONS"}, {"securityFilteringBehavior": "BothDirections"}),
        ],
    )
    def test_values_in_any_case_become_tmdl_names(self, settings, expected):
        given = f"a relationship with {settings}"
        should = f"pass {expected}"

        args = _call(_outcome(**settings))[1]

        assert {k: args[k] for k in expected} == expected, f"{given}: {should}"

    def test_no_settings_generate_what_they_did_before(self):
        given = "a relationship without settings, under --pql-assert 0.9.1"
        should = "map to the four-end existence check, as before this epic"

        outcome = _outcome()

        assert (outcome.status, _call(outcome)) == (Status.MAPPED, ("rel.exists", ENDS)), f"{given}: {should}"

    def test_rendered_call_passes_ten_arguments(self):
        given = "a relationship pinning cross-filter both, rendered for --pql-assert 0.9.1"
        should = "call ShouldExist with empty strings for the unstated settings, in argument order"
        plan = plan_contract(contract_dict(schema=_schema(pbiCrossFilteringBehavior="both")), pql_assert="0.9.1")

        dax = "".join(f.content for f in render(plan, env="DEV"))

        assert '"Orders", "CustomerKey", "Customer", "id", "", "", "", "BothDirections", "")' in dax, (
            f"{given}: {should}\n{dax}"
        )

    def test_rendering_is_byte_identical(self):
        given = "the same contract with settings, rendered twice"
        should = "produce identical suites"
        contract = contract_dict(schema=_schema(pbiCardinality="manyToOne", pbiIsActive="true"))

        first, second = (
            [f.content for f in render(plan_contract(contract, pql_assert="0.9.1"), env="DEV")] for _ in range(2)
        )

        assert first == second, f"{given}: {should}"


class TestMappingOnOlderPqlAssert:
    @pytest.mark.parametrize("version", ["0.8", "0.9"])
    def test_cardinality_and_security_filter_are_still_checked(self, version):
        given = f"cardinality and security filter bothDirections under --pql-assert {version}"
        should = "pass them to ShouldExist's eight arguments and map the rule"

        outcome = _outcome(version, pbiCardinality="oneToOne", pbiSecurityFilteringBehavior="bothDirections")

        assert (outcome.status, _call(outcome)) == (
            Status.MAPPED,
            (
                "rel.settings",
                {**ENDS, "fromCardinality": "One", "toCardinality": "One", "securityFilteringBehavior": "BothDirections"},
            ),
        ), f"{given}: {should}"

    def test_settings_the_library_cannot_check_are_named(self):
        given = "cardinality, cross-filter, and active under --pql-assert 0.9"
        should = "check cardinality, and approximate the rule naming the two settings that need 0.9.1"

        outcome = _outcome("0.9", pbiCardinality="manyToOne", pbiCrossFilteringBehavior="both", pbiIsActive="true")

        assert (
            outcome.status,
            _call(outcome)[1]["fromCardinality"],
            "pbiCrossFilteringBehavior" in outcome.reason,
            "pbiIsActive" in outcome.reason,
            "pbiCardinality" in outcome.reason,
            "--pql-assert 0.9.1" in outcome.reason,
        ) == (Status.APPROXIMATED, "Many", True, True, False, True), f"{given}: {should}\n{outcome.reason}"

    def test_security_filter_none_needs_0_9_1(self):
        given = "pbiSecurityFilteringBehavior: none under --pql-assert 0.9 (0.9.0 reports it as Unknown)"
        should = "check existence only and approximate the rule, naming the none value"

        outcome = _outcome("0.9", pbiSecurityFilteringBehavior="none")

        assert (outcome.status, _call(outcome), "pbiSecurityFilteringBehavior: none" in outcome.reason) == (
            Status.APPROXIMATED,
            ("rel.exists", ENDS),
            True,
        ), f"{given}: {should}\n{outcome.reason}"

    def test_0_7_keeps_skipping(self):
        given = "a relationship with settings under --pql-assert 0.7"
        should = "stay skipped, as every 0.7 relationship is"

        outcome = _outcome("0.7", pbiCardinality="manyToOne")

        assert outcome.status is Status.SKIPPED, f"{given}: {should}"


class TestInvalidSettings:
    @pytest.mark.parametrize(
        ("settings", "says"),
        [
            ({"pbiCardinality": "many"}, "pbiCardinality"),
            ({"pbiCrossFilteringBehavior": "sideways"}, "pbiCrossFilteringBehavior"),
            ({"pbiIsActive": "yes"}, "pbiIsActive"),
            ({"pbiSecurityFilteringBehavior": "single"}, "pbiSecurityFilteringBehavior"),
            ({"pbiSecurityFilteringBehavior": "both"}, "pbiSecurityFilteringBehavior"),
            ({"pbiCrossFilter": "both"}, "pbiCrossFilter"),
        ],
    )
    def test_a_bad_setting_skips_the_rule(self, settings, says):
        given = f"a relationship with {settings}"
        should = "skip the rule with a reason naming the property, rather than check less than the contract says"

        outcome = _outcome(**settings)

        assert (outcome.status, outcome.reason.startswith(says)) == (Status.SKIPPED, True), (
            f"{given}: {should}\n{outcome.reason}"
        )

    def test_lint_reports_a_bad_setting(self, tmp_path):
        given = "lint on a contract whose relationship says pbiSecurityFilteringBehavior: single"
        should = "report it as a problem and exit 1"
        from pql_test.cli import cli

        path = tmp_path / "c.odcs.yaml"
        path.write_text(
            yaml.safe_dump(contract_dict(schema=_schema(pbiSecurityFilteringBehavior="single"))), encoding="utf-8"
        )

        result = CliRunner().invoke(cli, ["contract", "lint", str(path), "--format", "json"])

        problems = json.loads(result.stdout)["problems"]
        assert (result.exit_code, any(p.startswith(f"{RULE}: pbiSecurityFilteringBehavior") for p in problems)) == (
            1,
            True,
        ), f"{given}: {should}\n{problems}"


class TestCatalogSelection:
    @pytest.mark.parametrize(
        ("reported", "catalog"),
        [("0.9.1", "0.9.1"), ("0.9.0", "0.9"), ("0.9.2", "0.9.1"), ("0.10.0", "0.9.1"), ("0.8.0", "0.8")],
    )
    def test_auto_follows_library_version(self, reported, catalog):
        given = f"a connected model reporting PQL.Assert {reported}"
        should = f"select the {catalog} catalog"
        from pql_test.contract_run import _catalog_for_version

        assert _catalog_for_version(reported) == catalog, f"{given}: {should}"

    def test_0_9_0_is_told_pql_test_supports_0_9_1(self):
        given = "a deployed model on PQL.Assert 0.9.0, run with the 0.9 catalog"
        should = "warn that pql-test supports up to 0.9.1"
        from pql_test.contract_run import pql_assert_version_warning

        warning = pql_assert_version_warning("0.9.0", "0.9")

        assert "supports up to 0.9.1" in (warning or ""), f"{given}: {should}\n{warning}"

    def test_0_9_1_catalog_on_a_0_9_0_model_warns(self):
        given = "--pql-assert 0.9.1 against a model on PQL.Assert 0.9.0"
        should = "warn that the suites call what the model lacks"
        from pql_test.contract_run import pql_assert_version_warning

        warning = pql_assert_version_warning("0.9.0", "0.9.1")

        assert "--pql-assert 0.9.1 needs PQL.Assert 0.9.1" in (warning or ""), f"{given}: {should}\n{warning}"

    @staticmethod
    def _library(should_exist_params: int) -> list:
        """Every function the 0.9.1 catalog calls, with ShouldExist cut to *should_exist_params* parameters."""
        from pql_test.odcs.catalog import load_catalog
        from pql_test.odcs.udf import parse_functions

        names = sorted({spec.fn for spec in load_catalog("pql_assert_0_9_1").ops.values()})
        tmdl = ""
        for name in names:
            count = should_exist_params if name == "PQL.Assert.Relationship.ShouldExist" else 12
            params = ", ".join(f"p{i} : STRING" for i in range(count))
            tmdl += f"function '{name}' =\n\t\t({params}) => 1\n"
        return parse_functions(tmdl)

    @pytest.mark.parametrize(("params", "recommended"), [(10, "0.9.1"), (8, "0.9")])
    def test_doctor_counts_parameters(self, params, recommended):
        given = f"a model folder whose Relationship.ShouldExist takes {params} parameters"
        should = f"recommend --pql-assert {recommended}"
        from pql_test.odcs.doctor import recommend_catalog

        choice, missing = recommend_catalog(self._library(params))

        assert choice == recommended, f"{given}: {should}\n{missing}"

    def test_doctor_names_the_function_that_is_too_old(self):
        given = "a model folder whose Relationship.ShouldExist takes 8 parameters"
        should = "say the 0.9.1 catalog needs a newer Relationship.ShouldExist"
        from pql_test.odcs.doctor import recommend_catalog

        _, missing = recommend_catalog(self._library(8))

        assert [m for m in missing["0.9.1"] if "Relationship.ShouldExist" in m and "8" in m], f"{given}: {should}"

    def test_code_coverage_folder_recommends_0_9_1(self):
        given = "examples/CodeCoverage (PQL.Assert 0.9.1)"
        should = "recommend --pql-assert 0.9.1"
        from pql_test.odcs.doctor import run_doctor

        assert run_doctor(CODE_COVERAGE).recommended == "0.9.1", f"{given}: {should}"


class TestModelSettings:
    def test_tmdl_settings_use_power_bi_defaults(self):
        given = "CodeCoverage's relationships.tmdl, which sets only crossFilteringBehavior: bothDirections"
        should = "read cross-filter Both and Power BI's default for every absent line"
        from pql_test.odcs.pbip import model_relationship_settings

        settings = model_relationship_settings(CODE_COVERAGE)

        assert settings == {
            ("Fact_Table", "Date ID", "Date_Dim", "Date ID"): {
                "fromCardinality": "Many",
                "toCardinality": "One",
                "securityFilteringBehavior": "OneDirection",
                "crossFilteringBehavior": "BothDirections",
                "isActive": "TRUE",
            }
        }, f"{given}: {should}"

    def test_tmdl_reads_every_setting(self, tmp_path):
        given = "a relationship whose TMDL sets every setting away from its default"
        should = "read each one"
        from pql_test.odcs.pbip import model_relationship_settings

        model = tmp_path / "M.SemanticModel"
        (model / "definition").mkdir(parents=True)
        (model / "definition" / "relationships.tmdl").write_text(
            "relationship abc\n"
            "\tisActive: false\n"
            "\tcrossFilteringBehavior: automatic\n"
            "\tfromCardinality: one\n"
            "\ttoCardinality: many\n"
            "\tsecurityFilteringBehavior: none\n"
            "\tfromColumn: A.x\n"
            "\ttoColumn: 'B b'.'y y'\n",
            encoding="utf-8",
        )

        assert model_relationship_settings(model) == {
            ("A", "x", "B b", "y y"): {
                "fromCardinality": "One",
                "toCardinality": "Many",
                "securityFilteringBehavior": "None",
                "crossFilteringBehavior": "Automatic",
                "isActive": "FALSE",
            }
        }, f"{given}: {should}"

    def _code_coverage_contract(self, tmp_path, **settings) -> Path:
        # "Date ID" has a space, which a table.property reference cannot hold, so the ends are named by id.
        relationship = {"to": "schema/date_dim/properties/date_id", "customProperties": custom(**settings)}
        schema = [
            schema_object("Fact_Table", [prop("Date ID", "string", relationships=[relationship])], id="fact"),
            schema_object("Date_Dim", [prop("Date ID", "integer", id="date_id")], id="date_dim"),
        ]
        path = tmp_path / "c.odcs.yaml"
        path.write_text(yaml.safe_dump(contract_dict(schema=schema)), encoding="utf-8")
        return path

    def test_lint_reports_a_setting_the_model_does_not_have(self, tmp_path):
        given = "lint against CodeCoverage (cross-filter Both) of a contract saying pbiCrossFilteringBehavior: single"
        should = "report the property and both values"
        from pql_test.cli import cli

        path = self._code_coverage_contract(tmp_path, pbiCrossFilteringBehavior="single", pbiCardinality="manyToOne")

        result = CliRunner().invoke(cli, ["contract", "lint", str(path), str(CODE_COVERAGE), "--format", "json"])

        problems = json.loads(result.stdout)["problems"]
        drift = [p for p in problems if "pbiCrossFilteringBehavior" in p]
        assert (len(drift), "single" in "".join(drift), "both" in "".join(drift), len(problems)) == (1, True, True, 1), (
            f"{given}: {should}\n{problems}"
        )

    def test_lint_passes_settings_the_model_has(self, tmp_path):
        given = "lint against CodeCoverage of a contract stating its relationship's settings as they are"
        should = "report no problem"
        from pql_test.cli import cli

        path = self._code_coverage_contract(
            tmp_path,
            pbiCardinality="manyToOne",
            pbiCrossFilteringBehavior="bothDirections",
            pbiIsActive=True,
            pbiSecurityFilteringBehavior="oneDirection",
        )

        result = CliRunner().invoke(cli, ["contract", "lint", str(path), str(CODE_COVERAGE), "--format", "json"])

        assert json.loads(result.stdout)["problems"] == [], f"{given}: {should}"


class TestLiveSettings:
    @staticmethod
    def _query(dax: str) -> list[dict]:
        """INFO rows for two tables joined by an inactive, Both, one-to-one relationship."""
        if "INFO.TABLES" in dax:
            return [{"[ID]": 1, "[Name]": "Sales"}, {"[ID]": 2, "[Name]": "Date"}]
        if "INFO.COLUMNS" in dax:
            return [
                {"[ID]": 11, "[TableID]": 1, "[ExplicitName]": "DateKey", "[Type]": 1, "[ExplicitDataType]": 6},
                {"[ID]": 21, "[TableID]": 2, "[ExplicitName]": "DateKey", "[Type]": 1, "[ExplicitDataType]": 6},
            ]
        if "INFO.VIEW.RELATIONSHIPS" in dax:
            return [{"[FromTable]": "Sales", "[FromColumn]": "DateKey", "[ToTable]": "Date", "[ToColumn]": "DateKey"}]
        if "INFO.RELATIONSHIPS" in dax:
            return [
                {
                    "[FromTableID]": 1,
                    "[FromColumnID]": 11,
                    "[ToTableID]": 2,
                    "[ToColumnID]": 21,
                    "[FromCardinality]": 1,
                    "[ToCardinality]": 1,
                    "[CrossFilteringBehavior]": 2,
                    "[IsActive]": "False",
                    "[SecurityFilteringBehavior]": 3,
                }
            ]
        return []

    def test_live_inventory_reads_settings(self):
        given = "a connected model's INFO.RELATIONSHIPS() row (numeric TOM values)"
        should = "read the relationship's settings in TMDL names"
        from pql_test.odcs.coverage_live import live_inventory

        inventory = live_inventory(self._query)

        assert inventory.relationship_settings == {
            ("Sales", "DateKey", "Date", "DateKey"): {
                "fromCardinality": "One",
                "toCardinality": "One",
                "securityFilteringBehavior": "None",
                "crossFilteringBehavior": "BothDirections",
                "isActive": "FALSE",
            }
        }, f"{given}: {should}"


class TestSuggestions:
    def test_uncovered_relationship_is_suggested_with_its_settings(self):
        given = "coverage of CodeCoverage by a contract that lists its tables but not their relationship"
        should = "suggest the relationship with the four settings it has, in dialog words"
        from pql_test.odcs.coverage import build_coverage, model_inventory

        schema = [
            schema_object("Fact_Table", [prop("Date ID", "integer")]),
            schema_object("Date_Dim", [prop("Date ID", "integer")]),
        ]
        plan = plan_contract(contract_dict(schema=schema), pql_assert="0.9.1")

        report = build_coverage(plan, model_inventory(CODE_COVERAGE), model="CodeCoverage", pql_assert="0.9.1")

        (suggestion,) = [s for s in report.suggestions if s.kind.value == "RELATIONSHIP"]
        (entry,) = yaml.safe_load(suggestion.yaml)
        assert entry["customProperties"] == [
            {"property": "pbiCardinality", "value": "manyToOne"},
            {"property": "pbiCrossFilteringBehavior", "value": "both"},
            {"property": "pbiIsActive", "value": True},
            {"property": "pbiSecurityFilteringBehavior", "value": "oneDirection"},
        ], f"{given}: {should}\n{suggestion.yaml}"

    def test_a_relationship_checked_with_settings_counts_as_listed(self):
        given = "coverage of CodeCoverage by a contract whose relationship pins cross-filter both"
        should = "count the relationship as listed (checked), like one checked for existence only"
        from pql_test.odcs.coverage import Kind, Level, build_coverage, model_inventory

        relationship = {
            "to": "schema/date_dim/properties/date_id",
            "customProperties": custom(pbiCrossFilteringBehavior="both"),
        }
        schema = [
            schema_object("Fact_Table", [prop("Date ID", "string", relationships=[relationship])], id="fact"),
            schema_object("Date_Dim", [prop("Date ID", "integer", id="date_id")], id="date_dim"),
        ]
        plan = plan_contract(contract_dict(schema=schema), pql_assert="0.9.1")

        report = build_coverage(plan, model_inventory(CODE_COVERAGE), model="CodeCoverage", pql_assert="0.9.1")

        (level,) = [o.level for o in report.objects if o.obj.kind is Kind.RELATIONSHIP]
        assert level is Level.LISTED, f"{given}: {should}"
