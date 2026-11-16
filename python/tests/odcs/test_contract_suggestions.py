# SPDX-License-Identifier: AGPL-3.0-only
"""`contract coverage` tells the contract owner what to change: YAML to add, and entries the model lacks."""

from __future__ import annotations

import copy
from pathlib import Path

import yaml

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
