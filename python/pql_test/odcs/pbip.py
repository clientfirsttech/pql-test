# SPDX-License-Identifier: AGPL-3.0-only
"""PBIP folder helpers: locate the ``*.SemanticModel`` folder and read TMDL table/column names."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

NOT_PBIP = (
    "MODEL_PATH {path!r} is not a PBIP model (no *.SemanticModel found). Pass the PBIP root folder, its "
    "*.SemanticModel folder, its .pbip file, or local/<name> for a model in this repository."
)
# Folders never searched for a local/<name> model's PBIP folder.
_SKIP_DIRS = {"node_modules", "__pycache__", "site-packages"}
_TABLE_RE = re.compile(r"^table\s+(.+?)\s*$")
# A quoted name ('a = b', with '' for ') is matched whole, so an "=" inside it does not end the name.
# The "=" after the name starts a calculated column's DAX (or a measure's).
_COLUMN_RE = re.compile(r"^\s+column\s+('(?:[^']|'')*'|[^'=]+?)\s*(=.*)?$")
_MEASURE_RE = re.compile(r"^\s+measure\s+('(?:[^']|'')*'|[^'=]+?)\s*(?:=.*)?$")
_CALCULATED_PARTITION_RE = re.compile(r"^\s+partition\s+.*=\s*calculated\s*$")
_DATA_TYPE_RE = re.compile(r"^\t\tdataType:\s*(\S+)\s*$")
# Power BI's automatic date/time tables: not part of the model anyone wrote.
AUTO_DATE_TABLE_RE = re.compile(r"^(LocalDateTable_|DateTableTemplate_)")


@dataclass(frozen=True)
class ModelColumn:
    """One column in a table's TMDL."""

    name: str
    data_type: str | None = None  # TMDL dataType, None when the file gives none
    hidden: bool = False
    calculated: bool = False  # its values come from DAX: `column X = <DAX>`, or a calculated table's column


@dataclass(frozen=True)
class ModelTable:
    """One ``definition/tables/*.tmdl`` table: its columns, measures, and kind."""

    name: str
    columns: tuple[ModelColumn, ...] = ()
    measures: tuple[str, ...] = ()
    calculated: bool = False  # partition = calculated
    calculation_group: bool = False


def is_measure_table(table: ModelTable, related: set[str]) -> bool:
    """True for a table that only holds measures, such as a ``_Measures`` table: it has measures and only
    hidden columns, and no relationship (*related*: lower-case names of tables in one). A fact table that
    hides its columns and shows only measures still joins its dimensions, so it is not one."""
    return bool(table.measures) and all(c.hidden for c in table.columns) and table.name.lower() not in related


def related_tables(relationships) -> set[str]:
    """Lower-case names of every table at either end of *relationships* ``(from table, column, to table, column)``."""
    return {end.lower() for r in relationships for end in (r[0], r[2])}


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


def _scan_table(lines: list[str]) -> ModelTable | None:
    """The table one TMDL file defines, or None when it defines none."""
    name, columns, measures = None, {}, []
    column, calculated_table, calculation_group = None, False, False
    for line in lines:
        if name is None:
            match = _TABLE_RE.match(line)
            if match:
                name = _tmdl_name(match.group(1))
            continue
        if line.startswith("\t") and not line.startswith("\t\t"):
            # A table-level line: a new column, or a measure/partition/... that ends the current one.
            match = _COLUMN_RE.match(line)
            column = _tmdl_name(match.group(1)) if match else None
            if match:
                columns[column] = {"data_type": None, "hidden": False, "calculated": match.group(2) is not None}
            measure = _MEASURE_RE.match(line)
            if measure:
                measures.append(_tmdl_name(measure.group(1)))
            calculated_table = calculated_table or bool(_CALCULATED_PARTITION_RE.match(line))
            calculation_group = calculation_group or line.strip() == "calculationGroup"
            continue
        if column is None:
            continue
        data_type = _DATA_TYPE_RE.match(line)
        if data_type:
            columns[column]["data_type"] = data_type.group(1)
        elif line.strip() in ("isHidden", "isHidden: true"):
            columns[column]["hidden"] = True
    if name is None:
        return None
    return ModelTable(
        name=name,
        columns=tuple(
            ModelColumn(c, f["data_type"], f["hidden"], f["calculated"] or calculated_table) for c, f in columns.items()
        ),
        measures=tuple(measures),
        calculated=calculated_table,
        calculation_group=calculation_group,
    )


def model_tables(semantic_model_dir: Path) -> tuple[ModelTable, ...]:
    """Every table in ``definition/tables/*.tmdl``, in case-insensitive file-name order (the same on every OS)."""
    files = sorted((semantic_model_dir / "definition" / "tables").glob("*.tmdl"), key=lambda p: p.name.lower())
    scanned = (_scan_table(f.read_text(encoding="utf-8-sig").splitlines()) for f in files)
    return tuple(t for t in scanned if t is not None)


def _scan_tables(semantic_model_dir: Path) -> dict[str, ModelTable]:
    return {t.name: t for t in model_tables(semantic_model_dir)}


def _tmdl_column_ref(raw: str) -> tuple[str, str]:
    """``(table, column)`` from a TMDL ``Table.Column`` reference; either part may be quoted."""
    raw = raw.strip()
    if raw.startswith("'"):
        table = _tmdl_name(raw)
        rest = raw[len(table.replace("'", "''")) + 2 :]
    else:
        table, _, rest = raw.partition(".")
        rest = "." + rest
    return table, _tmdl_name(rest[1:])


# A relationship's settings as Relationship.ShouldExist names them, with Power BI's value when TMDL omits the line.
RELATIONSHIP_DEFAULTS = {
    "fromCardinality": "Many",
    "toCardinality": "One",
    "securityFilteringBehavior": "OneDirection",
    "crossFilteringBehavior": "OneDirection",
    "isActive": "TRUE",
}
# TMDL enum value (any case) -> the name Relationship.ShouldExist reports.
_TMDL_SETTING_VALUES = {
    v.lower(): v for v in ("Many", "One", "OneDirection", "BothDirections", "Automatic", "None", "TRUE", "FALSE")
}

RelationshipEnds = tuple[str, str, str, str]


def _tmdl_relationships(semantic_model_dir: Path) -> list[tuple[RelationshipEnds, dict[str, str]]]:
    """``(ends, settings)`` per relationship in ``definition/relationships.tmdl``; absent settings get defaults."""
    tmdl = semantic_model_dir / "definition" / "relationships.tmdl"
    if not tmdl.is_file():
        return []
    found, ends, settings = [], {}, {}
    for line in [*tmdl.read_text(encoding="utf-8-sig").splitlines(), "relationship"]:
        stripped = line.strip()
        if stripped.startswith("relationship") and not line.startswith("\t"):
            if "fromColumn" in ends and "toColumn" in ends:
                found.append(((*ends["fromColumn"], *ends["toColumn"]), {**RELATIONSHIP_DEFAULTS, **settings}))
            ends, settings = {}, {}
            continue
        key, _, value = stripped.partition(":")
        if key in ("fromColumn", "toColumn"):
            ends[key] = _tmdl_column_ref(value)
        elif key in RELATIONSHIP_DEFAULTS:
            value = value.strip()
            settings[key] = _TMDL_SETTING_VALUES.get(value.lower(), value)
    return found


def model_relationships(semantic_model_dir: Path) -> set[RelationshipEnds]:
    """``(from table, from column, to table, to column)`` per relationship in ``definition/relationships.tmdl``."""
    return {ends for ends, _settings in _tmdl_relationships(semantic_model_dir)}


def model_relationship_settings(semantic_model_dir: Path) -> dict[RelationshipEnds, dict[str, str]]:
    """Each relationship's settings (``fromCardinality``, ..., ``isActive``), by its ends, as ShouldExist names them."""
    return dict(_tmdl_relationships(semantic_model_dir))


def model_columns(semantic_model_dir: Path) -> dict[str, dict[str, str | None]]:
    """``table -> {column: TMDL dataType or None}`` read from ``definition/tables/*.tmdl`` (measures are ignored)."""
    return {name: {c.name: c.data_type for c in t.columns} for name, t in _scan_tables(semantic_model_dir).items()}


def measure_tables(semantic_model_dir: Path) -> set[str]:
    """Tables that only hold measures (and hidden placeholder columns), such as a ``_Measures`` table."""
    related = related_tables(model_relationships(semantic_model_dir))
    return {name for name, t in _scan_tables(semantic_model_dir).items() if is_measure_table(t, related)}


def model_names(semantic_model_dir: Path) -> dict[str, set[str]]:
    """``table -> {columns}`` read from ``definition/tables/*.tmdl`` (measures are ignored)."""
    return {table: set(cols) for table, cols in model_columns(semantic_model_dir).items()}
