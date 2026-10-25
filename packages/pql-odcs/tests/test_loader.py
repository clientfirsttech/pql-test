# SPDX-License-Identifier: MIT
"""Unit tests for pql_odcs.loader."""

from __future__ import annotations

import pytest
import yaml
from factories import contract_dict, prop, schema_object

from pql_odcs.loader import ContractError, load_contract


def _write_yaml(tmp_path, data: dict, name: str = "c.odcs.yaml"):
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


class TestLoadContract:
    def test_yaml_path_and_dict_produce_identical_contracts(self, tmp_path):
        given = "the same contract as a YAML file and as an already-parsed dict"
        should = "load to equal Contract values"
        data = contract_dict(schema=[schema_object("MarvelFact", [prop("ID", "integer")])])

        from_file = load_contract(_write_yaml(tmp_path, data))
        from_dict = load_contract(data)

        assert from_file == from_dict, f"{given}: {should}"

    def test_records_where_the_contract_came_from(self, tmp_path):
        given = "a contract loaded from a file"
        should = "keep the file name as its source for generated headers"

        actual = load_contract(_write_yaml(tmp_path, contract_dict(), "marvel.odcs.yaml")).source

        assert actual == "marvel.odcs.yaml", f"{given}: {should}"

    def test_normalises_api_version(self):
        given = "apiVersion v3.0.2"
        should = "expose the version without the leading v"

        assert load_contract(contract_dict("v3.0.2")).api_version == "3.0.2", f"{given}: {should}"

    def test_does_not_mutate_the_callers_dict(self):
        given = "a dict handed over by an adapter"
        should = "leave the caller's dict unchanged"
        data = contract_dict()
        before = repr(data)

        load_contract(data)

        assert repr(data) == before, f"{given}: {should}"

    def test_unquoted_yaml_timestamps_stay_strings(self, tmp_path):
        given = "a YAML contract with an unquoted contractCreatedTs timestamp"
        should = "validate, because ODCS types timestamps as strings"
        path = tmp_path / "ts.odcs.yaml"
        path.write_text(
            yaml.safe_dump(contract_dict(), sort_keys=False) + "contractCreatedTs: 2026-10-24T10:00:00Z\n",
            encoding="utf-8",
        )

        actual = load_contract(path).data["contractCreatedTs"]

        assert actual == "2026-10-24T10:00:00Z", f"{given}: {should}"


class TestVersionGate:
    @pytest.mark.parametrize("version", ["v3.2.0", "v2.2.2", "v4.0.0"])
    def test_rejects_versions_outside_3_0_and_3_1(self, version):
        given = f"apiVersion {version}"
        should = "fail and name the supported range"

        with pytest.raises(ContractError) as exc:
            load_contract(contract_dict(version))

        assert "v3.0.x and v3.1.x" in str(exc.value), f"{given}: {should}"

    def test_missing_api_version_is_an_error(self):
        given = "a contract without apiVersion"
        should = "fail before schema validation"
        data = contract_dict()
        del data["apiVersion"]

        with pytest.raises(ContractError) as exc:
            load_contract(data)

        assert "apiVersion" in str(exc.value), f"{given}: {should}"


class TestSchemaValidation:
    def test_reports_every_violation_with_its_json_path(self):
        given = "a contract with two invalid properties in different objects"
        should = "report both violations with JSON paths, not just the first"
        data = contract_dict(
            schema=[
                schema_object("A", [prop("x", required="yes")]),
                schema_object("B", [prop("y", unique=3)]),
            ]
        )

        with pytest.raises(ContractError) as exc:
            load_contract(data)

        paths = [p.split(":", 1)[0] for p in exc.value.problems]
        assert {"$.schema[0].properties[0].required", "$.schema[1].properties[0].unique"} <= set(paths), (
            f"{given}: {should}"
        )

    def test_validates_3_0_contracts_against_the_3_0_schema(self):
        given = "a v3.0.2 contract using the 3.0 `rule` keyword on a quality check"
        should = "validate against the bundled 3.0.2 schema"
        data = contract_dict(
            "v3.0.2",
            schema=[schema_object("T", quality=[{"type": "library", "rule": "rowCount", "mustBeGreaterThan": 0}])],
        )

        assert load_contract(data).api_version == "3.0.2", f"{given}: {should}"

    def test_unreadable_yaml_is_a_contract_error(self, tmp_path):
        given = "a file that is not valid YAML"
        should = "raise ContractError, not a YAML exception"
        path = tmp_path / "bad.odcs.yaml"
        path.write_text("apiVersion: [unclosed\n", encoding="utf-8")

        with pytest.raises(ContractError) as exc:
            load_contract(path)

        assert "not valid YAML" in str(exc.value), f"{given}: {should}"
