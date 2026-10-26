# SPDX-License-Identifier: MIT
"""Unit tests for pql_odcs.naming (contract names -> semantic model names)."""

from __future__ import annotations

from factories import contract_dict, custom, prop, schema_object

from pql_odcs.loader import load_contract
from pql_odcs.naming import NameResolver


def _contract(*objects):
    return load_contract(contract_dict(schema=list(objects)))


class TestResolution:
    def test_custom_properties_name_the_model_table_and_column(self):
        given = "pbiTable / pbiColumn customProperties on the contract"
        should = "use them as the semantic model names"
        contract = _contract(
            schema_object(
                "fact_marvel",
                [prop("eye_id", customProperties=custom(pbiColumn="EyeID"))],
                customProperties=custom(pbiTable="MarvelFact"),
            )
        )
        resolver = NameResolver(contract)
        obj = contract.schema_objects[0]

        actual = (resolver.table(obj), resolver.column(obj, obj["properties"][0]))

        assert actual == ("MarvelFact", "EyeID"), f"{given}: {should}"

    def test_falls_back_to_the_logical_name(self):
        given = "no customProperties"
        should = "use the ODCS logical names unchanged"
        contract = _contract(schema_object("MarvelFact", [prop("Name")]))
        resolver = NameResolver(contract)
        obj = contract.schema_objects[0]

        actual = (resolver.table(obj), resolver.column(obj, obj["properties"][0]))

        assert actual == ("MarvelFact", "Name"), f"{given}: {should}"

    def test_unrelated_custom_properties_are_ignored(self):
        given = "customProperties that are not pbiTable / pbiColumn"
        should = "fall back to the logical name"
        contract = _contract(schema_object("T", [prop("c")], customProperties=custom(owner="sales")))
        obj = contract.schema_objects[0]

        assert NameResolver(contract).table(obj) == "T", f"{given}: {should}"


class TestProblems:
    def test_blank_resolved_name_is_a_problem(self):
        given = "a pbiTable customProperty set to an empty string"
        should = "report it, because an empty table name can never resolve"
        contract = _contract(schema_object("MarvelFact", [prop("Name")], customProperties=custom(pbiTable="")))

        actual = NameResolver(contract).problems()

        assert actual == ["MarvelFact: resolved table name is empty"], f"{given}: {should}"
