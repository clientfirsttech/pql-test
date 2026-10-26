# SPDX-License-Identifier: MIT
"""Resolve ODCS schema objects and properties to semantic model tables and columns.

The model name comes from the contract itself, so it travels with the contract
(including through the datacontract-cli adapter):

1. ``customProperties`` ``pbiTable`` (on a schema object) / ``pbiColumn`` (on a property)
2. otherwise the ODCS logical ``name``
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pql_odcs.loader import Contract

TABLE_KEY = "pbiTable"
COLUMN_KEY = "pbiColumn"


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


class NameResolver:
    """Resolves model table and column names for one contract."""

    def __init__(self, contract: Contract) -> None:
        self._contract = contract

    def table(self, obj: Mapping) -> str:
        override = custom_property(obj, TABLE_KEY)
        return str(override if override is not None else obj["name"])

    def column(self, obj: Mapping, prop: Mapping) -> str:
        override = custom_property(prop, COLUMN_KEY)
        return str(override if override is not None else prop["name"])

    def problems(self) -> list[str]:
        """Names that resolve to an empty string."""
        found: list[str] = []
        for obj in self._contract.schema_objects:
            if not self.table(obj).strip():
                found.append(f"{obj['name']}: resolved table name is empty")
            for prop in obj.get("properties") or []:
                if not self.column(obj, prop).strip():
                    found.append(f"{obj['name']}.{prop['name']}: resolved column name is empty")
        return sorted(found)
