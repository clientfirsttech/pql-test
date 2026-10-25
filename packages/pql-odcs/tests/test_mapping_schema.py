# SPDX-License-Identifier: MIT
"""Schema-rule mappers: object present, properties present, closed schema, required, distinct."""

from __future__ import annotations

from factories import contract_dict, custom, prop, schema_object

from pql_odcs.ir import DATA_QUALITY_SUITE, SCHEMA_SUITE, Status, Target
from pql_odcs.loader import load_contract
from pql_odcs.mapping import map_contract
from pql_odcs.naming import NameResolver


def _map(*objects, closed_schema=False):
    contract = load_contract(contract_dict(schema=list(objects)))
    outcomes = map_contract(contract, NameResolver(contract), closed_schema=closed_schema)
    return {o.rule_id: o for o in outcomes}


def _ops(outcome):
    return [(a.op, a.target, dict(a.args)) for a in outcome.assertions]


class TestObjectRules:
    def test_object_presence_maps_to_table_exists_in_the_schema_suite(self):
        given = "a schema object"
        should = "emit one tbl.exists assertion in the Schema suite"
        outcome = _map(schema_object("MarvelFact", [prop("ID")]))["MarvelFact.exists"]

        assert (outcome.status, _ops(outcome), outcome.assertions[0].suite) == (
            Status.MAPPED,
            [("tbl.exists", Target("MarvelFact"), {})],
            SCHEMA_SUITE,
        ), f"{given}: {should}"

    def test_properties_map_to_one_columns_check_per_table(self):
        given = "a schema object with three properties"
        should = "emit a single tbl.has_columns assertion listing every resolved column"
        outcome = _map(
            schema_object(
                "MarvelFact",
                [prop("ID"), prop("name", customProperties=custom(pbiColumn="Name")), prop("Appearances")],
            )
        )["MarvelFact.columns"]

        assert _ops(outcome) == [
            ("tbl.has_columns", Target("MarvelFact"), {"columns": ["ID", "Name", "Appearances"]})
        ], f"{given}: {should}"

    def test_closed_schema_is_opt_in(self):
        given = "no closed-schema opt-in"
        should = "not produce a no-extra-columns rule"

        assert "MarvelFact.closed" not in _map(schema_object("MarvelFact", [prop("ID")])), f"{given}: {should}"

    def test_closed_schema_opt_in_forbids_extra_columns(self):
        given = "the closed-schema opt-in"
        should = "emit tbl.no_extra_columns with the contract's columns"
        outcome = _map(schema_object("MarvelFact", [prop("ID"), prop("Name")]), closed_schema=True)["MarvelFact.closed"]

        assert _ops(outcome) == [("tbl.no_extra_columns", Target("MarvelFact"), {"columns": ["ID", "Name"]})], (
            f"{given}: {should}"
        )

    def test_column_names_with_commas_cannot_use_the_columns_check(self):
        given = "a property whose column name contains a comma"
        should = "skip the columns rule, because PQL.Assert splits its list on commas"
        outcome = _map(schema_object("T", [prop("a,b")]))["T.columns"]

        assert (outcome.status, "comma" in outcome.reason) == (Status.SKIPPED, True), f"{given}: {should}"


class TestScheduledRules:
    def test_rules_scheduled_for_later_releases_are_reported_as_skipped(self):
        given = "types, logicalTypeOptions, relationships, and SLA properties (all after v0.1)"
        should = "each appear as a skipped rule naming its release, never dropped"
        data = contract_dict(
            schema=[
                schema_object(
                    "Orders",
                    [
                        prop(
                            "amount",
                            "number",
                            physicalType="DECIMAL(10,2)",
                            logicalTypeOptions={"minimum": 0, "maximum": 10},
                        ),
                        prop("code", logicalTypeOptions={"pattern": "^[A-Z]+$"}),
                    ],
                    relationships=[{"type": "foreignKey", "from": "Orders.amount", "to": "Other.id"}],
                )
            ],
            slaProperties=[{"property": "latency", "value": 4, "unit": "d"}],
        )
        contract = load_contract(data)
        rules = {o.rule_id: o for o in map_contract(contract, NameResolver(contract))}

        actual = {
            rid: (rules[rid].status, release in rules[rid].reason)
            for rid, release in [
                ("Orders.amount.type", "v0.2"),
                ("Orders.amount.logicalTypeOptions", "v0.2"),
                ("Orders.code.logicalTypeOptions", "v0.3"),
                ("Orders.relationships[0]", "v0.2"),
                ("slaProperties[0]", "R8"),
            ]
        }

        assert set(actual.values()) == {(Status.SKIPPED, True)}, f"{given}: {should}\n{actual}"


class TestPropertyRules:
    def test_required_maps_to_zero_null_rate(self):
        given = "a required property"
        should = "emit col.null_rate_at_most 0 (not Col.ShouldNotBeNull; gap plan C1)"
        outcome = _map(schema_object("MarvelFact", [prop("Name", required=True)]))["MarvelFact.Name.required"]

        assert (_ops(outcome), outcome.assertions[0].suite) == (
            [("col.null_rate_at_most", Target("MarvelFact", "Name"), {"maxPct": 0})],
            DATA_QUALITY_SUITE,
        ), f"{given}: {should}"

    def test_primary_key_unique_and_duplicate_rule_share_one_distinct_check(self):
        given = "a column that is primaryKey, unique, and has duplicateValues mustBe 0"
        should = "map all three rules to one shared col.distinct (unique/duplicateValues approximated: blanks)"
        rules = _map(
            schema_object(
                "Dim",
                [
                    prop(
                        "ID",
                        primaryKey=True,
                        unique=True,
                        quality=[{"metric": "duplicateValues", "mustBe": 0}],
                    )
                ],
            )
        )
        sources = [rules["Dim.ID.primaryKey"], rules["Dim.ID.unique"], rules["Dim.ID.quality[0]"]]
        shared = {id(a) for o in sources for a in o.assertions}

        assert ([o.status for o in sources], len(shared), sources[0].assertions[0].op) == (
            [Status.APPROXIMATED] * 3,
            1,
            "col.distinct",
        ), f"{given}: {should}"

    def test_composite_primary_key_is_not_mapped_to_per_column_distinct(self):
        given = "an object whose primary key spans two columns"
        should = "skip each primaryKey rule, because neither column is distinct on its own"
        rules = _map(schema_object("Bridge", [prop("A", primaryKey=True), prop("B", primaryKey=True)]))

        actual = [
            (rules[r].status, "composite" in rules[r].reason) for r in ("Bridge.A.primaryKey", "Bridge.B.primaryKey")
        ]

        assert actual == [(Status.SKIPPED, True)] * 2, f"{given}: {should}"

    def test_nested_properties_are_reported_not_dropped(self):
        given = "an object-typed property with a required nested property"
        should = "report the nested rule as skipped instead of dropping it"
        rules = _map(schema_object("T", [prop("addr", "object", properties=[prop("zip", required=True)])]))

        assert rules["T.addr.zip.required"].status is Status.SKIPPED, f"{given}: {should}"

    def test_nested_object_property_is_excluded_from_the_columns_check(self):
        given = "an object-typed property"
        should = "not be listed as a model column"
        rules = _map(schema_object("T", [prop("id"), prop("addr", "object", properties=[prop("zip")])]))

        assert dict(rules["T.columns"].assertions[0].args) == {"columns": ["id"]}, f"{given}: {should}"


class TestOdcs32Rules:
    def _rules(self, *props):
        contract = load_contract(contract_dict("v3.2.0", schema=[schema_object("T", list(props))]))
        return {o.rule_id: o for o in map_contract(contract, NameResolver(contract))}

    def test_enum_is_reported_as_skipped_until_v0_2(self):
        given = "a 3.2 property with an enum of allowed values"
        should = "be skipped with a reason naming v0.2 and Col.ValuesShouldBeInSet"
        rule = self._rules(prop("status", enum=[{"value": "open"}, {"value": "closed"}]))["T.status.enum"]

        assert (rule.status, "v0.2" in rule.reason, "ValuesShouldBeInSet" in rule.reason) == (
            Status.SKIPPED,
            True,
            True,
        ), f"{given}: {should}"

    def test_map_and_vector_properties_are_not_model_columns(self):
        given = "3.2 map and vector properties"
        should = "be left out of the columns check"
        map_def = {"key": {"logicalType": "string"}, "value": {"logicalType": "string", "required": True}}
        rules = self._rules(prop("id"), prop("attrs", "map", map=map_def), prop("embedding", "vector"))

        assert dict(rules["T.columns"].assertions[0].args) == {"columns": ["id"]}, f"{given}: {should}"

    def test_rules_inside_a_map_value_are_reported_not_dropped(self):
        given = "a 3.2 map property whose value definition is required"
        should = "report the nested rule as skipped"
        map_def = {"key": {"logicalType": "string"}, "value": {"logicalType": "string", "required": True}}
        rules = self._rules(prop("attrs", "map", map=map_def))

        assert rules["T.attrs.map.value.required"].status is Status.SKIPPED, f"{given}: {should}"
