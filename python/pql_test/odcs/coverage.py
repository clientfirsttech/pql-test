# SPDX-License-Identifier: AGPL-3.0-only
"""`pql-test contract coverage`: which model objects a contract covers.

Every table, column, relationship, and measure in the model is counted once, at one level:

- **values tested**: a rule that checks the object's data runs (a DataQuality, RefreshAge, or
  ContractDax assertion targets or references it);
- **listed**: the contract lists it and a schema check runs (the table exists, has the column,
  the column has its type, the relationship exists);
- **listed, not enforced**: the contract lists it, but every rule on it is skipped;
- **not covered**: nothing in the contract names it.

Only direct references count, as in ``pql-test code-coverage``: a rule on a measure does not
cover what that measure uses. The model's objects come from its TMDL; nothing here connects
to a model or writes to one.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from enum import Enum, IntEnum
from pathlib import Path
from typing import TYPE_CHECKING

from pql_test.odcs.dax_refs import DaxRef, dax_references
from pql_test.odcs.ir import CONTRACT_DAX_SUITE, DIRECT_CALL, SCHEMA_SUITE, Assertion, Status
from pql_test.odcs.mapping.context import is_column
from pql_test.odcs.mapping.relationships import relationship_entries, resolve
from pql_test.odcs.pbip import AUTO_DATE_TABLE_RE, ModelTable, model_relationships, model_tables

if TYPE_CHECKING:
    from pql_test.odcs.api import Plan


class Kind(str, Enum):
    """The model object categories `contract coverage` counts."""

    TABLE = "TABLE"
    COLUMN = "COLUMN"
    RELATIONSHIP = "RELATIONSHIP"
    MEASURE = "MEASURE"


AUTO_DATE_TABLE = "Power BI's automatic date table, not part of the model anyone wrote"
MEASURE_TABLE = "a measure table: it holds measures (counted on their own) and only hidden placeholder columns"
CALCULATION_GROUP = "a calculation group: no contract rule targets one"
NOT_COUNTED = (
    "Roles, partitions, and calculation groups are not counted: an ODCS contract has no rule that targets them."
)


@dataclass(frozen=True)
class ModelObject:
    """One counted model object. *identifier* is ``Table``, ``Table[Column]``, ``Table[Measure]``,
    or ``From[column]->To[column]``, in the model's spelling."""

    kind: Kind
    identifier: str
    calculated: bool = False  # columns only: its values come from DAX


@dataclass(frozen=True)
class Exclusion:
    kind: Kind
    identifier: str
    reason: str


@dataclass(frozen=True)
class Inventory:
    objects: tuple[ModelObject, ...]
    excluded: tuple[Exclusion, ...]


def column_id(table: str, column: str) -> str:
    return f"{table}[{column}]"


def relationship_id(from_table: str, from_column: str, to_table: str, to_column: str) -> str:
    return f"{column_id(from_table, from_column)}->{column_id(to_table, to_column)}"


def _table_exclusion(table: ModelTable) -> str | None:
    """Why a table (and its columns) is not counted, the way `init` leaves it out of a starter contract."""
    if AUTO_DATE_TABLE_RE.match(table.name):
        return AUTO_DATE_TABLE
    if table.calculation_group:
        return CALCULATION_GROUP
    if table.measure_table:
        return MEASURE_TABLE
    return None


def model_inventory(semantic_model_dir: Path) -> Inventory:
    """Every table, column, measure, and relationship the report counts, and the ones it leaves out (with why)."""
    objects: list[ModelObject] = []
    excluded: list[Exclusion] = []
    left_out: dict[str, str] = {}
    for table in model_tables(semantic_model_dir):
        reason = _table_exclusion(table)
        objects.extend(ModelObject(Kind.MEASURE, column_id(table.name, m)) for m in table.measures)
        if reason:
            left_out[table.name.lower()] = reason
            excluded.append(Exclusion(Kind.TABLE, table.name, reason))
            excluded.extend(Exclusion(Kind.COLUMN, column_id(table.name, c.name), reason) for c in table.columns)
            continue
        objects.append(ModelObject(Kind.TABLE, table.name))
        objects.extend(
            ModelObject(Kind.COLUMN, column_id(table.name, c.name), calculated=c.calculated) for c in table.columns
        )
    for ends in sorted(model_relationships(semantic_model_dir)):
        identifier = relationship_id(*ends)
        reason = left_out.get(ends[0].lower()) or left_out.get(ends[2].lower())
        if reason:
            excluded.append(Exclusion(Kind.RELATIONSHIP, identifier, f"it joins {reason}"))
        else:
            objects.append(ModelObject(Kind.RELATIONSHIP, identifier))
    return Inventory(tuple(objects), tuple(excluded))


class Level(IntEnum):
    """How strongly the contract covers an object; an object takes the strongest level any rule gives it."""

    NOT_COVERED = 0
    LISTED_NOT_ENFORCED = 1  # in the contract, but every rule on it is skipped
    LISTED = 2  # a schema check runs: exists, has the column, has the type, the relationship exists
    VALUES_TESTED = 3  # a rule checks its data

    @property
    def label(self) -> str:
        return self.name.lower().replace("_", " ")


# Evidence.source values: the contract's own targets, a text scan of contract DAX, or the model's engine.
CONTRACT = "contract"
SCAN = "scan"
ENGINE = "engine"


@dataclass(frozen=True)
class Evidence:
    """One rule's claim on one object. *identifier* is in the model's spelling when the model has the object."""

    kind: Kind
    identifier: str
    level: Level
    rule_id: str
    source: str = CONTRACT


@dataclass(frozen=True)
class Unresolved:
    """A name in contract DAX that matches no model object, so it is not counted."""

    rule_id: str
    reference: str


@dataclass(frozen=True)
class ContractEvidence:
    evidence: tuple[Evidence, ...]
    unresolved: tuple[Unresolved, ...]


class _Names:
    """The inventory's identifiers by lower-case name (DAX names ignore case)."""

    def __init__(self, inventory: Inventory) -> None:
        self.by_key = {(o.kind, o.identifier.lower()): o.identifier for o in inventory.objects}
        self.tables = {i.lower(): i for (k, _), i in self.by_key.items() if k is Kind.TABLE}
        # Measure names are unique in a model, so [Name] finds its measure without the table.
        self.measures = {i[i.index("[") + 1 : -1].lower(): i for (k, _), i in self.by_key.items() if k is Kind.MEASURE}

    def model(self, kind: Kind, identifier: str) -> str:
        """The model's spelling of *identifier*, or *identifier* itself when the model lacks it."""
        return self.by_key.get((kind, identifier.lower()), identifier)

    def has(self, kind: Kind, identifier: str) -> bool:
        return (kind, identifier.lower()) in self.by_key


def _column_and_table(names: _Names, table: str, column: str, level: Level, rule_id: str, source: str) -> list[Evidence]:
    """A column reference covers its table too: the engine reports the table for every column reference."""
    return [
        Evidence(Kind.COLUMN, names.model(Kind.COLUMN, column_id(table, column)), level, rule_id, source),
        Evidence(Kind.TABLE, names.model(Kind.TABLE, table), level, rule_id, source),
    ]


def _assertion_evidence(names: _Names, a: Assertion, rule_id: str) -> list[Evidence]:
    """What a translated (not contract-written) assertion covers, from its target and arguments."""
    level = Level.LISTED if a.suite == SCHEMA_SUITE else Level.VALUES_TESTED
    if a.op == "rel.exists":
        ends = (a.args["fromTable"], a.args["fromColumn"], a.args["toTable"], a.args["toColumn"])
        return [Evidence(Kind.RELATIONSHIP, names.model(Kind.RELATIONSHIP, relationship_id(*ends)), level, rule_id)]
    found = [Evidence(Kind.TABLE, names.model(Kind.TABLE, a.target.table), level, rule_id)]
    columns = [a.target.column] if a.target.column else []
    columns += [c for c in a.args.get("columns") or [] if isinstance(c, str)]
    for column in columns:
        found += _column_and_table(names, a.target.table, column, level, rule_id, CONTRACT)
    return found


def _dax_texts(a: Assertion) -> list[str]:
    """The DAX a contract wrote for an ``engine: pql-test`` assertion: its expression, or its call's arguments."""
    if a.op == DIRECT_CALL:
        return [str(arg) for arg in a.args.get("arguments") or []]
    return [str(a.args["expression"])] if "expression" in a.args else []


def _resolve_reference(names: _Names, ref: DaxRef) -> list[tuple[Kind, str]] | None:
    """The model objects one DAX reference names, ``[]`` for a bare word that is not a table, or None when unresolved."""
    if ref.name is None:
        table = names.tables.get(ref.table.lower())
        if table:
            return [(Kind.TABLE, table)]
        return None if ref.quoted else []  # an unknown bare word is a variable or keyword, not a reference
    if ref.table is None:
        measure = names.measures.get(ref.name.lower())
        return [(Kind.MEASURE, measure)] if measure else None
    identifier = column_id(ref.table, ref.name)
    if names.has(Kind.COLUMN, identifier):
        return [(Kind.COLUMN, names.model(Kind.COLUMN, identifier)), (Kind.TABLE, names.model(Kind.TABLE, ref.table))]
    if names.has(Kind.MEASURE, identifier):
        return [(Kind.MEASURE, names.model(Kind.MEASURE, identifier))]
    return None


def _scanned(names: _Names, a: Assertion, rule_id: str) -> tuple[list[Evidence], list[Unresolved]]:
    found, unresolved = [], []
    for text in _dax_texts(a):
        for ref in dax_references(text):
            objects = _resolve_reference(names, ref)
            if objects is None:
                unresolved.append(Unresolved(rule_id, str(ref)))
            found += [Evidence(kind, identifier, Level.VALUES_TESTED, rule_id, SCAN) for kind, identifier in objects or []]
    return found, unresolved


def _listed(plan: Plan, names: _Names) -> Iterator[Evidence]:
    """Everything the contract's schema lists, at the weakest level: skipped rules still list their object."""
    for obj in plan.contract.schema_objects:
        table = plan.names.table(obj)
        yield Evidence(Kind.TABLE, names.model(Kind.TABLE, table), Level.LISTED_NOT_ENFORCED, obj["name"])
        for prop in obj.get("properties") or []:
            if is_column(prop):
                identifier = column_id(table, plan.names.column(obj, prop))
                scope = f"{obj['name']}.{prop.get('name')}"
                yield Evidence(Kind.COLUMN, names.model(Kind.COLUMN, identifier), Level.LISTED_NOT_ENFORCED, scope)
    for obj, prop, scope, index, rel in relationship_entries(plan.contract):
        ends = resolve(plan.contract, plan.names, obj, prop, rel)
        if not isinstance(ends, str):
            identifier = names.model(Kind.RELATIONSHIP, relationship_id(*ends))
            yield Evidence(Kind.RELATIONSHIP, identifier, Level.LISTED_NOT_ENFORCED, f"{scope}.relationships[{index}]")


def contract_evidence(plan: Plan, inventory: Inventory) -> ContractEvidence:
    """What every rule in *plan* covers in *inventory*, without connecting to the model.

    Translated rules cover their target (and its table); rules whose DAX the contract wrote cover
    only what that DAX references, read by a text scan, never the table they are placed under.
    """
    names = _Names(inventory)
    evidence: list[Evidence] = list(_listed(plan, names))
    unresolved: list[Unresolved] = []
    for outcome in plan.outcomes:
        if outcome.status is Status.SKIPPED:
            continue
        for a in outcome.assertions:
            if a.suite == CONTRACT_DAX_SUITE:
                found, missing = _scanned(names, a, outcome.rule_id)
                evidence += found
                unresolved += missing
            else:
                evidence += _assertion_evidence(names, a, outcome.rule_id)
    return ContractEvidence(tuple(_unique(evidence)), tuple(_unique(unresolved)))


def _unique(items: Iterable) -> list:
    return list(dict.fromkeys(items))
