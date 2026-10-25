# SPDX-License-Identifier: MIT
"""Versioned catalog mapping IR ops to PQL.Assert call templates (data, not code)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from importlib.resources import files

import yaml

DEFAULT_CATALOG = "pql_assert_0_7"


class CatalogError(Exception):
    """The catalog is malformed or has no entry for an IR op."""


@dataclass(frozen=True)
class OpSpec:
    fn: str
    args: tuple[str, ...]


@dataclass(frozen=True)
class Catalog:
    name: str
    library: str
    min_version: str
    ops: dict

    def op(self, key: str) -> OpSpec:
        try:
            return self.ops[key]
        except KeyError:
            raise CatalogError(
                f"IR op {key!r} has no entry in catalog {self.name} "
                f"({self.library} {self.min_version}); refusing to emit a partial call."
            ) from None


@cache
def load_catalog(name: str = DEFAULT_CATALOG) -> Catalog:
    """Load a bundled catalog, e.g. ``pql_assert_0_7``."""
    text = files("pql_odcs.catalog").joinpath(f"{name}.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    try:
        ops = {key: OpSpec(fn=spec["fn"], args=tuple(spec["args"])) for key, spec in data["ops"].items()}
        return Catalog(name=name, library=data["library"], min_version=str(data["min_version"]), ops=ops)
    except (KeyError, TypeError) as exc:
        raise CatalogError(f"Catalog {name} is malformed: {exc}") from exc
