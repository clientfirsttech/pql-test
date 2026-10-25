# SPDX-License-Identifier: MIT
"""Resolve ODCS schema objects and properties to semantic model tables and columns.

Precedence, highest first:

1. ``customProperties`` ``pbiTable`` (on a schema object) / ``pbiColumn`` (on a property)
2. a sidecar mapping file (``--mapping pql-odcs.mapping.yaml``)::

       tables:
         fact_marvel: MarvelFact          # ODCS object name -> model table
       columns:
         fact_marvel:
           eye_id: EyeID                  # ODCS property name -> model column

3. the ODCS logical ``name``
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from pql_odcs.loader import Contract

TABLE_KEY = "pbiTable"
COLUMN_KEY = "pbiColumn"
_SIDECAR_KEYS = {"tables", "columns"}


class MappingError(Exception):
    """The sidecar mapping file is unreadable or malformed."""


def custom_property(element: Mapping, key: str) -> Any:
    """Return ``customProperties[key]`` from an ODCS element, or ``None``.

    ODCS stores custom properties as a list of ``{property, value}`` items; a plain
    mapping is accepted as well.
    """
    props = element.get("customProperties")
    if isinstance(props, Mapping):
        return props.get(key)
    for item in props or []:
        if isinstance(item, Mapping) and item.get("property") == key:
            return item.get("value")
    return None


def load_sidecar(path: str | Path) -> dict:
    """Read and shape-check a sidecar mapping file."""
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise MappingError(f"Cannot read mapping file {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise MappingError(f"Mapping file {path} must be a YAML mapping.")
    unknown = sorted(set(data) - _SIDECAR_KEYS)
    if unknown:
        raise MappingError(f"Mapping file {path} has unknown key(s) {', '.join(unknown)}; expected tables, columns.")
    tables, columns = data.get("tables") or {}, data.get("columns") or {}
    if (
        not isinstance(tables, dict)
        or not isinstance(columns, dict)
        or not all(isinstance(v, dict) for v in columns.values())
    ):
        raise MappingError(f"Mapping file {path}: tables must map names to names; columns must nest by object.")
    return {"tables": tables, "columns": columns}


class NameResolver:
    """Resolves names for one contract, optionally with a sidecar mapping."""

    def __init__(self, contract: Contract, sidecar: Mapping | None = None) -> None:
        self._contract = contract
        self._tables: Mapping = (sidecar or {}).get("tables") or {}
        self._columns: Mapping = (sidecar or {}).get("columns") or {}

    def table(self, obj: Mapping) -> str:
        override = custom_property(obj, TABLE_KEY)
        if override is not None:
            return str(override)
        return str(self._tables.get(obj["name"], obj["name"]))

    def column(self, obj: Mapping, prop: Mapping) -> str:
        override = custom_property(prop, COLUMN_KEY)
        if override is not None:
            return str(override)
        return str((self._columns.get(obj["name"]) or {}).get(prop["name"], prop["name"]))

    def problems(self) -> list[str]:
        """Stale sidecar entries and names that resolve to an empty string."""
        found: list[str] = []
        objects = {o["name"]: o for o in self._contract.schema_objects}
        for name in self._tables:
            if name not in objects:
                found.append(f"mapping: tables.{name} is not a schema object in the contract")
        for obj_name, cols in self._columns.items():
            if obj_name not in objects:
                found.append(f"mapping: columns.{obj_name} is not a schema object in the contract")
                continue
            prop_names = {p["name"] for p in objects[obj_name].get("properties") or []}
            for col in cols:
                if col not in prop_names:
                    found.append(f"mapping: columns.{obj_name}.{col} is not a property of {obj_name} in the contract")
        for obj in objects.values():
            if not self.table(obj).strip():
                found.append(f"{obj['name']}: resolved table name is empty")
            for prop in obj.get("properties") or []:
                if not self.column(obj, prop).strip():
                    found.append(f"{obj['name']}.{prop['name']}: resolved column name is empty")
        return sorted(found)
