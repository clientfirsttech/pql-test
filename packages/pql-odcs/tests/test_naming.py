# SPDX-License-Identifier: MIT
"""Unit tests for pql_odcs.naming (contract names -> semantic model names)."""

from __future__ import annotations

import pytest
from factories import contract_dict, custom, prop, schema_object

from pql_odcs.loader import load_contract
from pql_odcs.naming import MappingError, NameResolver, load_sidecar


def _contract(*objects):
    return load_contract(contract_dict(schema=list(objects)))


class TestPrecedence:
    def test_custom_properties_win_over_sidecar_and_logical_name(self):
        given = "pbiTable/pbiColumn customProperties and a sidecar entry for the same names"
        should = "use the customProperties values"
        contract = _contract(
            schema_object(
                "fact_marvel",
                [prop("eye_id", customProperties=custom(pbiColumn="EyeID"))],
                customProperties=custom(pbiTable="MarvelFact"),
            )
        )
        sidecar = {"tables": {"fact_marvel": "Other"}, "columns": {"fact_marvel": {"eye_id": "Other"}}}
        resolver = NameResolver(contract, sidecar)
        obj = contract.schema_objects[0]

        actual = (resolver.table(obj), resolver.column(obj, obj["properties"][0]))

        assert actual == ("MarvelFact", "EyeID"), f"{given}: {should}"

    def test_sidecar_applies_when_custom_properties_are_absent(self):
        given = "a sidecar entry and no customProperties"
        should = "use the sidecar names"
        contract = _contract(schema_object("fact_marvel", [prop("eye_id")]))
        sidecar = {"tables": {"fact_marvel": "MarvelFact"}, "columns": {"fact_marvel": {"eye_id": "EyeID"}}}
        resolver = NameResolver(contract, sidecar)
        obj = contract.schema_objects[0]

        actual = (resolver.table(obj), resolver.column(obj, obj["properties"][0]))

        assert actual == ("MarvelFact", "EyeID"), f"{given}: {should}"

    def test_falls_back_to_the_logical_name(self):
        given = "no customProperties and no sidecar"
        should = "use the ODCS logical names unchanged"
        contract = _contract(schema_object("MarvelFact", [prop("Name")]))
        resolver = NameResolver(contract)
        obj = contract.schema_objects[0]

        actual = (resolver.table(obj), resolver.column(obj, obj["properties"][0]))

        assert actual == ("MarvelFact", "Name"), f"{given}: {should}"


class TestSidecarProblems:
    def test_reports_entries_for_objects_missing_from_the_contract(self):
        given = "a sidecar naming a table and a column the contract does not define"
        should = "report each stale entry instead of silently ignoring it"
        contract = _contract(schema_object("MarvelFact", [prop("Name")]))
        sidecar = {"tables": {"Ghost": "G"}, "columns": {"MarvelFact": {"Missing": "M"}}}

        actual = NameResolver(contract, sidecar).problems()

        assert actual == [
            "mapping: columns.MarvelFact.Missing is not a property of MarvelFact in the contract",
            "mapping: tables.Ghost is not a schema object in the contract",
        ], f"{given}: {should}"

    def test_blank_resolved_name_is_a_problem(self):
        given = "a pbiTable customProperty set to an empty string"
        should = "report it, because an empty table name can never resolve"
        contract = _contract(schema_object("MarvelFact", [prop("Name")], customProperties=custom(pbiTable="")))

        actual = NameResolver(contract).problems()

        assert actual == ["MarvelFact: resolved table name is empty"], f"{given}: {should}"


class TestLoadSidecar:
    def test_reads_tables_and_columns(self, tmp_path):
        given = "a sidecar YAML file with tables and columns"
        should = "return its mapping"
        path = tmp_path / "pql-odcs.mapping.yaml"
        path.write_text("tables:\n  a: A\ncolumns:\n  a:\n    b: B\n", encoding="utf-8")

        assert load_sidecar(path) == {"tables": {"a": "A"}, "columns": {"a": {"b": "B"}}}, f"{given}: {should}"

    def test_rejects_unknown_top_level_keys(self, tmp_path):
        given = "a sidecar with a misspelled top-level key"
        should = "fail with a MappingError naming the key"
        path = tmp_path / "m.yaml"
        path.write_text("table:\n  a: A\n", encoding="utf-8")

        with pytest.raises(MappingError) as exc:
            load_sidecar(path)

        assert "table" in str(exc.value), f"{given}: {should}"


def test_malformed_columns_section_is_a_mapping_error(tmp_path):
    given = "a sidecar whose columns section is a list"
    should = "raise MappingError instead of crashing"
    path = tmp_path / "m.yaml"
    path.write_text("columns:\n  - a\n", encoding="utf-8")

    with pytest.raises(MappingError) as exc:
        load_sidecar(path)

    assert "columns" in str(exc.value), f"{given}: {should}"
