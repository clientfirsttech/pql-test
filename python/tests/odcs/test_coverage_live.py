# SPDX-License-Identifier: AGPL-3.0-only
"""`contract coverage --live`: asking the model's engine what contract DAX references (pql_test.odcs.coverage_live).

The engine is Power BI's: CI has none, so these tests hand the code rows shaped like the ones
INFO.CALCDEPENDENCY("QUERY", ...) returned against SampleModel on 2026-11-16 (Desktop and the
service). tests/test_contract_live.py runs the same path against the real model.
"""

from __future__ import annotations

import pytest

from pql_test.odcs.api import plan_contract
from pql_test.odcs.coverage import ENGINE, SCAN, Inventory, Kind, ModelObject
from pql_test.odcs.coverage_live import batched_dependencies, engine_dax_evidence
from tests.odcs.factories import contract_dict, schema_object

ROW_NUMBER = "RowNumber-2662979B-1795-4F74-8F37-6A1BA8059B61"
MODEL = Inventory(
    tuple(
        ModelObject(kind, identifier, table=table, name=name)
        for kind, identifier, table, name in (
            (Kind.TABLE, "MarvelFact", "MarvelFact", ""),
            (Kind.TABLE, "DateDim", "DateDim", ""),
            (Kind.COLUMN, "MarvelFact[DateID]", "MarvelFact", "DateID"),
            (Kind.COLUMN, "DateDim[DateID]", "DateDim", "DateID"),
            (Kind.MEASURE, "MarvelFact[Running Total]", "MarvelFact", "Running Total"),
        )
    ),
    (),
)


def _contract(expression: str) -> dict:
    rule = {"id": "r", "type": "custom", "engine": "pql-test", "implementation": {"expression": expression, "mustBe": True}}
    return contract_dict(schema=[schema_object("MarvelFact", quality=[rule])])


def _engine(answers: dict[str, list[tuple] | Exception]):
    """A stand-in for the engine: each query's rows, looked up by a fragment of the query text."""
    asked: list[str] = []

    def dependencies(texts: list[str]) -> list[list[tuple] | str]:
        asked.extend(texts)
        out = []
        for text in texts:
            answer = next((a for fragment, a in answers.items() if fragment in text), [])
            out.append(str(answer) if isinstance(answer, Exception) else answer)
        return out

    return dependencies, asked


def _found(dax) -> set[tuple[Kind, str, str]]:
    return {(e.kind, e.identifier, e.source) for e in dax.evidence}


class TestEngineDaxEvidence:
    def test_measures_from_the_first_pass_tables_and_columns_from_the_masked_second(self):
        given = (
            "a rule on [Running Total] <= COUNTROWS('MarvelFact'), where the engine also lists the columns "
            "the measure uses internally (MarvelFact[DateID], DateDim[DateID])"
        )
        should = "credit the measure and MarvelFact, ask again with the measure masked, and credit nothing it uses"
        plan = plan_contract(_contract("[Running Total] <= COUNTROWS('MarvelFact')"), pql_assert="0.9")
        unmasked = [
            ("FUNCTION", None, "PQL.Assert.ShouldEqual"),
            ("MEASURE", "MarvelFact", "Running Total"),
            ("TABLE", "MarvelFact", "MarvelFact"),
            ("COLUMN", "MarvelFact", ROW_NUMBER),
            ("COLUMN", "MarvelFact", "DateID"),
            ("TABLE", "DateDim", "DateDim"),
            ("COLUMN", "DateDim", "DateID"),
        ]
        masked = [("FUNCTION", None, "PQL.Assert.ShouldEqual"), ("TABLE", "MarvelFact", "MarvelFact"), ("COLUMN", "MarvelFact", ROW_NUMBER)]
        dependencies, asked = _engine({"BLANK() <=": masked, "[Running Total] <=": unmasked})

        dax = engine_dax_evidence(plan, MODEL, dependencies)

        # Asked: a probe and the rule (one round trip), then the masked rule.
        assert (_found(dax), len(asked), "BLANK() <= COUNTROWS('MarvelFact')" in asked[-1]) == (
            {(Kind.MEASURE, "MarvelFact[Running Total]", ENGINE), (Kind.TABLE, "MarvelFact", ENGINE)},
            3,
            True,
        ), f"{given}: {should}"

    def test_a_rule_the_engine_cannot_analyse_falls_back_to_the_scan(self):
        given = "the engine raising an error for one rule's DAX"
        should = "credit that rule's references from the text scan and say the engine could not analyse it"
        plan = plan_contract(_contract("COUNTROWS('MarvelFact') > 0"), pql_assert="0.9")
        dependencies, _ = _engine({"COUNTROWS": RuntimeError("syntax error")})

        dax = engine_dax_evidence(plan, MODEL, dependencies)

        assert (_found(dax), [u.rule_id for u in dax.unresolved], dax.unavailable) == (
            {(Kind.TABLE, "MarvelFact", SCAN)},
            ["r"],
            (),
        ), f"{given}: {should}"

    def test_every_rule_failing_is_reported_as_unavailable_not_as_zero(self):
        given = "the engine refusing every query (no write permission on the model)"
        should = "say the engine check is unavailable with the reason, and still credit the text scan's references"
        plan = plan_contract(_contract("COUNTROWS('MarvelFact') > 0"), pql_assert="0.9")
        dependencies, _ = _engine({"": PermissionError("needs write permission")})

        dax = engine_dax_evidence(plan, MODEL, dependencies)

        assert (_found(dax), any("needs write permission" in u for u in dax.unavailable)) == (
            {(Kind.TABLE, "MarvelFact", SCAN)},
            True,
        ), f"{given}: {should}"


class TestBatchedDependencies:
    @staticmethod
    def _rows(*rows):
        return [{"[rule]": i, "[type]": t, "[table]": tb, "[object]": o} for i, t, tb, o in rows]

    def test_one_round_trip_labelled_by_rule(self):
        given = "two texts"
        should = "send one query and split its rows back to each text by the rule label"
        sent = []

        def query(dax):
            sent.append(dax)
            return self._rows((1, "TABLE", "B", "B"), (0, "TABLE", "A", "A"))

        found = batched_dependencies(query, ["EVALUATE {1}", "EVALUATE {2}"])

        assert (len(sent), found) == (1, [[("TABLE", "A", "A")], [("TABLE", "B", "B")]]), f"{given}: {should}"

    def test_a_failing_batch_is_retried_one_text_at_a_time(self):
        given = "a batch the engine rejects because one text is bad"
        should = "ask again per text, so the good text still gets its rows and the bad one its error"

        def query(dax):
            if "UNION" in dax or "bad" in dax:
                raise RuntimeError("cannot analyse bad")
            return [{"[REFERENCED_OBJECT_TYPE]": "TABLE", "[REFERENCED_TABLE]": "A", "[REFERENCED_OBJECT]": "A"}]

        found = batched_dependencies(query, ["EVALUATE {good}", "EVALUATE {bad}"])

        assert (found[0], "cannot analyse bad" in found[1]) == ([("TABLE", "A", "A")], True), f"{given}: {should}"

    @pytest.mark.parametrize("texts", [[], ["EVALUATE {1}"] * 3])
    def test_large_and_empty_inputs(self, texts):
        given = f"{len(texts)} text(s)"
        should = "return one result per text"

        found = batched_dependencies(lambda _dax: [], texts)

        assert len(found) == len(texts), f"{given}: {should}"


class TestLiveInventory:
    @staticmethod
    def _query(dax: str) -> list[dict]:
        """INFO rows shaped like SampleModel's (2026-11-16), for a fact table, a measure table, and a calculation group."""
        if "INFO.TABLES" in dax:
            return [
                {"[ID]": 10, "[Name]": "Sales", "[CalculationGroupID]": None},
                {"[ID]": 11, "[Name]": "_Measures", "[CalculationGroupID]": None},
                {"[ID]": 12, "[Name]": "Time Calc", "[CalculationGroupID]": 1},
            ]
        if "INFO.COLUMNS" in dax:
            return [
                {"[TableID]": 10, "[ExplicitName]": ROW_NUMBER, "[Type]": 3, "[ExplicitDataType]": 6, "[IsHidden]": True},
                {"[TableID]": 10, "[ExplicitName]": "Amount", "[Type]": 1, "[ExplicitDataType]": 8, "[IsHidden]": False},
                {"[TableID]": 10, "[ExplicitName]": "Band", "[Type]": 2, "[ExplicitDataType]": 2, "[IsHidden]": False},
                {"[TableID]": 11, "[ExplicitName]": "Placeholder", "[Type]": 1, "[ExplicitDataType]": 2, "[IsHidden]": True},
                {"[TableID]": 12, "[ExplicitName]": "Name", "[Type]": 1, "[ExplicitDataType]": 2, "[IsHidden]": False},
            ]
        if "INFO.MEASURES" in dax:
            return [{"[TableID]": 10, "[Name]": "Total"}, {"[TableID]": 11, "[Name]": "Now"}]
        return []

    def test_reads_the_model_like_the_tmdl_inventory(self):
        given = "INFO rows with a RowNumber column, a calculated column, a measure table, and a calculation group"
        should = (
            "count the data and calculated columns with their TMDL types, both measures, and only the fact table; "
            "leave out RowNumber, the measure table, and the calculation group"
        )
        from pql_test.odcs.coverage_live import live_inventory

        inventory = live_inventory(self._query)

        objects = {(o.kind, o.identifier, o.calculated, o.data_type) for o in inventory.objects}
        assert (objects, sorted(e.identifier for e in inventory.excluded if e.kind is Kind.TABLE)) == (
            {
                (Kind.TABLE, "Sales", False, None),
                (Kind.COLUMN, "Sales[Amount]", False, "double"),
                (Kind.COLUMN, "Sales[Band]", True, "string"),
                (Kind.MEASURE, "Sales[Total]", False, None),
                (Kind.MEASURE, "_Measures[Now]", False, None),
            },
            ["Time Calc", "_Measures"],
        ), f"{given}: {should}"
