"""
Unit tests for [python/pql_test/runner/coverage_collector.py](../pql_test/runner/coverage_collector.py).

All XMLA calls are mocked via the ``pql_test.runner`` package bridge (same
pattern as test_pql_test_runner.py) -- no live connection required. See
tasks/direct-udf-code-coverage-metadata-contract.md for the live-model
evidence this collector's queries are built from.
"""

from __future__ import annotations

from unittest.mock import patch

from pql_test.runner.coverage import CoverageObjectType
from pql_test.runner.coverage_collector import collect_coverage
from pql_test.runner.models import PqlTest, ResolvedXmlaConnection

_CONN = ResolvedXmlaConnection(server="localhost:9999", catalog="")

_TABLES = [{"ID": "10", "Name": "MarvelFact"}, {"ID": "13", "Name": "DateDim"}]
_COLUMNS = [
    # Type 1 = plain data column (never eligible); Type 2 = calculated column
    {"ID": "1", "TableID": "13", "ExplicitName": "Month Year", "Type": "2"},
    {"ID": "2", "TableID": "10", "ExplicitName": "ID", "Type": "1"},
]
_MEASURES = [{"ID": "1", "TableID": "10", "Name": "Number of Characters"}]
_PARTITIONS = [{"ID": "1", "TableID": "10", "Name": "MarvelFact-guid"}]
_ROLES = [{"ID": "1", "Name": "West"}]
_RELATIONSHIPS_VIEW = [
    {
        "ID": "34",
        "FromTable": "MarvelFact",
        "FromColumn": "DateID",
        "ToTable": "DateDim",
        "ToColumn": "DateID",
    }
]
_UDFS = [
    {
        "Name": "Schema.DEV.Tests",
        "Expression": (
            '() => PQL.Assert.Relationship.ShouldExist('
            '"rel exists", "MarvelFact", "DateID", "DateDim", "DateID")'
        ),
    },
]


def _calcdep_row(object_name, ref_type, ref_table, ref_object, object_type="FUNCTION"):
    return {
        "OBJECT_TYPE": object_type,
        "OBJECT": object_name,
        "REFERENCED_OBJECT_TYPE": ref_type,
        "REFERENCED_TABLE": ref_table,
        "REFERENCED_OBJECT": ref_object,
    }


def _fake_execute(overrides=None):
    """Route EVALUATE queries to fixture rows by substring match."""
    overrides = overrides or {}

    def _execute(conn, query):
        for needle, rows in overrides.items():
            if needle in query:
                return rows
        table = {
            "INFO.TABLES": _TABLES,
            "INFO.COLUMNS": _COLUMNS,
            "INFO.MEASURES": _MEASURES,
            "INFO.PARTITIONS": _PARTITIONS,
            "INFO.ROLES": _ROLES,
            "INFO.VIEW.RELATIONSHIPS": _RELATIONSHIPS_VIEW,
            "INFO.USERDEFINEDFUNCTIONS": _UDFS,
            "INFO.CALCDEPENDENCY": [],
        }
        for needle, rows in table.items():
            if needle in query:
                return rows
        raise AssertionError(f"unexpected query: {query}")

    return _execute


class TestCollectCoverage:
    def test_given_no_discovered_tests_should_return_zero_coverage_with_every_eligible_object_uncovered(
        self,
    ):
        with patch("pql_test.runner.retrieve_tests", return_value=[]), patch(
            "pql_test.runner._execute_dax_query", side_effect=_fake_execute()
        ):
            report = collect_coverage(
                "local/SampleModel", connection=_CONN, connection_pre_resolved=True
            )

        assert report is not None
        assert report.test_count == 0
        assert report.result.covered == ()
        gap_identifiers = {(g.object_type, g.identifier) for g in report.result.gaps}
        assert (CoverageObjectType.TABLE, "MarvelFact") in gap_identifiers
        assert (CoverageObjectType.CALC_COLUMN, "DateDim[Month Year]") in gap_identifiers
        assert (CoverageObjectType.MEASURE, "MarvelFact[Number of Characters]") in gap_identifiers
        assert (CoverageObjectType.ROLE, "West") in gap_identifiers
        assert (
            CoverageObjectType.RELATIONSHIP,
            "MarvelFact[DateID]->DateDim[DateID]",
        ) in gap_identifiers
        # Plain (non-calculated) columns are never eligible -- only CALC_COLUMN is a requested category
        assert not any(g.identifier == "MarvelFact[ID]" for g in report.result.gaps)

    def test_given_a_direct_calcdependency_edge_from_a_discovered_test_should_mark_the_table_covered(
        self,
    ):
        tests = [PqlTest(name="DataQuality.DEV.Tests", file_path="", source="")]
        calcdep = [_calcdep_row("DataQuality.DEV.Tests", "TABLE", "MarvelFact", "MarvelFact")]

        with patch("pql_test.runner.retrieve_tests", return_value=tests), patch(
            "pql_test.runner._execute_dax_query",
            side_effect=_fake_execute({"INFO.CALCDEPENDENCY": calcdep}),
        ):
            report = collect_coverage(
                "local/SampleModel", connection=_CONN, connection_pre_resolved=True
            )

        covered = {(e.object_type, e.identifier): e.test_names for e in report.result.covered}
        assert covered[(CoverageObjectType.TABLE, "MarvelFact")] == ("DataQuality.DEV.Tests",)

    def test_given_a_calcdependency_edge_to_a_calculated_column_should_mark_it_covered(self):
        tests = [PqlTest(name="Calcs.DEV.Tests", file_path="", source="")]
        calcdep = [
            _calcdep_row("Calcs.DEV.Tests", "CALC_COLUMN", "DateDim", "Month Year")
        ]

        with patch("pql_test.runner.retrieve_tests", return_value=tests), patch(
            "pql_test.runner._execute_dax_query",
            side_effect=_fake_execute({"INFO.CALCDEPENDENCY": calcdep}),
        ):
            report = collect_coverage(
                "local/SampleModel", connection=_CONN, connection_pre_resolved=True
            )

        covered_ids = {(e.object_type, e.identifier) for e in report.result.covered}
        assert (CoverageObjectType.CALC_COLUMN, "DateDim[Month Year]") in covered_ids

    def test_given_duplicate_evidence_from_two_tests_should_count_the_object_once_with_both_test_names(
        self,
    ):
        tests = [
            PqlTest(name="DataQuality.DEV.Tests", file_path="", source=""),
            PqlTest(name="Calcs.DEV.Tests", file_path="", source=""),
        ]
        calcdep = [
            _calcdep_row("DataQuality.DEV.Tests", "TABLE", "MarvelFact", "MarvelFact"),
            _calcdep_row("Calcs.DEV.Tests", "TABLE", "MarvelFact", "MarvelFact"),
        ]

        with patch("pql_test.runner.retrieve_tests", return_value=tests), patch(
            "pql_test.runner._execute_dax_query",
            side_effect=_fake_execute({"INFO.CALCDEPENDENCY": calcdep}),
        ):
            report = collect_coverage(
                "local/SampleModel", connection=_CONN, connection_pre_resolved=True
            )

        matches = [
            e
            for e in report.result.covered
            if e.object_type == CoverageObjectType.TABLE and e.identifier == "MarvelFact"
        ]
        assert len(matches) == 1
        assert set(matches[0].test_names) == {"DataQuality.DEV.Tests", "Calcs.DEV.Tests"}

    def test_given_a_test_udfs_role_name_matching_a_model_role_should_mark_the_role_covered(
        self,
    ):
        tests = [
            PqlTest(
                name="RLS.ANY.Tests", file_path="", source="", role_name="West"
            )
        ]

        with patch("pql_test.runner.retrieve_tests", return_value=tests), patch(
            "pql_test.runner._execute_dax_query", side_effect=_fake_execute()
        ):
            report = collect_coverage(
                "local/SampleModel", connection=_CONN, connection_pre_resolved=True
            )

        covered = {(e.object_type, e.identifier): e.test_names for e in report.result.covered}
        assert covered[(CoverageObjectType.ROLE, "West")] == ("RLS.ANY.Tests",)

    def test_given_a_relationship_shouldexist_call_in_a_tests_expression_should_mark_the_relationship_covered(
        self,
    ):
        tests = [PqlTest(name="Schema.DEV.Tests", file_path="", source="")]

        with patch("pql_test.runner.retrieve_tests", return_value=tests), patch(
            "pql_test.runner._execute_dax_query", side_effect=_fake_execute()
        ):
            report = collect_coverage(
                "local/SampleModel", connection=_CONN, connection_pre_resolved=True
            )

        covered = {(e.object_type, e.identifier): e.test_names for e in report.result.covered}
        assert covered[
            (CoverageObjectType.RELATIONSHIP, "MarvelFact[DateID]->DateDim[DateID]")
        ] == ("Schema.DEV.Tests",)

    def test_partitions_are_always_excluded_with_a_reason_never_covered_or_a_gap(self):
        with patch("pql_test.runner.retrieve_tests", return_value=[]), patch(
            "pql_test.runner._execute_dax_query", side_effect=_fake_execute()
        ):
            report = collect_coverage(
                "local/SampleModel", connection=_CONN, connection_pre_resolved=True
            )

        assert not any(
            e.object_type == CoverageObjectType.PARTITION
            for e in report.result.covered + report.result.gaps
        )
        excluded = [
            e for e in report.result.excluded if e.object_type == CoverageObjectType.PARTITION
        ]
        assert len(excluded) == 1
        assert excluded[0].reason

    def test_given_calcdependency_query_failure_should_report_table_calc_column_and_measure_unavailable_not_zero_coverage(
        self,
    ):
        def _boom(conn, query):
            if "INFO.CALCDEPENDENCY" in query:
                raise RuntimeError("XMLA timeout")
            return _fake_execute()(conn, query)

        with patch("pql_test.runner.retrieve_tests", return_value=[]), patch(
            "pql_test.runner._execute_dax_query", side_effect=_boom
        ):
            report = collect_coverage(
                "local/SampleModel", connection=_CONN, connection_pre_resolved=True
            )

        unavailable_types = {u.object_type for u in report.unavailable}
        assert CoverageObjectType.TABLE in unavailable_types
        assert CoverageObjectType.CALC_COLUMN in unavailable_types
        assert CoverageObjectType.MEASURE in unavailable_types
        # Those categories must not silently show up as gaps/zero-coverage
        assert not any(
            g.object_type in (CoverageObjectType.TABLE, CoverageObjectType.CALC_COLUMN, CoverageObjectType.MEASURE)
            for g in report.result.gaps
        )

    def test_given_relationship_inventory_succeeds_but_expression_text_query_fails_should_report_unavailable_not_gaps(
        self,
    ):
        def _boom(conn, query):
            if "INFO.USERDEFINEDFUNCTIONS" in query:
                raise RuntimeError("XMLA timeout")
            return _fake_execute()(conn, query)

        with patch("pql_test.runner.retrieve_tests", return_value=[]), patch(
            "pql_test.runner._execute_dax_query", side_effect=_boom
        ):
            report = collect_coverage(
                "local/SampleModel", connection=_CONN, connection_pre_resolved=True
            )

        unavailable_types = {u.object_type for u in report.unavailable}
        assert CoverageObjectType.RELATIONSHIP in unavailable_types
        assert not any(
            g.object_type == CoverageObjectType.RELATIONSHIP for g in report.result.gaps
        )
        assert not any(
            e.object_type == CoverageObjectType.RELATIONSHIP for e in report.result.covered
        )

    def test_given_info_tables_query_fails_should_report_dependent_categories_unavailable_not_gaps(
        self,
    ):
        def _boom(conn, query):
            if "INFO.TABLES" in query:
                raise RuntimeError("XMLA timeout")
            return _fake_execute()(conn, query)

        with patch("pql_test.runner.retrieve_tests", return_value=[]), patch(
            "pql_test.runner._execute_dax_query", side_effect=_boom
        ):
            report = collect_coverage(
                "local/SampleModel", connection=_CONN, connection_pre_resolved=True
            )

        unavailable_types = {u.object_type for u in report.unavailable}
        for expected in (
            CoverageObjectType.TABLE,
            CoverageObjectType.CALC_COLUMN,
            CoverageObjectType.MEASURE,
            CoverageObjectType.PARTITION,
        ):
            assert expected in unavailable_types, f"{expected} should be unavailable"
        assert not any(
            g.object_type
            in (
                CoverageObjectType.TABLE,
                CoverageObjectType.CALC_COLUMN,
                CoverageObjectType.MEASURE,
                CoverageObjectType.PARTITION,
            )
            for g in report.result.gaps
        )

    def test_given_no_live_connection_should_return_none(self):
        with patch("pql_test.runner.resolve_xmla_connection", return_value=None):
            report = collect_coverage("local/NoSuchModel")

        assert report is None
