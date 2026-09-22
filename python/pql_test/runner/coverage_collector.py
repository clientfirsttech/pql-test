"""
XMLA-backed direct test-UDF coverage collection.

Retrieves the discovered test-UDF set, inventories eligible model objects
across the epic's six categories (tables, calculated columns, measures,
relationships, partitions, roles), and produces normalized
``CoverageEvidence`` / ``ExclusionRecord`` inputs for
:func:`pql_test.runner.coverage.classify_coverage`.

See tasks/direct-udf-code-coverage-metadata-contract.md for the verified
per-category XMLA metadata source this module implements:

- TABLE / CALC_COLUMN / MEASURE — direct ``INFO.CALCDEPENDENCY()`` edges
  from a discovered test UDF (``OBJECT_TYPE = "FUNCTION"``, ``OBJECT`` in
  the discovered test-name set).
- ROLE — a discovered test UDF's ``PQLAssert_RoleName`` annotation
  (already surfaced by ``retrieve_tests``/``PQL.Assert.RetrieveTestsV2()``)
  matched against the model's role inventory.
- RELATIONSHIP — the string-literal arguments of a
  ``PQL.Assert.Relationship.ShouldExist(...)`` call parsed out of the test
  UDF's own DAX expression text, matched against
  ``INFO.VIEW.RELATIONSHIPS()``.
- PARTITION — no PQL.Assert helper targets partitions, so every partition
  is always excluded with a reason rather than counted covered/uncovered.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from pql_test.runner.coverage import (
    ClassificationResult,
    CoverageEvidence,
    CoverageObjectType,
    EligibleObject,
    ExclusionRecord,
    classify_coverage,
)
from pql_test.runner.models import (
    PqlTest,
    ResolvedXmlaConnection,
    XmlaConnectionOptions,
)

if TYPE_CHECKING:
    from pql_test.runner.discovery import retrieve_tests
    from pql_test.runner.resolver import resolve_xmla_connection
    from pql_test.runner.xmla import _execute_dax_query, _get_col
else:
    # Import at runtime through runner package to enable test mocking,
    # matching the pattern used by discovery.py / execution.py.
    from pql_test import runner

    retrieve_tests = lambda *args, **kw: runner.retrieve_tests(*args, **kw)
    resolve_xmla_connection = lambda *args: runner.resolve_xmla_connection(*args)
    _execute_dax_query = lambda *args: runner._execute_dax_query(*args)
    _get_col = lambda *args: runner._get_col(*args)

__all__ = ["CoverageReport", "UnavailableCategory", "collect_coverage"]

_RELATIONSHIP_CALL_RE = re.compile(
    r'PQL\.Assert\.Relationship\.ShouldExist\s*\(\s*"[^"]*"\s*,\s*'
    r'"([^"]*)"\s*,\s*"([^"]*)"\s*,\s*"([^"]*)"\s*,\s*"([^"]*)"\s*\)',
    re.IGNORECASE,
)

_CALCULATED_COLUMN_TYPES = {"2", "4"}  # TOM ColumnType: 2=Calculated, 4=CalculatedTableColumn
_TABLE_REF_TYPES = {"TABLE", "CALC_TABLE"}
_PARTITION_EXCLUSION_REASON = (
    "no PQL.Assert helper targets partitions "
    "(see tasks/direct-udf-code-coverage-metadata-contract.md)"
)


@dataclass(frozen=True)
class UnavailableCategory:
    """A category whose XMLA metadata source could not be queried."""

    object_type: CoverageObjectType
    reason: str


@dataclass(frozen=True)
class CoverageReport:
    """Full direct-coverage result for one model."""

    model_path: str
    test_count: int
    result: ClassificationResult
    unavailable: tuple[UnavailableCategory, ...]


def _safe_query(
    connection: ResolvedXmlaConnection,
    query: str,
    category: CoverageObjectType,
    unavailable: list[UnavailableCategory],
) -> Optional[list[dict]]:
    try:
        return _execute_dax_query(connection, query)
    except Exception as exc:  # noqa: BLE001
        unavailable.append(
            UnavailableCategory(category, f"{type(exc).__name__}: {str(exc)[:300]}")
        )
        return None


def _dedup_evidence(
    triples: list[tuple[CoverageObjectType, str, str]]
) -> list[CoverageEvidence]:
    grouped: dict[tuple[CoverageObjectType, str], list[str]] = {}
    for object_type, identifier, test_name in triples:
        names = grouped.setdefault((object_type, identifier), [])
        if test_name not in names:
            names.append(test_name)
    return [
        CoverageEvidence(object_type, identifier, tuple(sorted(names)))
        for (object_type, identifier), names in grouped.items()
    ]


def collect_coverage(
    model_path: str,
    conn_opts: Optional[XmlaConnectionOptions] = None,
    connection: Optional[ResolvedXmlaConnection] = None,
    *,
    connection_pre_resolved: bool = False,
) -> Optional[CoverageReport]:
    """
    Collect direct test-UDF coverage evidence for *model_path*.

    Reuses the same connection-resolution and test-discovery path as
    ``run_tests_from_model`` -- no secrets are read from files here.
    Returns ``None`` when no XMLA connection can be resolved.
    """
    if conn_opts is None:
        conn_opts = XmlaConnectionOptions()
    if connection is None and not connection_pre_resolved:
        connection = resolve_xmla_connection(model_path, conn_opts)
    if connection is None:
        return None

    tests: list[PqlTest] = retrieve_tests(model_path, connection=connection)
    test_names = {t.name for t in tests}

    unavailable: list[UnavailableCategory] = []
    eligible: list[EligibleObject] = []
    exclusions: list[ExclusionRecord] = []
    evidence_triples: list[tuple[CoverageObjectType, str, str]] = []

    # --- Tables (also the table-name lookup other categories join against) ---
    table_rows = _safe_query(connection, "EVALUATE INFO.TABLES()", CoverageObjectType.TABLE, unavailable)
    table_names_by_id: dict[str, str] = {}
    if table_rows is not None:
        for row in table_rows:
            table_id = _get_col(row, "ID")
            name = _get_col(row, "Name")
            table_names_by_id[table_id] = name
            eligible.append(EligibleObject(CoverageObjectType.TABLE, name))

    # --- Calculated columns ---
    column_rows = _safe_query(
        connection, "EVALUATE INFO.COLUMNS()", CoverageObjectType.CALC_COLUMN, unavailable
    )
    if column_rows is not None and table_rows is not None:
        for row in column_rows:
            if _get_col(row, "Type") not in _CALCULATED_COLUMN_TYPES:
                continue
            table_name = table_names_by_id.get(_get_col(row, "TableID"))
            if not table_name:
                continue
            col_name = _get_col(row, "ExplicitName") or _get_col(row, "InferredName")
            eligible.append(
                EligibleObject(CoverageObjectType.CALC_COLUMN, f"{table_name}[{col_name}]")
            )
    elif column_rows is not None and table_rows is None:
        unavailable.append(
            UnavailableCategory(
                CoverageObjectType.CALC_COLUMN, "table names unavailable (INFO.TABLES() failed)"
            )
        )

    # --- Measures ---
    measure_rows = _safe_query(
        connection, "EVALUATE INFO.MEASURES()", CoverageObjectType.MEASURE, unavailable
    )
    if measure_rows is not None and table_rows is not None:
        for row in measure_rows:
            table_name = table_names_by_id.get(_get_col(row, "TableID"))
            if not table_name:
                continue
            eligible.append(
                EligibleObject(
                    CoverageObjectType.MEASURE, f"{table_name}[{_get_col(row, 'Name')}]"
                )
            )
    elif measure_rows is not None and table_rows is None:
        unavailable.append(
            UnavailableCategory(
                CoverageObjectType.MEASURE, "table names unavailable (INFO.TABLES() failed)"
            )
        )

    # --- Partitions: always excluded, never evaluated for evidence ---
    partition_rows = _safe_query(
        connection, "EVALUATE INFO.PARTITIONS()", CoverageObjectType.PARTITION, unavailable
    )
    if partition_rows is not None and table_rows is not None:
        for row in partition_rows:
            table_name = table_names_by_id.get(_get_col(row, "TableID"))
            part_name = _get_col(row, "Name")
            identifier = f"{table_name}[{part_name}]" if table_name else part_name
            eligible.append(EligibleObject(CoverageObjectType.PARTITION, identifier))
            exclusions.append(
                ExclusionRecord(
                    CoverageObjectType.PARTITION, identifier, _PARTITION_EXCLUSION_REASON
                )
            )
    elif partition_rows is not None and table_rows is None:
        unavailable.append(
            UnavailableCategory(
                CoverageObjectType.PARTITION, "table names unavailable (INFO.TABLES() failed)"
            )
        )

    # --- Roles: evidence from the test UDF's own PQLAssert_RoleName annotation ---
    role_rows = _safe_query(connection, "EVALUATE INFO.ROLES()", CoverageObjectType.ROLE, unavailable)
    role_names: set[str] = set()
    if role_rows is not None:
        for row in role_rows:
            name = _get_col(row, "Name")
            role_names.add(name)
            eligible.append(EligibleObject(CoverageObjectType.ROLE, name))
    for t in tests:
        if t.role_name and t.role_name in role_names:
            evidence_triples.append((CoverageObjectType.ROLE, t.role_name, t.name))

    # --- Relationships: evidence from parsing PQL.Assert.Relationship.ShouldExist(...) calls ---
    relationship_rows = _safe_query(
        connection,
        "EVALUATE INFO.VIEW.RELATIONSHIPS()",
        CoverageObjectType.RELATIONSHIP,
        unavailable,
    )
    relationship_ids: dict[tuple[str, str, str, str], str] = {}
    if relationship_rows is not None:
        for row in relationship_rows:
            key = (
                _get_col(row, "FromTable"),
                _get_col(row, "FromColumn"),
                _get_col(row, "ToTable"),
                _get_col(row, "ToColumn"),
            )
            identifier = f"{key[0]}[{key[1]}]->{key[2]}[{key[3]}]"
            relationship_ids[key] = identifier
            eligible.append(EligibleObject(CoverageObjectType.RELATIONSHIP, identifier))

        udf_rows = _safe_query(
            connection,
            "EVALUATE INFO.USERDEFINEDFUNCTIONS()",
            CoverageObjectType.RELATIONSHIP,
            unavailable,
        )
        if udf_rows is not None:
            for row in udf_rows:
                name = _get_col(row, "Name")
                if name not in test_names:
                    continue
                expression = _get_col(row, "Expression")
                for match in _RELATIONSHIP_CALL_RE.finditer(expression):
                    key = match.groups()
                    identifier = relationship_ids.get(key)
                    if identifier:
                        evidence_triples.append((CoverageObjectType.RELATIONSHIP, identifier, name))
        else:
            # Evidence gathering failed even though the relationship inventory
            # succeeded -- drop the eligible entries so they show up only as
            # unavailable (already recorded by _safe_query), never as gaps.
            eligible = [e for e in eligible if e.object_type != CoverageObjectType.RELATIONSHIP]

    # --- Direct INFO.CALCDEPENDENCY() edges from a discovered test UDF ---
    try:
        calcdep_rows: Optional[list[dict]] = _execute_dax_query(
            connection, "EVALUATE INFO.CALCDEPENDENCY()"
        )
    except Exception as exc:  # noqa: BLE001
        calcdep_rows = None
        cause = f"{type(exc).__name__}: {str(exc)[:300]}"
        for object_type in (
            CoverageObjectType.TABLE,
            CoverageObjectType.CALC_COLUMN,
            CoverageObjectType.MEASURE,
        ):
            unavailable.append(
                UnavailableCategory(
                    object_type,
                    f"INFO.CALCDEPENDENCY() query failed; direct-edge evidence unavailable: {cause}",
                )
            )
        eligible = [
            e
            for e in eligible
            if e.object_type
            not in (
                CoverageObjectType.TABLE,
                CoverageObjectType.CALC_COLUMN,
                CoverageObjectType.MEASURE,
            )
        ]
    else:
        for row in calcdep_rows:
            if _get_col(row, "OBJECT_TYPE") != "FUNCTION":
                continue
            object_name = _get_col(row, "OBJECT")
            if object_name not in test_names:
                continue
            ref_type = _get_col(row, "REFERENCED_OBJECT_TYPE")
            ref_table = _get_col(row, "REFERENCED_TABLE")
            ref_object = _get_col(row, "REFERENCED_OBJECT")
            if ref_type in _TABLE_REF_TYPES:
                evidence_triples.append((CoverageObjectType.TABLE, ref_object, object_name))
            elif ref_type == "CALC_COLUMN":
                evidence_triples.append(
                    (CoverageObjectType.CALC_COLUMN, f"{ref_table}[{ref_object}]", object_name)
                )
            elif ref_type == "MEASURE":
                evidence_triples.append(
                    (CoverageObjectType.MEASURE, f"{ref_table}[{ref_object}]", object_name)
                )

    result = classify_coverage(eligible, _dedup_evidence(evidence_triples), exclusions)
    return CoverageReport(
        model_path=model_path,
        test_count=len(tests),
        result=result,
        unavailable=tuple(unavailable),
    )
