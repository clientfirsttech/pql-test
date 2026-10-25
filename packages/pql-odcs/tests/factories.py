# SPDX-License-Identifier: MIT
"""Factory helpers that build fresh ODCS contract dicts for each test (no shared state)."""

from __future__ import annotations

import copy


def contract_dict(api_version: str = "v3.1.0", schema: list | None = None, **overrides) -> dict:
    """Return a minimal valid ODCS contract with *schema* objects and root *overrides*."""
    data = {
        "apiVersion": api_version,
        "kind": "DataContract",
        "id": "marvel-contract",
        "name": "Marvel Characters",
        "version": "1.0.0",
        "status": "active",
        "schema": copy.deepcopy(schema) if schema is not None else [],
    }
    data.update(copy.deepcopy(overrides))
    return data


def schema_object(name: str, properties: list | None = None, **extra) -> dict:
    """Return an ODCS schema object (a table) named *name*."""
    obj = {"name": name, "physicalType": "table", "properties": copy.deepcopy(properties or [])}
    obj.update(copy.deepcopy(extra))
    return obj


def prop(name: str, logical_type: str = "string", **extra) -> dict:
    """Return an ODCS schema property (a column) named *name*."""
    p = {"name": name, "logicalType": logical_type}
    p.update(copy.deepcopy(extra))
    return p


def custom(**pairs) -> list[dict]:
    """Return ODCS customProperties as the spec's list of {property, value} items."""
    return [{"property": k, "value": v} for k, v in pairs.items()]
