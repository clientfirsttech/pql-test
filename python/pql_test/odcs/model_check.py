# SPDX-License-Identifier: AGPL-3.0-only
"""Contract entries the model does not match: tables, columns, data types, and relationships.

``lint CONTRACT MODEL_PATH`` reports these as problems; ``contract coverage`` reports them as
what to fix or remove in the contract. The model is given as plain names, so the same checks
run against a PBIP folder's TMDL or a connected model.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING

from pql_test.odcs.datatypes import tmdl_model_type
from pql_test.odcs.mapping.context import is_column
from pql_test.odcs.mapping.relationships import relationship_entries, resolve

if TYPE_CHECKING:
    from pql_test.odcs.api import Plan


def model_problems(
    plan: Plan,
    model: Mapping[str, Mapping[str, str | None]],
    relationships: Iterable[tuple[str, str, str, str]],
) -> list[str]:
    """Every contract table, column, type, and relationship *model* does not match.

    *model* is ``table -> {column: TMDL dataType or None}``; a None type is not checked.
    *relationships* are ``(from table, from column, to table, to column)``.
    """
    # DAX object names are case-insensitive.
    model_ci = {t.lower(): {c.lower(): dt for c, dt in cols.items()} for t, cols in model.items()}
    problems = []
    for obj in plan.contract.schema_objects:
        table = plan.names.table(obj)
        if table.lower() not in model_ci:
            problems.append(f"{obj['name']}: table {table!r} not found in model")
            continue
        for prop in obj.get("properties") or []:
            column = plan.names.column(obj, prop)
            if is_column(prop) and column.lower() not in model_ci[table.lower()]:
                problems.append(f"{obj['name']}.{prop['name']}: column {column!r} not found in model table {table!r}")
    problems.extend(_type_problems(plan, model_ci))
    problems.extend(_relationship_problems(plan, relationships))
    return problems


def _type_problems(plan: Plan, model_ci: dict) -> list[str]:
    """Type checks whose column has a different data type in the model."""
    problems = []
    for outcome in plan.outcomes:
        for a in outcome.assertions:
            if a.op != "tbl.column_type":
                continue
            tmdl = model_ci.get(a.target.table.lower(), {}).get((a.target.column or "").lower())
            actual = tmdl_model_type(tmdl) if tmdl else None
            if actual and actual not in a.args["types"]:
                expected = " or ".join(a.args["types"])
                problems.append(
                    f"{outcome.rule_id}: column {a.target.column!r} is {actual} in the model, the contract expects "
                    f"{expected} (set pbiDataType to pin another model type)"
                )
    return problems


def _relationship_problems(plan: Plan, model: Iterable[tuple[str, str, str, str]]) -> list[str]:
    """Contract relationships (any catalog) that the model does not define, from foreign key to key."""
    defined = {tuple(n.lower() for n in r) for r in model}
    problems = []
    for obj, prop, scope, index, rel in relationship_entries(plan.contract):
        found = resolve(plan.contract, plan.names, obj, prop, rel)
        if isinstance(found, str):
            continue  # reported as skipped by `mapping`
        key = tuple(n.lower() for n in found)
        if key in defined:
            continue
        where = "is defined from the key side in the model" if key[2:] + key[:2] in defined else "is not in the model"
        problems.append(
            f"{scope}.relationships[{index}]: relationship {found.from_table}[{found.from_column}] -> "
            f"{found.to_table}[{found.to_column}] {where}"
        )
    return problems
