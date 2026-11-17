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

import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from pql_test.odcs.dax_refs import DaxRef, dax_references
from pql_test.odcs.ir import CONTRACT_DAX_SUITE, DIRECT_CALL, SCHEMA_SUITE, Assertion, Status
from pql_test.odcs.mapping.context import is_column
from pql_test.odcs.mapping.relationships import relationship_entries, resolve
from pql_test.odcs.pbip import (
    AUTO_DATE_TABLE_RE,
    ModelTable,
    is_measure_table,
    model_relationships,
    model_tables,
    related_tables,
)

if TYPE_CHECKING:
    from pql_test.odcs.api import Plan


class Kind(str, Enum):
    """The model object categories `contract coverage` counts."""

    TABLE = "TABLE"
    COLUMN = "COLUMN"
    RELATIONSHIP = "RELATIONSHIP"
    MEASURE = "MEASURE"


AUTO_DATE_TABLE = "Power BI's automatic date table, not part of the model anyone wrote"
MEASURE_TABLE = (
    "a measure table: it holds measures (counted on their own), only hidden placeholder columns, and no relationship"
)
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
    table: str = ""  # tables, columns, measures: the (home) table
    name: str = ""  # columns and measures: the name without the table
    data_type: str | None = None  # columns only: the TMDL dataType, when known
    ends: tuple[str, ...] = ()  # relationships only: (from table, from column, to table, to column)


@dataclass(frozen=True)
class Exclusion:
    kind: Kind
    identifier: str
    reason: str


@dataclass(frozen=True)
class Inventory:
    objects: tuple[ModelObject, ...]
    excluded: tuple[Exclusion, ...]
    # Every table's columns, left-out tables included, for the checks `lint` makes
    # (``table -> {column: TMDL dataType or None}``), and every relationship's ends.
    tables: Mapping[str, Mapping[str, str | None]] = field(default_factory=dict)
    relationships: tuple[tuple[str, str, str, str], ...] = ()


def column_id(table: str, column: str) -> str:
    return f"{table}[{column}]"


def relationship_id(from_table: str, from_column: str, to_table: str, to_column: str) -> str:
    return f"{column_id(from_table, from_column)}->{column_id(to_table, to_column)}"


def _table_exclusion(table: ModelTable, related: set[str]) -> str | None:
    """Why a table (and its columns) is not counted, the way `init` leaves it out of a starter contract."""
    if AUTO_DATE_TABLE_RE.match(table.name):
        return AUTO_DATE_TABLE
    if table.calculation_group:
        return CALCULATION_GROUP
    if is_measure_table(table, related):
        return MEASURE_TABLE
    return None


def model_inventory(semantic_model_dir: Path) -> Inventory:
    """Every table, column, measure, and relationship the report counts, and the ones it leaves out (with why)."""
    tables = model_tables(semantic_model_dir)
    return inventory_of(tables, sorted(model_relationships(semantic_model_dir)))


def inventory_of(tables: Iterable[ModelTable], relationships: Iterable[tuple[str, str, str, str]]) -> Inventory:
    """The inventory of a model given as tables and relationship ends, read from TMDL or from a connected model."""
    tables, relationships = tuple(tables), tuple(relationships)
    objects: list[ModelObject] = []
    excluded: list[Exclusion] = []
    left_out: dict[str, str] = {}
    related = related_tables(relationships)
    for table in tables:
        reason = _table_exclusion(table, related)
        objects.extend(
            ModelObject(Kind.MEASURE, column_id(table.name, m), table=table.name, name=m) for m in table.measures
        )
        if reason:
            left_out[table.name.lower()] = reason
            excluded.append(Exclusion(Kind.TABLE, table.name, reason))
            excluded.extend(Exclusion(Kind.COLUMN, column_id(table.name, c.name), reason) for c in table.columns)
            continue
        objects.append(ModelObject(Kind.TABLE, table.name, table=table.name))
        objects.extend(
            ModelObject(
                Kind.COLUMN,
                column_id(table.name, c.name),
                calculated=c.calculated,
                table=table.name,
                name=c.name,
                data_type=c.data_type,
            )
            for c in table.columns
        )
    for ends in relationships:
        identifier = relationship_id(*ends)
        reason = left_out.get(ends[0].lower()) or left_out.get(ends[2].lower())
        if reason:
            excluded.append(Exclusion(Kind.RELATIONSHIP, identifier, f"it joins {reason}"))
        else:
            objects.append(ModelObject(Kind.RELATIONSHIP, identifier, ends=tuple(ends)))
    columns = {t.name: {c.name: c.data_type for c in t.columns} for t in tables}
    return Inventory(tuple(objects), tuple(excluded), columns, relationships)


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


class ModelNames:
    """The inventory's identifiers by lower-case name (DAX names ignore case)."""

    def __init__(self, inventory: Inventory) -> None:
        self.by_key = {(o.kind, o.identifier.lower()): o.identifier for o in inventory.objects}
        self.tables = {i.lower(): i for (k, _), i in self.by_key.items() if k is Kind.TABLE}
        # Measure names are unique in a model, so [Name] finds its measure without the table.
        self.measures = {
            (o.name or o.identifier[o.identifier.index("[") + 1 : -1]).lower(): o.identifier
            for o in inventory.objects
            if o.kind is Kind.MEASURE
        }

    def model(self, kind: Kind, identifier: str) -> str:
        """The model's spelling of *identifier*, or *identifier* itself when the model lacks it."""
        return self.by_key.get((kind, identifier.lower()), identifier)

    def has(self, kind: Kind, identifier: str) -> bool:
        return (kind, identifier.lower()) in self.by_key


def _column_and_table(names: ModelNames, table: str, column: str, level: Level, rule_id: str, source: str) -> list[Evidence]:
    """A column reference covers its table too: the engine reports the table for every column reference."""
    return [
        Evidence(Kind.COLUMN, names.model(Kind.COLUMN, column_id(table, column)), level, rule_id, source),
        Evidence(Kind.TABLE, names.model(Kind.TABLE, table), level, rule_id, source),
    ]


def _assertion_evidence(names: ModelNames, a: Assertion, rule_id: str) -> list[Evidence]:
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


def _resolve_reference(names: ModelNames, ref: DaxRef) -> list[tuple[Kind, str]] | None:
    """The model objects one DAX reference names, ``[]`` for a bare word that is not a table, or None when unresolved."""
    if ref.name is None:
        table = names.tables.get(ref.table.lower())
        if table:
            return [(Kind.TABLE, table)]
        return None if ref.quoted else []  # an unknown bare word is a variable or keyword, not a reference
    if ref.table is not None and not ref.quoted and ref.table.lower() not in names.tables:
        ref = DaxRef(name=ref.name)  # an unquoted word that names no table: read [Name] on its own
    if ref.table is None:
        measure = names.measures.get(ref.name.lower())
        return [(Kind.MEASURE, measure)] if measure else None
    identifier = column_id(ref.table, ref.name)
    if names.has(Kind.COLUMN, identifier):
        return [(Kind.COLUMN, names.model(Kind.COLUMN, identifier)), (Kind.TABLE, names.model(Kind.TABLE, ref.table))]
    if names.has(Kind.MEASURE, identifier):
        return [(Kind.MEASURE, names.model(Kind.MEASURE, identifier))]
    return None


def scanned_evidence(names: ModelNames, a: Assertion, rule_id: str) -> tuple[list[Evidence], list[Unresolved]]:
    """What a contract-DAX assertion references, read from its text: the evidence, and names that match nothing."""
    found, unresolved = [], []
    for text in _dax_texts(a):
        for ref in dax_references(text):
            objects = _resolve_reference(names, ref)
            if objects is None:
                unresolved.append(Unresolved(rule_id, str(ref)))
            found += [Evidence(kind, identifier, Level.VALUES_TESTED, rule_id, SCAN) for kind, identifier in objects or []]
    return found, unresolved


def _listed(plan: Plan, names: ModelNames) -> Iterator[Evidence]:
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


def dax_rule_assertions(plan: Plan) -> list[tuple[str, Assertion]]:
    """``(rule id, assertion)`` for every enforced rule whose DAX the contract wrote (``engine: pql-test``)."""
    return [
        (outcome.rule_id, a)
        for outcome in plan.outcomes
        if outcome.status is not Status.SKIPPED
        for a in outcome.assertions
        if a.suite == CONTRACT_DAX_SUITE
    ]


def contract_evidence(plan: Plan, inventory: Inventory, *, scan_dax: bool = True) -> ContractEvidence:
    """What every rule in *plan* covers in *inventory*, without connecting to the model.

    Translated rules cover their target (and its table); rules whose DAX the contract wrote cover
    only what that DAX references, read by a text scan, never the table they are placed under.
    With *scan_dax* False those rules are left out, for the caller to ask the model's engine instead.
    """
    names = ModelNames(inventory)
    evidence: list[Evidence] = list(_listed(plan, names))
    unresolved: list[Unresolved] = []
    for outcome in plan.outcomes:
        if outcome.status is Status.SKIPPED:
            continue
        for a in outcome.assertions:
            if a.suite != CONTRACT_DAX_SUITE:
                evidence += _assertion_evidence(names, a, outcome.rule_id)
            elif scan_dax:
                found, missing = scanned_evidence(names, a, outcome.rule_id)
                evidence += found
                unresolved += missing
    return ContractEvidence(tuple(_unique(evidence)), tuple(_unique(unresolved)))


@dataclass(frozen=True)
class DaxEvidence:
    """What the model's engine says contract DAX references (``--live``), with what it could not analyse."""

    evidence: tuple[Evidence, ...]
    unresolved: tuple[Unresolved, ...] = ()
    unavailable: tuple[str, ...] = ()  # why the engine check could not run at all


def _unique(items: Iterable) -> list:
    return list(dict.fromkeys(items))


SCHEMA_VERSION = 1
CALCULATED_GAP = (
    "calculated columns whose DAX no rule checks: a calculated column's values come from DAX, "
    "so only a rule on its values tests that logic"
)


@dataclass(frozen=True)
class Classified:
    """One model object at its strongest level, with the rules (or, when listed but not enforced, the
    contract paths) that put it there, and where that evidence came from."""

    obj: ModelObject
    level: Level
    rules: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()


def classify(inventory: Inventory, evidence: Iterable[Evidence]) -> tuple[Classified, ...]:
    """Each inventory object at the strongest level any evidence gives it. Evidence for objects the
    model lacks is ignored here (``lint`` reports those)."""
    by_key: dict[tuple[Kind, str], list[Evidence]] = {}
    for e in evidence:
        by_key.setdefault((e.kind, e.identifier.lower()), []).append(e)
    result = []
    for obj in inventory.objects:
        found = by_key.get((obj.kind, obj.identifier.lower()), [])
        level = max((e.level for e in found), default=Level.NOT_COVERED)
        strongest = [e for e in found if e.level is level]
        rules = tuple(_unique(e.rule_id for e in strongest))
        sources = tuple(sorted({e.source for e in strongest}))
        result.append(Classified(obj, level, rules, sources))
    return tuple(result)


@dataclass(frozen=True)
class Counts:
    eligible: int = 0
    values_tested: int = 0
    listed: int = 0
    listed_not_enforced: int = 0
    not_covered: int = 0

    @property
    def covered(self) -> int:
        """Objects with at least one rule that runs: values tested or listed."""
        return self.values_tested + self.listed

    @property
    def percent(self) -> float:
        # code-coverage's rounding: only every object covered rounds to 100.
        from pql_test.runner.coverage_report import coverage_percent

        return coverage_percent(self.covered, self.eligible)

    @classmethod
    def of(cls, objects: Iterable[Classified]) -> Counts:
        levels = [c.level for c in objects]
        return cls(
            eligible=len(levels),
            values_tested=levels.count(Level.VALUES_TESTED),
            listed=levels.count(Level.LISTED),
            listed_not_enforced=levels.count(Level.LISTED_NOT_ENFORCED),
            not_covered=levels.count(Level.NOT_COVERED),
        )

    def to_json(self) -> dict:
        return {
            "eligible": self.eligible,
            "covered": self.covered,
            "percent": self.percent,
            "valuesTested": self.values_tested,
            "listed": self.listed,
            "listedNotEnforced": self.listed_not_enforced,
            "notCovered": self.not_covered,
        }


@dataclass(frozen=True)
class Suggestion:
    """ODCS YAML that would cover one uncovered object, and where in the contract it goes.

    *section* is ``schema`` (a new schema object), or ``properties`` / ``quality`` / ``relationships`` of the
    schema object named *schema_object* (None: any schema object). *ids* are ``(schema object, property or
    None, id)``: the ids to give those elements first, for a relationship that references them by id.
    """

    kind: Kind
    identifier: str
    section: str
    schema_object: str | None
    yaml: str
    ids: tuple[tuple[str, str | None, str], ...] = ()

    @property
    def where(self) -> str:
        if self.section == "schema":
            return "under schema:"
        owner = f"schema object {self.schema_object!r}" if self.schema_object else "any schema object"
        return f"under {owner}, {self.section}:"


def _yaml(entries: list) -> str:
    return yaml.safe_dump(entries, sort_keys=False, allow_unicode=True, width=120)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "measure"


def _quality_ids(plan: Plan) -> set[str]:
    """Every quality rule id the contract already uses, on schema objects and their properties."""
    ids = set()
    for obj in plan.contract.schema_objects:
        for element in (obj, *(obj.get("properties") or [])):
            rules = [r for r in element.get("quality") or [] if isinstance(r, Mapping) and r.get("id")]
            ids.update(str(r["id"]) for r in rules)
    return ids


def _measure_rule(obj: ModelObject, taken: set[str]) -> dict:
    """An ``engine: pql-test`` rule template that tests the measure's value (the comparator is a placeholder).

    Its id is not in *taken* (ids already in the contract or suggested), and is added to it.
    """
    base = f"{_slug(obj.name)}-check"
    rule_id = next(i for i in (base, *(f"{base}-{n}" for n in range(2, len(taken) + 3))) if i not in taken)
    taken.add(rule_id)
    return {
        "id": rule_id,
        "type": "custom",
        "engine": "pql-test",
        "description": f"{obj.name} has the expected value (edit the comparator below)",
        "implementation": {"expression": f"[{obj.name.replace(']', ']]')}]", "mustBeGreaterThan": 0},
    }


NO_RELATIONSHIPS_V30 = (
    "relationships: ODCS v3.0 has no relationships, so none is suggested; use apiVersion v3.1.0 or later to list them"
)


def _forms(plan: Plan):
    from pql_test.odcs.loader import reference_forms

    return reference_forms(plan.contract.api_version.rsplit(".", 1)[0])


class _Ids:
    """Ids for the elements an id-form relationship references: an existing id is reused, and a new one is
    unique within its containing array (the ODCS rule) and the same in every suggestion that needs it."""

    def __init__(self, plan: Plan) -> None:
        self._objects = plan.contract.schema_objects
        self._proposed: dict[tuple[str, str | None], str] = {}

    def of(self, owner: str, prop_name: str | None, element: Mapping | None, siblings: list) -> tuple[str, bool]:
        """``(id, whether the element still needs it)`` for *element* (None: not in the contract yet)."""
        if element is not None and element.get("id"):
            return str(element["id"]), False
        key = (owner, prop_name)
        if key not in self._proposed:
            # Ids already proposed for the same array: schema objects, or this schema object's properties.
            same_array = [
                v
                for (o, p), v in self._proposed.items()
                if (p is None if prop_name is None else (o == owner and p is not None))
            ]
            taken = {str(s["id"]) for s in siblings if isinstance(s, Mapping) and s.get("id")} | set(same_array)
            base = re.sub(r"[^A-Za-z0-9_]+", "_", prop_name or owner).strip("_").lower() or "id"
            candidates = (base, *(f"{base}_{n}" for n in range(2, len(taken) + 3)))
            self._proposed[key] = next(i for i in candidates if i not in taken)
        return self._proposed[key], True

    def reference(self, owner: str, obj: Mapping | None, prop_name: str, prop: Mapping | None) -> tuple[str, list]:
        """The ``schema/<id>/properties/<id>`` reference, and the ``(owner, property, id)`` ids to add for it."""
        obj_id, new_obj = self.of(owner, None, obj, self._objects)
        prop_id, new_prop = self.of(owner, prop_name, prop, (obj or {}).get("properties") or [])
        to_add = [(owner, None, obj_id)] * new_obj + [(owner, prop_name, prop_id)] * new_prop
        return f"schema/{obj_id}/properties/{prop_id}", to_add


def _contract_end(plan: Plan, table: str, column: str) -> tuple[Mapping | None, Mapping | None]:
    """The contract schema object and column property whose model names are *table* and *column*."""
    obj = next((o for o in plan.contract.schema_objects if plan.names.table(o).lower() == table.lower()), None)
    props = (obj or {}).get("properties") or []
    prop = next((p for p in props if is_column(p) and plan.names.column(obj, p).lower() == column.lower()), None)
    return obj, prop


def _relationship_suggestion(plan: Plan, o: ModelObject, ids: _Ids) -> Suggestion | None:
    """A schema-level foreign key for an uncovered relationship: each end as ``table.property`` when both its
    names fit that form, else by id.

    An end the contract does not list yet is named as the model names it, as the table and column suggestions
    add it. ODCS v3.0 has no relationships, so it gets none.
    """
    forms = _forms(plan)
    if forms is None:
        return None
    refs, to_add, owners = [], [], []
    for table, column in (o.ends[:2], o.ends[2:]):
        obj, prop = _contract_end(plan, table, column)
        owner, prop_name = obj["name"] if obj else table, prop["name"] if prop else column
        owners.append(owner)
        # A dot in a name would read as a nested property, so it needs the id form too.
        if "." not in owner + prop_name and forms.shorthand.fullmatch(f"{owner}.{prop_name}"):
            refs.append(f"{owner}.{prop_name}")
            continue
        ref, added = ids.reference(owner, obj, prop_name, prop)
        refs.append(ref)
        to_add.extend(added)
    entry = {"type": "foreignKey", "from": refs[0], "to": refs[1]}
    return Suggestion(Kind.RELATIONSHIP, o.identifier, "relationships", owners[0], _yaml([entry]), tuple(to_add))


def suggestions(plan: Plan, objects: Iterable[Classified]) -> tuple[Suggestion, ...]:
    """YAML for every uncovered table, column, measure, and relationship: tables and columns the way `init`
    writes them, a rule template per measure (an ODCS schema cannot list a measure, so only a rule covers one),
    and a foreign key per relationship (by id when a name has a character a table.property reference cannot hold).
    """
    from pql_test.odcs.scaffold import starter_object, starter_property

    objects = tuple(objects)
    in_contract = {plan.names.table(o).lower(): o["name"] for o in plan.contract.schema_objects}
    taken = _quality_ids(plan)
    columns: dict[str, list[ModelObject]] = {}
    for c in objects:
        if c.obj.kind is Kind.COLUMN:
            columns.setdefault(c.obj.table.lower(), []).append(c.obj)
    uncovered = [c.obj for c in objects if c.level is Level.NOT_COVERED]
    # A table the schema does not list gets a new schema object, which covers its columns, and holds
    # the rule templates for its uncovered measures.
    new_tables = {
        o.table: None for o in uncovered if o.kind in (Kind.TABLE, Kind.COLUMN) and o.table.lower() not in in_contract
    }
    new_lower = {t.lower() for t in new_tables}
    found = []
    for table in new_tables:
        entry = starter_object(table, {c.name: c.data_type for c in columns.get(table.lower(), [])})
        rules = [_measure_rule(o, taken) for o in uncovered if o.kind is Kind.MEASURE and o.table.lower() == table.lower()]
        if rules:
            entry["quality"] = rules
        found.append(Suggestion(Kind.TABLE, table, "schema", None, _yaml([entry])))
    for o in uncovered:
        if o.kind is Kind.COLUMN and o.table.lower() in in_contract:
            owner = in_contract[o.table.lower()]
            entry = starter_property(o.name, o.data_type)
            found.append(Suggestion(Kind.COLUMN, o.identifier, "properties", owner, _yaml([entry])))
        elif o.kind is Kind.MEASURE and o.table.lower() not in new_lower:
            # Placement does not change what a rule covers, so a measure whose table is not in the contract
            # (a measure table, say) can go under any schema object.
            owner = in_contract.get(o.table.lower())
            found.append(Suggestion(Kind.MEASURE, o.identifier, "quality", owner, _yaml([_measure_rule(o, taken)])))
    ids = _Ids(plan)
    relationships = (_relationship_suggestion(plan, o, ids) for o in uncovered if o.kind is Kind.RELATIONSHIP)
    found.extend(s for s in relationships if s is not None)
    return tuple(found)


@dataclass(frozen=True)
class CoverageReport:
    contract: dict  # id, name, apiVersion, source
    model: str
    pql_assert: str
    objects: tuple[Classified, ...]
    excluded: tuple[Exclusion, ...] = ()
    unresolved: tuple[Unresolved, ...] = ()
    suggestions: tuple[Suggestion, ...] = ()
    mismatches: tuple[str, ...] = ()  # contract entries the model lacks or types differently (lint's checks)
    live: bool = False  # the objects came from the connected model and its engine read the contract DAX
    unavailable: tuple[str, ...] = ()  # checks that could not run, and why

    def counts(self, kind: Kind | None = None) -> Counts:
        return Counts.of(c for c in self.objects if kind is None or c.obj.kind is kind)

    @property
    def calculated_without_value_rule(self) -> tuple[str, ...]:
        return tuple(
            c.obj.identifier for c in self.objects if c.obj.calculated and c.level is not Level.VALUES_TESTED
        )

    def to_json(self) -> dict:
        from pql_test.odcs import __version__

        return {
            "schemaVersion": SCHEMA_VERSION,
            "generator": f"pql-test {__version__}",
            "contract": self.contract,
            "model": self.model,
            "source": "model" if self.live else "files",
            "pqlAssert": self.pql_assert,
            "summary": self.counts().to_json(),
            "categories": {k.value: self.counts(k).to_json() for k in Kind},
            "objects": [
                {
                    "kind": c.obj.kind.value,
                    "identifier": c.obj.identifier,
                    "level": c.level.name.lower(),
                    **({"calculated": True} if c.obj.calculated else {}),
                    "rules": list(c.rules),
                    "sources": list(c.sources),
                }
                for c in self.objects
            ],
            "calculatedColumnsWithoutValueRule": list(self.calculated_without_value_rule),
            "excluded": [{"kind": e.kind.value, "identifier": e.identifier, "reason": e.reason} for e in self.excluded],
            "notCounted": NOT_COUNTED,
            "unresolved": [{"ruleId": u.rule_id, "reference": u.reference} for u in self.unresolved],
            "suggestions": [
                {
                    "kind": s.kind.value,
                    "identifier": s.identifier,
                    "section": s.section,
                    "schemaObject": s.schema_object,
                    "yaml": s.yaml,
                    "ids": [{"schemaObject": o, "property": p, "id": i} for o, p, i in s.ids],
                }
                for s in self.suggestions
            ],
            "mismatches": list(self.mismatches),
            "unavailable": list(self.unavailable),
        }


def build_coverage(
    plan: Plan,
    inventory: Inventory,
    *,
    model: str,
    pql_assert: str,
    dax: DaxEvidence | None = None,
) -> CoverageReport:
    """The coverage report for *plan* against *inventory*.

    Without *dax*, contract DAX is read by a text scan; with it (``--live``), the engine's answer is used.
    """
    from pql_test.odcs.model_check import model_problems

    found = contract_evidence(plan, inventory, scan_dax=dax is None)
    evidence = found.evidence + (dax.evidence if dax else ())
    objects = classify(inventory, evidence)
    c = plan.contract
    no_relationships = _forms(plan) is None and any(
        o.obj.kind is Kind.RELATIONSHIP and o.level is Level.NOT_COVERED for o in objects
    )
    return CoverageReport(
        contract={"id": c.id, "name": c.name, "apiVersion": c.api_version, "source": c.source},
        model=model,
        pql_assert=pql_assert,
        objects=objects,
        excluded=inventory.excluded,
        unresolved=found.unresolved + (dax.unresolved if dax else ()),
        suggestions=suggestions(plan, objects),
        mismatches=tuple(model_problems(plan, inventory.tables, inventory.relationships)),
        live=dax is not None,
        unavailable=(dax.unavailable if dax else ()) + ((NO_RELATIONSHIPS_V30,) if no_relationships else ()),
    )
