# SPDX-License-Identifier: MIT
"""PBIP folder helpers: locate the ``*.SemanticModel`` folder and read TMDL table/column names."""

from __future__ import annotations

import re
from pathlib import Path

NOT_PBIP = (
    "MODEL_PATH {path!r} is not a PBIP folder (no *.SemanticModel found). pql-odcs v0.1 writes "
    "*.Tests.dax files into a PBIP model's DAXQueries/ folder; query-scoped XMLA runs arrive in "
    "v0.2 (--target query) and persistent deploys in v0.3 (--target deploy)."
)
NOT_PBIP_LOCAL = (
    "MODEL_PATH {path!r} names a model open in Power BI Desktop, but pql-odcs reads the PBIP folder on "
    "disk and never connects. Pass the folder (for example ./{name}.SemanticModel), or check the open "
    "model with `pql-test contract run CONTRACT {path} --env ENV`."
)
_TABLE_RE = re.compile(r"^table\s+(.+?)\s*$")
_COLUMN_RE = re.compile(r"^\s+column\s+(.+?)\s*(?:=.*)?$")


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


def require_semantic_model_dir(model_path: str | Path) -> Path:
    found = find_semantic_model_dir(model_path)
    if found is None:
        path = str(model_path).replace("\\", "/")
        if path.startswith("local/"):
            # pql-test's identifier for an open Desktop model: say so instead of "not a PBIP folder".
            raise ModelPathError(NOT_PBIP_LOCAL.format(path=str(model_path), name=path[len("local/") :]))
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


def model_names(semantic_model_dir: Path) -> dict[str, set[str]]:
    """``table -> {columns}`` read from ``definition/tables/*.tmdl`` (measures are ignored)."""
    names: dict[str, set[str]] = {}
    for tmdl in sorted((semantic_model_dir / "definition" / "tables").glob("*.tmdl")):
        table = None
        for line in tmdl.read_text(encoding="utf-8-sig").splitlines():
            if table is None:
                match = _TABLE_RE.match(line)
                if match:
                    table = _tmdl_name(match.group(1))
                    names[table] = set()
                continue
            match = _COLUMN_RE.match(line)
            if match and line.startswith("\t") and not line.startswith("\t\t"):
                names[table].add(_tmdl_name(match.group(1)))
    return names
