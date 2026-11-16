# SPDX-License-Identifier: AGPL-3.0-only
"""What each contract rule covers in the model, read from the contract alone (coverage.contract_evidence)."""

from __future__ import annotations

from pql_test.odcs.api import plan_contract
from pql_test.odcs.coverage import Inventory, Kind, Level, ModelObject, contract_evidence
from tests.odcs.factories import contract_dict, prop, schema_object


def _inventory(*objects: tuple[Kind, str]) -> Inventory:
    return Inventory(tuple(ModelObject(kind, identifier) for kind, identifier in objects), ())


SALES_MODEL = _inventory(
    (Kind.TABLE, "Sales"),
    (Kind.COLUMN, "Sales[id]"),
    (Kind.COLUMN, "Sales[amount]"),
    (Kind.TABLE, "Customer"),
    (Kind.COLUMN, "Customer[id]"),
    (Kind.COLUMN, "Customer[segment]"),
    (Kind.MEASURE, "Sales[Total]"),
    (Kind.RELATIONSHIP, "Sales[id]->Customer[id]"),
)


def _levels(found, kind: Kind | None = None) -> dict[str, Level]:
    """Strongest level per identifier (optionally one kind only)."""
    levels: dict[str, Level] = {}
    for e in found.evidence:
        if kind is None or e.kind is kind:
            levels[e.identifier] = max(levels.get(e.identifier, Level.NOT_COVERED), e.level)
    return levels


def _dax_rule(rule_id: str, implementation: dict) -> dict:
    return {"id": rule_id, "type": "custom", "engine": "pql-test", "implementation": implementation}


class TestContractEvidence:
    def test_schema_checks_list_and_data_rules_test_values(self):
        given = "a typed column with no data rule, and a required column (a null-count rule)"
        should = "mark the typed column listed, the required one and its table values tested"
        contract = contract_dict(schema=[schema_object("Sales", [prop("id"), prop("amount", "number", required=True)])])

        found = contract_evidence(plan_contract(contract, pql_assert="0.9"), SALES_MODEL)

        assert (_levels(found, Kind.COLUMN), _levels(found, Kind.TABLE)) == (
            {"Sales[id]": Level.LISTED, "Sales[amount]": Level.VALUES_TESTED},
            {"Sales": Level.VALUES_TESTED},
        ), f"{given}: {should}"

    def test_a_skipped_rule_still_lists_its_object(self):
        given = "a relationship under PQL.Assert 0.7, which cannot check relationships (the rule is skipped)"
        should = "mark the relationship listed but not enforced, and listed once 0.9 can check it"
        contract = contract_dict(
            schema=[
                schema_object("Sales", [prop("id", relationships=[{"type": "foreignKey", "to": "Customer.id"}])]),
                schema_object("Customer", [prop("id")]),
            ]
        )

        old = contract_evidence(plan_contract(contract, pql_assert="0.7"), SALES_MODEL)
        new = contract_evidence(plan_contract(contract, pql_assert="0.9"), SALES_MODEL)

        key = "Sales[id]->Customer[id]"
        assert (_levels(old, Kind.RELATIONSHIP)[key], _levels(new, Kind.RELATIONSHIP)[key]) == (
            Level.LISTED_NOT_ENFORCED,
            Level.LISTED,
        ), f"{given}: {should}"

    def test_contract_dax_covers_what_it_references_not_where_it_sits(self):
        given = "an engine: pql-test expression under Sales that references [Total] and 'Customer'[segment]"
        should = "mark the measure, the column, and its table values tested, but not Sales, where the rule sits"
        rule = _dax_rule("big-segments", {"expression": "CALCULATE([Total], 'Customer'[segment] = \"Big\")", "mustBeGreaterThan": 0})
        contract = contract_dict(schema=[schema_object("Sales", quality=[rule])])

        found = contract_evidence(plan_contract(contract, pql_assert="0.9"), SALES_MODEL)

        dax = {(e.kind, e.identifier, e.level) for e in found.evidence if e.rule_id == "big-segments"}
        assert dax == {
            (Kind.MEASURE, "Sales[Total]", Level.VALUES_TESTED),
            (Kind.COLUMN, "Customer[segment]", Level.VALUES_TESTED),
            (Kind.TABLE, "Customer", Level.VALUES_TESTED),
        }, f"{given}: {should}"

    def test_direct_call_arguments_are_scanned(self):
        given = "an engine: pql-test direct call whose argument is 'Sales'[amount]"
        should = "mark that column values tested"
        rule = _dax_rule("amount-mean", {"function": "PQL.Assert.Col.MeanShouldBeInRange", "args": ["'Sales'[amount]", 0, 100]})
        contract = contract_dict(schema=[schema_object("Sales", quality=[rule])])

        found = contract_evidence(plan_contract(contract, pql_assert="0.9"), SALES_MODEL)

        assert _levels(found, Kind.COLUMN) == {"Sales[amount]": Level.VALUES_TESTED}, f"{given}: {should}"

    def test_names_that_match_no_measure_are_unresolved_not_guessed(self):
        given = "[segment] (a column name, but no measure) and [Nope] in contract DAX"
        should = "count neither, and report both as unresolved for that rule"
        rule = _dax_rule("guess", {"expression": "[segment] & [Nope]", "mustBe": "x"})
        contract = contract_dict(schema=[schema_object("Sales", quality=[rule])])

        found = contract_evidence(plan_contract(contract, pql_assert="0.9"), SALES_MODEL)

        assert (
            [e for e in found.evidence if e.rule_id == "guess"],
            sorted((u.rule_id, u.reference) for u in found.unresolved),
        ) == ([], [("guess", "[Nope]"), ("guess", "[segment]")]), f"{given}: {should}"

    def test_names_match_the_model_whatever_their_case(self):
        given = "a contract that spells the table and column in another case than the model"
        should = "credit the model's objects, in the model's spelling (DAX names ignore case)"
        contract = contract_dict(schema=[schema_object("SALES", [prop("ID", required=True)])])

        found = contract_evidence(plan_contract(contract, pql_assert="0.9"), SALES_MODEL)

        assert _levels(found, Kind.COLUMN) == {"Sales[id]": Level.VALUES_TESTED}, f"{given}: {should}"
