# SPDX-License-Identifier: AGPL-3.0-only
"""Versioned catalog mapping IR ops to PQL.Assert call templates (data, not code)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from importlib.resources import files

import yaml

DEFAULT_CATALOG = "pql_assert_0_7"
# `--pql-assert` choices -> bundled catalog. The default stays 0.7 until 0.8 is common.
PQL_ASSERT_CATALOGS = {"0.7": "pql_assert_0_7", "0.8": "pql_assert_0_8"}
DEFAULT_PQL_ASSERT = "0.7"
LATEST_PQL_ASSERT = "0.8"


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

    def has(self, key: str) -> bool:
        return key in self.ops

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
    text = files("pql_test.odcs.catalog").joinpath(f"{name}.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    try:
        # `extends` names an older catalog whose ops this one inherits and may override.
        base = dict(load_catalog(data["extends"]).ops) if data.get("extends") else {}
        base.update({key: OpSpec(fn=spec["fn"], args=tuple(spec["args"])) for key, spec in data["ops"].items()})
        ops = base
        return Catalog(name=name, library=data["library"], min_version=str(data["min_version"]), ops=ops)
    except (KeyError, TypeError) as exc:
        raise CatalogError(f"Catalog {name} is malformed: {exc}") from exc


@dataclass(frozen=True)
class Signature:
    params: int
    optional: int
    use: str  # mapped | dax | none (see pql_assert_functions.yaml)

    @property
    def callable(self) -> bool:
        """True when a contract may call it directly (``engine: pql-test`` with ``function``)."""
        return self.use != "none"


@dataclass(frozen=True)
class Signatures:
    version: str  # the PQL.Assert release they were read from
    functions: dict


@cache
def load_signatures() -> Signatures:
    """Every PQL.Assert function's parameter counts, from the bundled ``pql_assert_functions.yaml``."""
    text = files("pql_test.odcs.catalog").joinpath("pql_assert_functions.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    functions = {name: Signature(**spec) for name, spec in data["functions"].items()}
    return Signatures(version=str(data["version"]), functions=functions)


def catalog_for(pql_assert: str = DEFAULT_PQL_ASSERT) -> Catalog:
    """The bundled catalog for a ``--pql-assert`` choice (``"0.7"`` or ``"0.8"``)."""
    try:
        return load_catalog(PQL_ASSERT_CATALOGS[str(pql_assert)])
    except KeyError:
        raise CatalogError(
            f"Unknown PQL.Assert version {pql_assert!r}; choose from {', '.join(PQL_ASSERT_CATALOGS)}."
        ) from None
