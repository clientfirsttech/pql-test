# SPDX-License-Identifier: AGPL-3.0-only
"""PBIP folder helpers: locate the ``*.SemanticModel`` folder and read TMDL table/column names."""

from __future__ import annotations

import os
import re
from pathlib import Path

NOT_PBIP = (
    "MODEL_PATH {path!r} is not a PBIP model (no *.SemanticModel found). Pass the PBIP root folder, its "
    "*.SemanticModel folder, its .pbip file, or local/<name> for a model in this repository."
)
# Folders never searched for a local/<name> model's PBIP folder.
_SKIP_DIRS = {"node_modules", "__pycache__", "site-packages"}
_TABLE_RE = re.compile(r"^table\s+(.+?)\s*$")
# A quoted name ('a = b', with '' for ') is matched whole, so an "=" inside it does not end the name.
_COLUMN_RE = re.compile(r"^\s+column\s+('(?:[^']|'')*'|[^'=]+?)\s*(?:=.*)?$")
_DATA_TYPE_RE = re.compile(r"^\t\tdataType:\s*(\S+)\s*$")


class ModelPathError(Exception):
    """MODEL_PATH is not a usable PBIP model folder."""


def find_semantic_model_dir(model_path: str | Path) -> Path | None:
    """Return the ``*.SemanticModel`` folder for a PBIP root, model folder, or ``.pbip`` file.

    Returns ``None`` when *model_path* is not a PBIP path on disk.

    Raises:
        ModelPathError: the folder holds more than one ``*.SemanticModel``.
    """
    path = Path(model_path)
    if path.is_file() and path.suffix.lower() == ".pbip":
        sibling = path.with_suffix(".SemanticModel")
        if sibling.is_dir():
            return sibling
        path = path.parent
    if not path.is_dir():
        return None
    if path.name.endswith(".SemanticModel"):
        return path
    candidates = sorted(c for c in path.iterdir() if c.is_dir() and c.name.endswith(".SemanticModel"))
    if len(candidates) > 1:
        names = ", ".join(c.name for c in candidates)
        raise ModelPathError(f"MODEL_PATH {str(model_path)!r} holds several semantic models ({names}); pick one.")
    return candidates[0] if candidates else None


def local_model_name(model_path: str | Path) -> str | None:
    """``<name>`` for a ``local/<name>`` MODEL_PATH (pql-test's open-Desktop-model form), else None."""
    path = str(model_path).replace("\\", "/")
    if path.startswith("local/") and not Path(model_path).exists():
        return path[len("local/") :]
    return None


def repository_root(start: Path | None = None) -> Path:
    """The nearest folder at or above *start* (default: the current folder) holding ``.git``, else *start*."""
    start = (start or Path.cwd()).resolve()
    return next((p for p in (start, *start.parents) if (p / ".git").exists()), start)


def find_local_model_dir(name: str, root: Path) -> Path:
    """The one ``<name>.SemanticModel`` folder under *root*.

    Raises:
        ModelPathError: there is none, or there are several.
    """
    wanted = f"{name}.SemanticModel".lower()
    found = []
    for dirpath, dirnames, _ in os.walk(root):
        found += [Path(dirpath) / d for d in dirnames if d.lower() == wanted]
        # Skip hidden folders (.git, .venv), dependency trees, and the inside of any semantic model.
        dirnames[:] = [
            d for d in dirnames if not d.startswith(".") and d not in _SKIP_DIRS and not d.endswith(".SemanticModel")
        ]
    if len(found) == 1:
        return found[0]
    if found:
        listed = ", ".join(str(p) for p in sorted(found))
        raise ModelPathError(f"Several {name}.SemanticModel folders under {root}: {listed}. Pass the folder instead.")
    raise ModelPathError(
        f"No {name}.SemanticModel folder under {root}. local/{name} needs the model's PBIP folder in this "
        "repository; run from inside it, or pass the folder instead."
    )


def require_semantic_model_dir(model_path: str | Path) -> Path:
    """The ``*.SemanticModel`` folder for MODEL_PATH: a PBIP path, or ``local/<name>`` (found under the repository).

    Raises:
        ModelPathError: MODEL_PATH is not a PBIP path, or ``local/<name>`` has no single folder.
    """
    name = local_model_name(model_path)
    if name is not None:
        return find_local_model_dir(name, repository_root())
    found = find_semantic_model_dir(model_path)
    if found is None:
        raise ModelPathError(NOT_PBIP.format(path=str(model_path)))
    return found


def _tmdl_name(raw: str) -> str:
    if raw.startswith("'"):
        end = 1
        while end < len(raw):
            if raw[end] == "'" and raw[end + 1 : end + 2] != "'":
                break
            end += 2 if raw[end] == "'" else 1
        return raw[1:end].replace("''", "'")
    return raw


def model_columns(semantic_model_dir: Path) -> dict[str, dict[str, str | None]]:
    """``table -> {column: TMDL dataType or None}`` read from ``definition/tables/*.tmdl`` (measures are ignored)."""
    columns: dict[str, dict[str, str | None]] = {}
    for tmdl in sorted((semantic_model_dir / "definition" / "tables").glob("*.tmdl")):
        table, column = None, None
        for line in tmdl.read_text(encoding="utf-8-sig").splitlines():
            if table is None:
                match = _TABLE_RE.match(line)
                if match:
                    table = _tmdl_name(match.group(1))
                    columns[table] = {}
                continue
            if line.startswith("\t") and not line.startswith("\t\t"):
                # A table-level line: a new column, or a measure/partition/... that ends the current one.
                match = _COLUMN_RE.match(line)
                column = _tmdl_name(match.group(1)) if match else None
                if column is not None:
                    columns[table][column] = None
                continue
            data_type = _DATA_TYPE_RE.match(line)
            if column is not None and data_type:
                columns[table][column] = data_type.group(1)
    return columns


def model_names(semantic_model_dir: Path) -> dict[str, set[str]]:
    """``table -> {columns}`` read from ``definition/tables/*.tmdl`` (measures are ignored)."""
    return {table: set(cols) for table, cols in model_columns(semantic_model_dir).items()}
