# SPDX-License-Identifier: AGPL-3.0-only
"""Unit tests for pql_test.odcs.ir and pql_test.odcs.catalog."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from pql_test.odcs.catalog import CatalogError, load_catalog
from pql_test.odcs.ir import Assertion, RuleOutcome, Status, Target

SRC = Path(__file__).resolve().parents[2] / "pql_test" / "odcs"


class TestIR:
    def test_assertions_are_immutable(self):
        given = "an IR assertion"
        should = "reject attribute assignment (frozen dataclass)"
        a = Assertion(rule_id="r", suite="Schema", op="tbl.exists", target=Target("T"), args={}, description="d")

        with pytest.raises(AttributeError) as exc:
            a.op = "other"  # type: ignore[misc]

        assert exc.type is not None, f"{given}: {should}"

    def test_dedupe_key_ignores_the_source_rule(self):
        given = "two assertions with the same op, target, args, and severity from different rules"
        should = "share a dedupe key so they collapse into one DAX call"
        a = Assertion("r1", "DataQuality", "col.distinct", Target("T", "C"), {}, "a")
        b = Assertion("r2", "DataQuality", "col.distinct", Target("T", "C"), {}, "b")

        assert a.dedupe_key() == b.dedupe_key(), f"{given}: {should}"

    def test_skipped_outcome_needs_a_reason(self):
        given = "a SKIPPED outcome without a reason"
        should = "be rejected, so nothing is dropped silently"

        with pytest.raises(ValueError) as exc:
            RuleOutcome(rule_id="r", status=Status.SKIPPED, assertions=())

        assert "reason" in str(exc.value), f"{given}: {should}"


class TestCatalog:
    def test_declares_the_minimum_pql_assert_version(self):
        given = "the bundled PQL.Assert 0.7 catalog"
        should = "declare min_version 0.7.1"

        assert load_catalog().min_version == "0.7.1", f"{given}: {should}"

    def test_resolves_an_op_to_function_and_argument_order(self):
        given = "the tbl.row_count op"
        should = "resolve to Tbl.ShouldHaveRowCount with the table before the count (PQL.Assert 0.7.1)"

        spec = load_catalog().op("tbl.row_count")

        assert (spec.fn, spec.args) == (
            "PQL.Assert.Tbl.ShouldHaveRowCount",
            ("testName", "tableRef", "count"),
        ), f"{given}: {should}"

    def test_unknown_op_names_the_op_and_catalog_version(self):
        given = "an IR op missing from the catalog"
        should = "raise CatalogError naming the op and the catalog version"

        with pytest.raises(CatalogError) as exc:
            load_catalog().op("col.not_a_thing")

        assert ("col.not_a_thing" in str(exc.value), "0.7.1" in str(exc.value)) == (True, True), f"{given}: {should}"

    def test_python_source_never_names_pql_assert_functions(self):
        given = "every Python module in pql_test.odcs"
        should = "contain no PQL.Assert function names; they live only in the catalog YAML"
        offenders = []
        for path in SRC.rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                is_str = isinstance(node, ast.Constant) and isinstance(node.value, str)
                if is_str and re.search(r"PQL\.Assert\.[A-Z]", node.value):
                    offenders.append(f"{path.name}: {node.value}")

        assert offenders == [], f"{given}: {should}"
