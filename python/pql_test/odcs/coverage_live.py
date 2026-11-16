# SPDX-License-Identifier: AGPL-3.0-only
"""`contract coverage --live`: ask the model's engine what the contract's DAX references.

``INFO.CALCDEPENDENCY("QUERY", <dax>)`` analyses DAX the model never stores: it changes nothing
in the model (checked against SampleModel in Desktop and in the service, 2026-11-16). It answers
with a flat list, though: measures the DAX names directly, plus every table and column reached
through those measures at any depth. So each rule is asked twice:

1. its DAX as written, keeping only the measures;
2. its DAX with those measures replaced by ``BLANK()``, keeping the tables and columns.

That keeps the direct-reference rule of ``pql-test code-coverage``: a rule on a measure never
covers what the measure uses. Rules share a round trip (``UNION`` of one ``SELECTCOLUMNS`` per
rule, labelled with the rule's index, because the engine leaves its own ``[QUERY]`` column
empty). A rule the engine cannot analyse falls back to the text scan and says so.

Nothing here opens a connection: callers pass a ``query`` function, so this module imports no
XMLA code.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from pql_test.odcs.coverage import (
    ENGINE,
    DaxEvidence,
    Evidence,
    Inventory,
    Kind,
    Level,
    ModelNames,
    Unresolved,
    column_id,
    dax_rule_assertions,
    inventory_of,
    scanned_evidence,
)
from pql_test.odcs.dax_refs import mask_references
from pql_test.odcs.emit.dax import dax_string, render_call
from pql_test.odcs.pbip import ModelColumn, ModelTable

if TYPE_CHECKING:
    from pql_test.odcs.api import Plan

# One dependency row: (REFERENCED_OBJECT_TYPE, REFERENCED_TABLE, REFERENCED_OBJECT).
Row = tuple[str, "str | None", str]
# Texts per round trip: enough to make a large contract a few queries, small enough to keep each query short.
BATCH_SIZE = 50
# A query that always analyses: when even this fails, the engine check cannot run at all (no permission, say).
PROBE = "EVALUATE { 1 }"
NEEDS_WRITE = "INFO.CALCDEPENDENCY needs write permission on the model"
_TABLE_TYPES = {"TABLE", "CALC_TABLE"}
_COLUMN_TYPES = {"COLUMN", "CALC_COLUMN"}


def _cell(row: dict, name: str):
    """A row's value for column *name*, whatever bracketing the driver gave the key (``[name]``, ``T[name]``)."""
    for key, value in row.items():
        if str(key).rstrip("]").rsplit("[", 1)[-1].lower() == name.lower():
            return value
    return None


def _error(exc: Exception) -> str:
    text = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
    return text[:300]


def _single(query: Callable[[str], list[dict]], text: str) -> list[Row] | str:
    try:
        rows = query(f"EVALUATE INFO.CALCDEPENDENCY(\"QUERY\", {dax_string(text)})")
    except Exception as exc:  # noqa: BLE001 - the engine's reason is the answer for this text
        return _error(exc)
    return [(_cell(r, "REFERENCED_OBJECT_TYPE"), _cell(r, "REFERENCED_TABLE"), _cell(r, "REFERENCED_OBJECT")) for r in rows]


def _batch(query: Callable[[str], list[dict]], texts: Sequence[str]) -> list[list[Row] | str]:
    parts = [
        f'SELECTCOLUMNS(INFO.CALCDEPENDENCY("QUERY", {dax_string(t)}), "rule", {i}, '
        '"type", [REFERENCED_OBJECT_TYPE], "table", [REFERENCED_TABLE], "object", [REFERENCED_OBJECT])'
        for i, t in enumerate(texts)
    ]
    dax = parts[0] if len(parts) == 1 else "UNION(\n  " + ",\n  ".join(parts) + "\n)"
    try:
        rows = query(f"EVALUATE {dax}")
    except Exception:  # noqa: BLE001 - one bad text fails the batch: ask again one by one
        return [_single(query, t) for t in texts]
    found: list[list[Row] | str] = [[] for _ in texts]
    for r in rows:
        found[int(_cell(r, "rule"))].append((_cell(r, "type"), _cell(r, "table"), _cell(r, "object")))
    return found


def batched_dependencies(query: Callable[[str], list[dict]], texts: Sequence[str]) -> list[list[Row] | str]:
    """Each text's dependency rows, ``BATCH_SIZE`` texts per round trip; for a text the engine cannot
    analyse, the engine's error message instead."""
    found: list[list[Row] | str] = []
    for start in range(0, len(texts), BATCH_SIZE):
        found += _batch(query, texts[start : start + BATCH_SIZE])
    return found


def _rows_evidence(names: ModelNames, rows: list[Row], rule_id: str, kinds: set[Kind]) -> list[Evidence]:
    found = []
    for typ, table, obj in rows:
        if typ == "MEASURE" and Kind.MEASURE in kinds:
            found.append(Evidence(Kind.MEASURE, names.model(Kind.MEASURE, column_id(table, obj)), Level.VALUES_TESTED, rule_id, ENGINE))
        elif typ in _TABLE_TYPES and Kind.TABLE in kinds:
            found.append(Evidence(Kind.TABLE, names.model(Kind.TABLE, obj), Level.VALUES_TESTED, rule_id, ENGINE))
        elif typ in _COLUMN_TYPES and Kind.COLUMN in kinds and not str(obj).startswith("RowNumber-"):
            # Every table has a hidden RowNumber-<GUID> column; COUNTROWS reports it.
            found.append(Evidence(Kind.COLUMN, names.model(Kind.COLUMN, column_id(table, obj)), Level.VALUES_TESTED, rule_id, ENGINE))
    return found


def engine_dax_evidence(
    plan: Plan,
    inventory: Inventory,
    dependencies: Callable[[list[str]], list[list[Row] | str]],
) -> DaxEvidence:
    """What every contract-DAX rule in *plan* references, as the model's engine reads it.

    *dependencies* answers a list of DAX queries with each one's dependency rows (or an error
    message): ``functools.partial(batched_dependencies, query)`` against a connection.
    """
    names = ModelNames(inventory)
    rules = dax_rule_assertions(plan)
    if not rules:
        return DaxEvidence(())
    texts = [f"EVALUATE {render_call(a, 'coverage', plan.catalog)}" for _, a in rules]
    probe, *first = dependencies([PROBE, *texts])
    if isinstance(probe, str):
        # Not one rule's problem: the engine check cannot run here. Fall back to the text scan for all.
        evidence, unresolved = [], []
        for rule_id, a in rules:
            found, missing = scanned_evidence(names, a, rule_id)
            evidence += found
            unresolved += missing
        reason = f"the model's engine could not analyse contract DAX ({probe}); {NEEDS_WRITE}. Used the text scan instead."
        return DaxEvidence(tuple(evidence), tuple(unresolved), (reason,))

    evidence: list[Evidence] = []
    unresolved: list[Unresolved] = []
    second: list[tuple[int, str]] = []  # (rule index, masked text) for rules that reference measures
    for i, ((rule_id, a), rows) in enumerate(zip(rules, first)):
        if isinstance(rows, str):
            found, missing = scanned_evidence(names, a, rule_id)
            evidence += found
            unresolved += [*missing, Unresolved(rule_id, f"(the model could not analyse this rule's DAX: {rows}; used the text scan)")]
            continue
        evidence += _rows_evidence(names, rows, rule_id, {Kind.MEASURE})
        measures = {str(obj).lower() for typ, _, obj in rows if typ == "MEASURE"}
        if measures:
            second.append((i, mask_references(texts[i], measures)))
        else:
            evidence += _rows_evidence(names, rows, rule_id, {Kind.TABLE, Kind.COLUMN})
    for (i, _), rows in zip(second, dependencies([t for _, t in second]) if second else []):
        rule_id, a = rules[i]
        if isinstance(rows, str):
            found, missing = scanned_evidence(names, a, rule_id)
            evidence += [e for e in found if e.kind in (Kind.TABLE, Kind.COLUMN)]
            unresolved.append(Unresolved(rule_id, f"(the model could not analyse this rule's DAX without its measures: {rows}; used the text scan)"))
            continue
        evidence += _rows_evidence(names, rows, rule_id, {Kind.TABLE, Kind.COLUMN})
    return DaxEvidence(tuple(dict.fromkeys(evidence)), tuple(dict.fromkeys(unresolved)))


# INFO.COLUMNS()[Type] (TOM ColumnType) and [ExplicitDataType] (TOM DataType) codes.
_CALCULATED, _ROW_NUMBER, _CALCULATED_TABLE_COLUMN = 2, 3, 4
_TMDL_DATA_TYPES = {2: "string", 6: "int64", 8: "double", 9: "dateTime", 10: "decimal", 11: "boolean", 17: "binary"}


def _data_type(row: dict) -> str | None:
    for name in ("ExplicitDataType", "InferredDataType"):
        found = _TMDL_DATA_TYPES.get(_int(_cell(row, name)))
        if found:
            return found
    return None


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def live_inventory(query: Callable[[str], list[dict]]) -> Inventory:
    """The connected model's tables, columns, measures, and relationships, read from its INFO functions,
    with the same exclusions as the TMDL inventory. Raises when the model refuses an INFO query."""
    tables: dict[int, dict] = {}
    for row in query("EVALUATE INFO.TABLES()"):
        tables[_int(_cell(row, "ID"))] = {
            "name": _cell(row, "Name"),
            "calculation_group": _cell(row, "CalculationGroupID") is not None,
            "columns": [],
            "measures": [],
        }
    for row in query("EVALUATE INFO.COLUMNS()"):
        table, kind = tables.get(_int(_cell(row, "TableID"))), _int(_cell(row, "Type"))
        if table is None or kind == _ROW_NUMBER:
            continue
        name = _cell(row, "ExplicitName") or _cell(row, "InferredName")
        calculated = kind in (_CALCULATED, _CALCULATED_TABLE_COLUMN)
        table["columns"].append(ModelColumn(name, _data_type(row), bool(_cell(row, "IsHidden")), calculated))
    for row in query("EVALUATE INFO.MEASURES()"):
        table = tables.get(_int(_cell(row, "TableID")))
        if table is not None:
            table["measures"].append(_cell(row, "Name"))
    relationships = sorted(
        (_cell(r, "FromTable"), _cell(r, "FromColumn"), _cell(r, "ToTable"), _cell(r, "ToColumn"))
        for r in query("EVALUATE INFO.VIEW.RELATIONSHIPS()")
    )
    model = [
        ModelTable(
            t["name"],
            tuple(t["columns"]),
            tuple(t["measures"]),
            calculated=any(c.calculated for c in t["columns"]) and all(c.calculated for c in t["columns"]),
            calculation_group=t["calculation_group"],
        )
        for t in sorted(tables.values(), key=lambda t: str(t["name"]).lower())
    ]
    return inventory_of(model, relationships)
