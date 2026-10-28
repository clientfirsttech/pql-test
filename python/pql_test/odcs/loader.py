# SPDX-License-Identifier: AGPL-3.0-only
"""Load an ODCS contract from YAML or a dict, gate its version, and schema-validate it."""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import Any, Union

import yaml

# Supported ODCS minor versions -> bundled JSON schema used to validate them.
SCHEMAS = {
    "3.0": "odcs-json-schema-v3.0.2.json",
    "3.1": "odcs-json-schema-v3.1.0.json",
    "3.2": "odcs-json-schema-v3.2.0.json",
}
SUPPORTED_RANGE = "v3.0.x, v3.1.x, and v3.2.x"
_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")

ContractSource = Union[str, Path, Mapping]


class ContractError(Exception):
    """The contract could not be read, is an unsupported version, or is invalid."""

    def __init__(self, message: str, problems: list[str] | None = None) -> None:
        self.problems = list(problems or [])
        detail = "".join(f"\n  {p}" for p in self.problems)
        super().__init__(message + detail)


@dataclass(frozen=True)
class Contract:
    """A validated ODCS contract. ``data`` is a private deep copy of the input."""

    data: dict
    api_version: str
    source: str = field(default="<dict>", compare=False)

    @property
    def id(self) -> str:
        return str(self.data["id"])

    @property
    def name(self) -> str | None:
        return self.data.get("name")

    @property
    def data_product(self) -> str | None:
        return self.data.get("dataProduct")

    @property
    def schema_objects(self) -> list[dict]:
        return list(self.data.get("schema") or [])


class _NoTimestampLoader(yaml.SafeLoader):
    """SafeLoader that keeps timestamps as strings (ODCS types them as strings)."""


_NoTimestampLoader.yaml_implicit_resolvers = {
    key: [(tag, rx) for tag, rx in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def _read_yaml(path: Path) -> Any:
    try:
        return yaml.load(path.read_text(encoding="utf-8"), Loader=_NoTimestampLoader)
    except OSError as exc:
        raise ContractError(f"Cannot read contract {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ContractError(f"Contract {path} is not valid YAML: {exc}") from exc


@cache
def _validator(schema_file: str):
    from jsonschema import Draft201909Validator  # deferred: keeps CLI startup fast

    schema = json.loads(files("pql_test.odcs").joinpath("schemas").joinpath(schema_file).read_text(encoding="utf-8"))
    return Draft201909Validator(schema)


def _json_path(parts) -> str:
    out = "$"
    for part in parts:
        out += f"[{part}]" if isinstance(part, int) else f".{part}"
    return out


def _minor(api_version: Any) -> tuple[str, str]:
    match = _VERSION_RE.match(str(api_version)) if api_version is not None else None
    if match is None:
        raise ContractError(f"Unsupported or missing apiVersion {api_version!r}; pql-test supports {SUPPORTED_RANGE}.")
    major, minor, patch = match.groups()
    key = f"{major}.{minor}"
    if key not in SCHEMAS:
        raise ContractError(f"Unsupported apiVersion {api_version!r}; pql-test supports {SUPPORTED_RANGE}.")
    return key, f"{major}.{minor}.{patch}"


def validate(data: Mapping) -> list[str]:
    """Return every schema violation in *data* as ``<json path>: <message>``, sorted."""
    key, _ = _minor(data.get("apiVersion"))
    errors = _validator(SCHEMAS[key]).iter_errors(data)
    return sorted({f"{_json_path(e.absolute_path)}: {e.message}" for e in errors})


def load_contract(source: ContractSource) -> Contract:
    """Load and validate an ODCS contract from a YAML path or an already-parsed mapping.

    Raises:
        ContractError: unreadable file, unsupported apiVersion, or schema violations.
    """
    if isinstance(source, Mapping):
        data, origin = copy.deepcopy(dict(source)), "<dict>"
    else:
        path = Path(source)
        data, origin = _read_yaml(path), path.name
    if not isinstance(data, dict):
        raise ContractError(f"Contract {origin} must be a YAML mapping, got {type(data).__name__}.")
    _, version = _minor(data.get("apiVersion"))
    problems = validate(data)
    if problems:
        raise ContractError(f"Contract {origin} does not match the ODCS v{version} schema:", problems)
    return Contract(data=data, api_version=version, source=origin)
