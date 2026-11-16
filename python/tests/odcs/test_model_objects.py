# SPDX-License-Identifier: AGPL-3.0-only
"""The model objects `contract coverage` counts, read from a PBIP model's TMDL (pbip.model_tables, coverage.model_inventory)."""

from __future__ import annotations

from pathlib import Path

from pql_test.odcs.coverage import Kind, model_inventory
from pql_test.odcs.pbip import model_tables
from pql_test.odcs.scaffold import starter_contract

SAMPLE = Path(__file__).resolve().parents[3] / "examples" / "SampleModel.SemanticModel"


def _model(tmp_path: Path, tables: dict[str, str], relationships: str = "") -> Path:
    """A *.SemanticModel folder whose tables/<name>.tmdl files hold the given TMDL bodies."""
    sm = tmp_path / "M.SemanticModel"
    (sm / "definition" / "tables").mkdir(parents=True)
    for name, body in tables.items():
        (sm / "definition" / "tables" / f"{name}.tmdl").write_text(body, encoding="utf-8")
    if relationships:
        (sm / "definition" / "relationships.tmdl").write_text(relationships, encoding="utf-8")
    return sm


SALES = (
    "table Sales\n"
    "\tmeasure 'Total Amount' = SUM(Sales[Amount])\n"
    "\t\tformatString: 0\n"
    "\n"
    "\tmeasure Orders = ```\n"
    "\t\t\tCOUNTROWS(Sales)\n"
    "\t\t\t```\n"
    "\n"
    "\tcolumn Amount\n"
    "\t\tdataType: double\n"
    "\n"
    "\tcolumn CustomerKey\n"
    "\t\tdataType: int64\n"
    "\t\tisHidden\n"
    "\n"
    "\tcolumn 'Amount Band' = IF([Amount] > 100, \"High\", \"Low\")\n"
    "\t\tdataType: string\n"
    "\n"
    "\tpartition Sales = m\n"
)


def _identifiers(inventory, kind: Kind) -> list[str]:
    return sorted(o.identifier for o in inventory.objects if o.kind is kind)


class TestModelTables:
    def test_lists_measures_with_their_home_table(self, tmp_path):
        given = "a table with a one-line measure and a multi-line ``` measure"
        should = "list both measures under that table"

        (sales,) = model_tables(_model(tmp_path, {"Sales": SALES}))

        assert sales.measures == ("Total Amount", "Orders"), f"{given}: {should}"

    def test_marks_calculated_and_hidden_columns(self, tmp_path):
        given = "a data column, a hidden data column, and a calculated column with a data type"
        should = "mark only the `column X = <DAX>` one calculated, and only the isHidden one hidden"

        (sales,) = model_tables(_model(tmp_path, {"Sales": SALES}))

        flags = {c.name: (c.calculated, c.hidden) for c in sales.columns}
        assert flags == {
            "Amount": (False, False),
            "CustomerKey": (False, True),
            "Amount Band": (True, False),
        }, f"{given}: {should}"

    def test_columns_of_a_calculated_table_are_calculated(self, tmp_path):
        given = "a calculated table (partition = calculated) whose columns have no `=`"
        should = "mark its columns calculated, because their values come from the table's DAX"
        body = "table Zones\n\tcolumn Zone\n\t\tsourceColumn: [Value1]\n\n\tpartition Zones = calculated\n\t\tmode: import\n"

        (zones,) = model_tables(_model(tmp_path, {"Zones": body}))

        assert [c.calculated for c in zones.columns] == [True], f"{given}: {should}"


class TestModelInventory:
    def test_counts_tables_columns_measures_and_relationships(self, tmp_path):
        given = "a model with a fact table, a dimension, and a relationship between them"
        should = "list every table, column (hidden ones too), measure, and relationship"
        model = _model(
            tmp_path,
            {"Sales": SALES, "Customer": "table Customer\n\tcolumn CustomerKey\n\t\tdataType: int64\n"},
            "relationship r1\n\tfromColumn: Sales.CustomerKey\n\ttoColumn: Customer.CustomerKey\n",
        )

        inventory = model_inventory(model)

        assert (
            _identifiers(inventory, Kind.TABLE),
            _identifiers(inventory, Kind.COLUMN),
            _identifiers(inventory, Kind.MEASURE),
            _identifiers(inventory, Kind.RELATIONSHIP),
        ) == (
            ["Customer", "Sales"],
            ["Customer[CustomerKey]", "Sales[Amount Band]", "Sales[Amount]", "Sales[CustomerKey]"],
            ["Sales[Orders]", "Sales[Total Amount]"],
            ["Sales[CustomerKey]->Customer[CustomerKey]"],
        ), f"{given}: {should}"

    def test_leaves_out_what_init_leaves_out_but_keeps_the_measures(self, tmp_path):
        given = "an automatic date table, its relationship, and a measure table with a hidden placeholder column"
        should = (
            "exclude the date table, its column and relationship, and the measure table and its placeholder "
            "column, with reasons, but still count the measure"
        )
        model = _model(
            tmp_path,
            {
                "Sales": "table Sales\n\tcolumn OrderDate\n\t\tdataType: dateTime\n",
                "LocalDateTable_1": "table LocalDateTable_1\n\tcolumn Date\n\t\tdataType: dateTime\n",
                "_Measures": "table _Measures\n\tmeasure Now = NOW()\n\n\tcolumn Placeholder\n\t\tisHidden\n",
            },
            "relationship r1\n\tfromColumn: Sales.OrderDate\n\ttoColumn: LocalDateTable_1.Date\n",
        )

        inventory = model_inventory(model)

        excluded = sorted((e.kind.value, e.identifier) for e in inventory.excluded)
        assert (
            _identifiers(inventory, Kind.TABLE),
            _identifiers(inventory, Kind.MEASURE),
            _identifiers(inventory, Kind.RELATIONSHIP),
            excluded,
            all(e.reason for e in inventory.excluded),
        ) == (
            ["Sales"],
            ["_Measures[Now]"],
            [],
            [
                ("COLUMN", "LocalDateTable_1[Date]"),
                ("COLUMN", "_Measures[Placeholder]"),
                ("RELATIONSHIP", "Sales[OrderDate]->LocalDateTable_1[Date]"),
                ("TABLE", "LocalDateTable_1"),
                ("TABLE", "_Measures"),
            ],
            True,
        ), f"{given}: {should}"

    def test_leaves_out_calculation_groups(self, tmp_path):
        given = "a calculation group table"
        should = "exclude it and its column with a reason, because no contract rule targets one"
        body = "table 'Time Calc'\n\tcalculationGroup\n\t\tcalculationItem YTD = TOTALYTD(SELECTEDMEASURE(), 'Date'[Date])\n\n\tcolumn Name\n\t\tdataType: string\n"

        inventory = model_inventory(_model(tmp_path, {"Time Calc": body}))

        assert (inventory.objects, sorted(e.identifier for e in inventory.excluded)) == (
            (),
            ["Time Calc", "Time Calc[Name]"],
        ), f"{given}: {should}"

    def test_init_starter_lists_every_counted_table_and_column(self):
        given = "SampleModel and the starter contract `init` writes for it"
        should = "count exactly the tables and columns the starter describes, so the starter covers all of them"
        contract = starter_contract(SAMPLE)

        inventory = model_inventory(SAMPLE)

        starter = (
            sorted(o["name"] for o in contract["schema"]),
            sorted(f"{o['name']}[{p['name']}]" for o in contract["schema"] for p in o["properties"]),
        )
        assert (_identifiers(inventory, Kind.TABLE), _identifiers(inventory, Kind.COLUMN)) == starter, f"{given}: {should}"
