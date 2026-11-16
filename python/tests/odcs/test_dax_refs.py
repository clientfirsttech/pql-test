# SPDX-License-Identifier: AGPL-3.0-only
"""The text scan of DAX a contract wrote: which model names it references (pql_test.odcs.dax_refs)."""

from __future__ import annotations

from pql_test.odcs.dax_refs import DaxRef, dax_references


class TestDaxReferences:
    def test_qualified_column_references(self):
        given = "a quoted and an unquoted table-qualified column, one with a space before the bracket"
        should = "return both as table + name references"

        refs = dax_references("SUM('Order Lines'[amount]) + MAX(Orders [order_date])")

        assert refs == [
            DaxRef(table="Order Lines", name="amount", quoted=True),
            DaxRef(table="Orders", name="order_date"),
        ], f"{given}: {should}"

    def test_bare_bracket_name(self):
        given = "a measure written without its table"
        should = "return a reference with a name and no table"

        assert dax_references("[Total Sales] * 2") == [DaxRef(name="Total Sales")], f"{given}: {should}"

    def test_strings_and_comments_hold_no_references(self):
        given = "names inside a string literal, a // comment, a -- comment, and a /* */ comment"
        should = "return only the reference outside them"
        text = "\"[x] 'T'[c]\" // [y]\n-- 'U'[z]\n/* [v] */ [w]"

        assert dax_references(text) == [DaxRef(name="w")], f"{given}: {should}"

    def test_table_references_but_not_functions(self):
        given = "COUNTROWS over a quoted and an unquoted table, and dotted function names"
        should = "return the two tables, never the function names"

        refs = dax_references("COUNTROWS('Sales') + COUNTROWS(Customer) + PQL.Assert.Col.Mean ( 1 )")

        assert refs == [DaxRef(table="Sales", quoted=True), DaxRef(table="Customer")], f"{given}: {should}"

    def test_escaped_quotes_and_brackets(self):
        given = "a table name with '' and a column name with ]]"
        should = "unescape both"

        assert dax_references("'O''Brien'[a]]b]") == [DaxRef(table="O'Brien", name="a]b", quoted=True)], (
            f"{given}: {should}"
        )
