# SPDX-License-Identifier: AGPL-3.0-only
"""`contract coverage` tells the contract owner what to change: YAML to add, and entries the model lacks."""

from __future__ import annotations

import copy
import json
from importlib.resources import files
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner
from jsonschema import Draft202012Validator

from pql_test.odcs.api import plan_contract
from pql_test.odcs.coverage import Kind, Level, build_coverage, model_inventory
from tests.odcs.factories import contract_dict, prop, schema_object

SALES_TMDL = (
    "table Sales\n"
    "\tmeasure 'Total Amount' = SUM(Sales[Amount])\n"
    "\n"
    "\tcolumn Amount\n"
    "\t\tdataType: double\n"
    "\n"
    "\tcolumn Region\n"
    "\t\tdataType: string\n"
)
CUSTOMER_TMDL = (
    "table Customer\n\tmeasure Customers = COUNTROWS(Customer)\n\n"
    "\tcolumn Id\n\t\tdataType: int64\n\n\tcolumn Since\n\t\tdataType: dateTime\n"
)
MEASURES_TMDL = "table _Measures\n\tmeasure Now = NOW()\n\n\tcolumn Placeholder\n\t\tisHidden\n"


def _model(tmp_path: Path) -> Path:
    sm = tmp_path / "M.SemanticModel"
    (sm / "definition" / "tables").mkdir(parents=True)
    (sm / "definition" / "tables" / "Sales.tmdl").write_text(SALES_TMDL, encoding="utf-8")
    (sm / "definition" / "tables" / "Customer.tmdl").write_text(CUSTOMER_TMDL, encoding="utf-8")
    (sm / "definition" / "tables" / "_Measures.tmdl").write_text(MEASURES_TMDL, encoding="utf-8")
    return sm


def _report(contract: dict, model: Path):
    return build_coverage(plan_contract(contract, pql_assert="0.9"), model_inventory(model), model=str(model), pql_assert="0.9")


def _apply(contract: dict, suggestion) -> dict:
    """Add one suggestion's YAML to a copy of *contract*, where the suggestion says it goes."""
    updated = copy.deepcopy(contract)
    entries = yaml.safe_load(suggestion.yaml)
    if suggestion.section == "schema":
        updated["schema"].extend(entries)
        return updated
    owner = suggestion.schema_object or updated["schema"][0]["name"]  # None: any schema object
    obj = next(o for o in updated["schema"] if o["name"] == owner)
    obj.setdefault(suggestion.section, []).extend(entries)
    return updated


def _level(report, kind: Kind, identifier: str) -> Level:
    return next(c.level for c in report.objects if c.obj.kind is kind and c.obj.identifier == identifier)


SALES_ONLY = contract_dict(schema=[schema_object("Sales", [prop("Amount", "number")])])


class TestSuggestions:
    def test_a_missing_table_gets_a_schema_object_with_init_types(self, tmp_path):
        given = "a model table the contract does not list, with a measure"
        should = (
            "suggest a schema object built like init's, with each column's logicalType from the TMDL, "
            "holding a rule template for the measure"
        )

        report = _report(SALES_ONLY, _model(tmp_path))

        (customer,) = [s for s in report.suggestions if s.identifier == "Customer"]
        assert (customer.section, yaml.safe_load(customer.yaml)) == (
            "schema",
            [
                {
                    "name": "Customer",
                    "physicalType": "table",
                    "properties": [{"name": "Id", "logicalType": "integer"}, {"name": "Since", "logicalType": "date"}],
                    "quality": [
                        {
                            "id": "customers-check",
                            "type": "custom",
                            "engine": "pql-test",
                            "description": "Customers has the expected value (edit the comparator below)",
                            "implementation": {"expression": "[Customers]", "mustBeGreaterThan": 0},
                        }
                    ],
                }
            ],
        ), f"{given}: {should}"

    def test_a_measure_whose_table_no_schema_object_holds_can_go_anywhere(self, tmp_path):
        given = "a measure in a measure table, which the contract never lists"
        should = "suggest its rule template for any schema object, not one that only looks related"

        report = _report(SALES_ONLY, _model(tmp_path))

        (now,) = [s for s in report.suggestions if s.identifier == "_Measures[Now]"]
        assert (now.section, now.schema_object, now.where) == ("quality", None, "under any schema object, quality:"), (
            f"{given}: {should}"
        )

    def test_a_missing_column_goes_under_its_schema_object(self, tmp_path):
        given = "a column of a listed table that the contract does not list"
        should = "suggest a property for that schema object, and no separate one for columns of a missing table"

        report = _report(SALES_ONLY, _model(tmp_path))

        columns = [(s.schema_object, s.section, s.identifier) for s in report.suggestions if s.kind is Kind.COLUMN]
        assert columns == [("Sales", "properties", "Sales[Region]")], f"{given}: {should}"

    def test_applying_the_suggestions_covers_what_they_name(self, tmp_path):
        given = "a contract with every table, column, and measure suggestion applied"
        should = "list the table and column, and test every measure's value"
        model = _model(tmp_path)
        contract = SALES_ONLY
        for suggestion in _report(SALES_ONLY, model).suggestions:
            contract = _apply(contract, suggestion)

        after = _report(contract, model)

        assert (
            _level(after, Kind.TABLE, "Customer"),
            _level(after, Kind.COLUMN, "Sales[Region]"),
            _level(after, Kind.MEASURE, "Sales[Total Amount]"),
            _level(after, Kind.MEASURE, "Customer[Customers]"),
            _level(after, Kind.MEASURE, "_Measures[Now]"),
        ) == (Level.LISTED, Level.LISTED, *(Level.VALUES_TESTED,) * 3), f"{given}: {should}"

    def test_contract_entries_the_model_lacks_are_reported(self, tmp_path):
        given = "a contract listing a table and a column the model does not have"
        should = "report both, using lint's model checks, so one run says what to remove too"
        contract = contract_dict(schema=[schema_object("Sales", [prop("Discount", "number")]), schema_object("Ghost")])

        report = _report(contract, _model(tmp_path))

        assert (
            any("Discount" in m and "not found" in m for m in report.mismatches),
            any("Ghost" in m and "not found" in m for m in report.mismatches),
        ) == (True, True), f"{given}: {report.mismatches}"


def test_suggested_rule_ids_are_unique(tmp_path):
    given = "two measures whose names slug alike ('Sales %' and 'Sales $') and a contract rule already named sales-check"
    should = "give every suggested rule its own id, so pasting them all keeps the contract's ids unique"
    sm = tmp_path / "M.SemanticModel"
    (sm / "definition" / "tables").mkdir(parents=True)
    body = "table Sales\n\tmeasure 'Sales %' = 1\n\n\tmeasure 'Sales $' = 2\n\n\tcolumn Amount\n\t\tdataType: double\n"
    (sm / "definition" / "tables" / "Sales.tmdl").write_text(body, encoding="utf-8")
    taken = {"id": "sales-check", "type": "custom", "engine": "pql-test", "implementation": {"expression": "1", "mustBe": 1}}
    contract = contract_dict(schema=[schema_object("Sales", [prop("Amount", "number")], quality=[taken])])

    report = _report(contract, sm)

    ids = [yaml.safe_load(s.yaml)[0]["id"] for s in report.suggestions if s.kind is Kind.MEASURE]
    assert (len(ids), len(set(ids)), "sales-check" in ids) == (2, 2, False), f"{given}: {should}: {ids}"


def _related_model(tmp_path: Path) -> Path:
    """Two relationships: one between names a table.property reference can hold, one between names with spaces."""
    sm = tmp_path / "R.SemanticModel"
    tables = sm / "definition" / "tables"
    tables.mkdir(parents=True)
    for table, column in (("Orders", "CustomerId"), ("Customer", "Id"), ("'Fact Table'", "'Date ID'"), ("'Date Dim'", "'Date ID'")):
        (tables / f"{table.strip(chr(39))}.tmdl").write_text(
            f"table {table}\n\tcolumn {column}\n\t\tdataType: int64\n", encoding="utf-8"
        )
    (sm / "definition" / "relationships.tmdl").write_text(
        "relationship a1\n\tfromColumn: Orders.CustomerId\n\ttoColumn: Customer.Id\n\n"
        "relationship b2\n\tfromColumn: 'Fact Table'.'Date ID'\n\ttoColumn: 'Date Dim'.'Date ID'\n",
        encoding="utf-8",
    )
    return sm


# The settings a relationship TMDL leaves at Power BI's defaults, as a suggestion writes them.
DEFAULT_SETTINGS = [
    {"property": "pbiCardinality", "value": "manyToOne"},
    {"property": "pbiCrossFilteringBehavior", "value": "single"},
    {"property": "pbiIsActive", "value": True},
    {"property": "pbiSecurityFilteringBehavior", "value": "oneDirection"},
]
RELATED = contract_dict(
    schema=[
        schema_object("Orders", [prop("CustomerId", "integer")]),
        schema_object("Customer", [prop("Id", "integer")]),
        schema_object("Fact Table", [prop("Date ID", "integer")]),
        schema_object("Date Dim", [prop("Date ID", "integer")], id="date_dim"),
    ]
)


def _apply_all(contract: dict, report) -> dict:
    """Apply every suggestion, giving each element the ids its suggestion lists first."""
    for suggestion in report.suggestions:
        for owner, prop_name, element_id in suggestion.ids:
            contract = copy.deepcopy(contract)
            obj = next(o for o in contract["schema"] if o["name"] == owner)
            element = obj if prop_name is None else next(p for p in obj["properties"] if p["name"] == prop_name)
            element["id"] = element_id
        contract = _apply(contract, suggestion)
    return contract


class TestRelationshipSuggestions:
    def _suggestion(self, report, identifier: str):
        return next(s for s in report.suggestions if s.kind is Kind.RELATIONSHIP and s.identifier == identifier)

    def test_names_a_reference_can_hold_get_the_shorthand_form(self, tmp_path):
        given = "an uncovered relationship between names that fit a table.property reference"
        should = "suggest a schema-level foreign key under the foreign key's schema object, with no ids to add"

        s = self._suggestion(_report(RELATED, _related_model(tmp_path)), "Orders[CustomerId]->Customer[Id]")

        assert (s.section, s.schema_object, s.ids, yaml.safe_load(s.yaml)) == (
            "relationships",
            "Orders",
            (),
            [
                {
                    "type": "foreignKey",
                    "from": "Orders.CustomerId",
                    "to": "Customer.Id",
                    "customProperties": DEFAULT_SETTINGS,
                }
            ],
        ), f"{given}: {should}"

    def test_names_with_spaces_get_the_id_form(self, tmp_path):
        given = "an uncovered relationship between columns named 'Date ID', and 'Date Dim' already has an id"
        should = "suggest the id form, reuse the existing id, and list the ids the other elements need"

        s = self._suggestion(_report(RELATED, _related_model(tmp_path)), "Fact Table[Date ID]->Date Dim[Date ID]")

        assert (s.schema_object, s.ids, yaml.safe_load(s.yaml)) == (
            "Fact Table",
            (("Fact Table", None, "fact_table"), ("Fact Table", "Date ID", "date_id"), ("Date Dim", "Date ID", "date_id")),
            [
                {
                    "type": "foreignKey",
                    "from": "schema/fact_table/properties/date_id",
                    "to": "schema/date_dim/properties/date_id",
                    "customProperties": DEFAULT_SETTINGS,
                }
            ],
        ), f"{given}: {should}"

    def test_only_the_end_that_needs_ids_gets_them(self, tmp_path):
        given = "a relationship from a column a table.property reference can hold to one it cannot"
        should = "keep the shorthand for the first end and ask for ids only on the second"
        sm = _related_model(tmp_path)
        (sm / "definition" / "relationships.tmdl").write_text(
            "relationship c3\n\tfromColumn: Orders.CustomerId\n\ttoColumn: 'Date Dim'.'Date ID'\n", encoding="utf-8"
        )

        s = self._suggestion(_report(RELATED, sm), "Orders[CustomerId]->Date Dim[Date ID]")

        assert (s.ids, yaml.safe_load(s.yaml)[0]["from"], yaml.safe_load(s.yaml)[0]["to"]) == (
            (("Date Dim", "Date ID", "date_id"),),
            "Orders.CustomerId",
            "schema/date_dim/properties/date_id",
        ), f"{given}: {should}"

    def test_suggested_ids_are_unique_within_their_array(self, tmp_path):
        given = "a schema object that already has the id the 'Fact Table' slug would get"
        should = "suggest another id, because an ODCS id must be unique within its containing array"
        contract = copy.deepcopy(RELATED)
        contract["schema"][0]["id"] = "fact_table"

        s = self._suggestion(_report(contract, _related_model(tmp_path)), "Fact Table[Date ID]->Date Dim[Date ID]")

        assert ("Fact Table", None, "fact_table_2") in s.ids, f"{given}: {should}: {s.ids}"

    def test_applying_them_covers_the_relationships_and_passes_lint(self, tmp_path):
        given = "a contract missing two tables, with every suggestion (and its ids) applied"
        should = "list both relationships, and pass lint's reference and model checks"
        from pql_test.odcs.mapping.relationships import broken_references

        model = _related_model(tmp_path)
        contract = contract_dict(schema=[schema_object("Orders", [prop("CustomerId", "integer")])])
        contract = _apply_all(contract, _report(contract, model))
        after = _report(contract, model)
        plan = plan_contract(contract, pql_assert="0.9")

        assert (
            _level(after, Kind.RELATIONSHIP, "Orders[CustomerId]->Customer[Id]"),
            _level(after, Kind.RELATIONSHIP, "Fact Table[Date ID]->Date Dim[Date ID]"),
            after.mismatches,
            broken_references(plan.contract, plan.names),
        ) == (Level.LISTED, Level.LISTED, (), []), f"{given}: {should}"

    def test_json_carries_the_ids_to_add(self, tmp_path):
        given = "an id-form relationship suggestion in the JSON report"
        should = "list each id to add with its schema object and property"

        out = _report(RELATED, _related_model(tmp_path)).to_json()

        (entry,) = [s for s in out["suggestions"] if s["kind"] == "RELATIONSHIP" and "Fact Table" in s["identifier"]]
        assert entry["ids"][0] == {"schemaObject": "Fact Table", "property": None, "id": "fact_table"}, (
            f"{given}: {should}"
        )


class TestRelationshipSuggestionsEndToEnd:
    """The commands a contract owner runs: coverage prints the ids and YAML, lint passes once they are applied."""

    @pytest.fixture(autouse=True)
    def _files_only(self, monkeypatch):
        monkeypatch.setenv("PQL_TEST_HERMETIC", "1")

    def _write(self, tmp_path: Path, contract: dict) -> Path:
        path = tmp_path / "c.odcs.yaml"
        path.write_text(yaml.safe_dump(contract, sort_keys=False), encoding="utf-8")
        return path

    def _coverage(self, *args):
        from pql_test.cli import cli

        return CliRunner().invoke(cli, ["contract", "coverage", *(str(a) for a in args)])

    def test_text_report_lists_the_ids_to_add(self, tmp_path):
        given = "an uncovered relationship between columns named 'Date ID'"
        should = "print each id to add, then the id-form YAML"
        model = _related_model(tmp_path)

        out = self._coverage(self._write(tmp_path, RELATED), model).output

        assert (
            "#   schema object 'Fact Table': id: fact_table" in out,
            "#   property 'Date ID' of 'Fact Table': id: date_id" in out,
            "from: schema/fact_table/properties/date_id" in out,
        ) == (True, True, True), f"{given}: {should}\n{out}"

    def test_json_with_ids_validates_against_the_packaged_schema(self, tmp_path):
        given = "a JSON coverage report with a non-empty ids list"
        should = "validate against contract-coverage.schema.json"
        schema = json.loads(files("pql_test.odcs").joinpath("contract-coverage.schema.json").read_text(encoding="utf-8"))

        result = self._coverage(self._write(tmp_path, RELATED), _related_model(tmp_path), "--format", "json")
        report = json.loads(result.stdout)

        assert (
            any(s["ids"] for s in report["suggestions"]),
            [e.message for e in Draft202012Validator(schema).iter_errors(report)],
        ) == (True, []), f"{given}: {should}"

    def test_lint_passes_once_the_suggestions_are_applied(self, tmp_path):
        given = "a contract missing two tables, with every suggestion and its ids applied"
        should = "pass `contract lint CONTRACT MODEL_PATH`"
        from pql_test.odcs.cli import contract as contract_group

        model = _related_model(tmp_path)
        contract = contract_dict(schema=[schema_object("Orders", [prop("CustomerId", "integer")])])
        path = self._write(tmp_path, _apply_all(contract, _report(contract, model)))

        result = CliRunner().invoke(contract_group, ["lint", str(path), str(model)])

        assert result.exit_code == 0, f"{given}: {should}\n{result.output}"

    def test_a_v3_0_contract_says_why_no_relationship_is_suggested(self, tmp_path):
        given = "a v3.0 contract and an uncovered relationship"
        should = "suggest none, and say ODCS v3.0 has no relationships"

        report = _report(contract_dict("v3.0.2", schema=RELATED["schema"][:2]), _related_model(tmp_path))

        assert (
            [s for s in report.suggestions if s.kind is Kind.RELATIONSHIP],
            any("ODCS v3.0 has no relationships" in u for u in report.unavailable),
        ) == ([], True), f"{given}: {should}"
