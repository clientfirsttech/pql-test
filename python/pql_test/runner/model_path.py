"""
Model path parsing and filesystem utilities.

This module handles parsing of MODEL_PATH arguments in three formats:
1. Filesystem path — PBIP root or .SemanticModel directory
2. local/<model_name> — Connect to locally-open Power BI Desktop
3. <workspace>.Workspace/<model>.SemanticModel — Fabric service path

Also provides helpers for discovering .SemanticModel directories, .pbip files,
and DAX test files within PBIP models.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Optional

from pql_test.runner.models import ModelIdentifier, PqlTest

__all__ = [
    "parse_model_identifier",
    "_find_semantic_model_dir",
    "_find_pbip_file",
    "_collect_dax_test_files",
    "_parse_dax_test_file",
    "_discover_local_test_names",
    "_has_local_ownership_sources",
]


def parse_model_identifier(model_path: str) -> ModelIdentifier:
    """Parse a *model_path* CLI argument into a :class:`ModelIdentifier`.

    Detection rules (applied in order):

    1. Starts with ``local/`` **and** the path does not exist on the local
       filesystem → ``kind='local'``, *model_name* is the remainder.
    2. Matches the canonical Fabric-style service path
       ``<workspace>.Workspace/<model>.SemanticModel`` (forward- or
       back-slash separator) and does not exist on the filesystem →
       ``kind='service'``, suffixes are stripped from each part.
    3. Contains at least one ``.``, does not look like a path, and does not
       exist on the filesystem → legacy dot notation ``<workspace>.<model>``
       → ``kind='service'``.  Emits a one-line deprecation warning on stderr.
    4. Otherwise → ``kind='path'`` (traditional filesystem path).
    """
    # 1. local/<model_name>
    if model_path.startswith("local/") and not Path(model_path).exists():
        name = model_path[len("local/") :]
        return ModelIdentifier(kind="local", model_name=name, raw=model_path)

    # 2. Canonical Fabric-style: <workspace>.Workspace/<model>.SemanticModel
    # (or backslash form). Anchored on the suffixes so workspaces with dots
    # in their names parse unambiguously.  Suffix matching is
    # case-insensitive — give the user the benefit of the doubt if they type
    # ``.workspace`` / ``.semanticmodel`` in a different case.  We still
    # require BOTH suffixes: ``.SemanticModel`` alone is also the local PBIP
    # directory convention, so demanding both keeps service paths
    # distinguishable from a filesystem path like ``dir/Model.SemanticModel``.
    if not Path(model_path).exists():
        # Try both '/' and '\\' as separators — Fabric exports use '/', but
        # users on Windows may type the path with '\\'.
        for sep in ("/", "\\"):
            if sep in model_path:
                ws_part, _, model_part = model_path.partition(sep)
                if ws_part.lower().endswith(".workspace") and model_part.lower().endswith(
                    ".semanticmodel"
                ):
                    ws = ws_part[: -len(".Workspace")]
                    sm = model_part[: -len(".SemanticModel")]
                    if ws and sm:
                        return ModelIdentifier(
                            kind="service",
                            workspace_name=ws,
                            model_name=sm,
                            raw=model_path,
                        )

    # 3. Legacy <workspace>.<model> dot notation — deprecated but still
    # supported.  Reject any path containing a separator: those are either
    # filesystem paths (handled in step 4) or malformed Fabric-style paths
    # that we don't want to silently coerce into a dot split.
    if (
        not model_path.startswith(("./", "/", "\\"))
        and "/" not in model_path
        and "\\" not in model_path
        and "." in model_path
        and not Path(model_path).exists()
    ):
        dot_idx = model_path.rfind(".")
        ws = model_path[:dot_idx]
        sm = model_path[dot_idx + 1 :]
        if ws and sm:
            print(
                f"Note: '<workspace>.<model>' dot notation is deprecated. "
                f"Use the canonical Fabric form instead: "
                f"'{ws}.Workspace/{sm}.SemanticModel'.",
                file=sys.stderr,
            )
            return ModelIdentifier(
                kind="service",
                workspace_name=ws,
                model_name=sm,
                raw=model_path,
            )

    # 4. Filesystem path (default)
    return ModelIdentifier(kind="path", raw=model_path)


def _find_semantic_model_dir(model_path: str) -> Optional[str]:
    """Return the .SemanticModel directory for a PBIP model.

    Accepts any of:
    - The PBIP root directory (parent of the .SemanticModel folder)  <- canonical
    - The .SemanticModel directory itself
    - A .pbip file (the .SemanticModel whose stem matches the .pbip's stem
      is preferred so flat layouts with multiple models in one folder
      resolve to the correct model)
    """
    p = Path(model_path)
    if not p.exists():
        return None
    # Passed the .SemanticModel directory directly
    if p.is_dir() and p.name.endswith(".SemanticModel"):
        return str(p)
    # Passed a .pbip file — prefer the .SemanticModel whose stem matches the
    # .pbip's stem.  This mirrors the logic in _find_pbip_file and keeps
    # flat layouts (e.g. examples/ with three side-by-side .pbip files)
    # resolving to the correct model instead of whichever .SemanticModel
    # iterdir() happens to yield first.
    if p.is_file() and p.suffix == ".pbip":
        pbip_stem = p.stem
        parent = p.parent
        sibling = parent / f"{pbip_stem}.SemanticModel"
        if sibling.is_dir():
            return str(sibling)
        p = parent
    # Standard: scan the directory for a .SemanticModel subdirectory
    if p.is_dir():
        for entry in p.iterdir():
            if entry.name.endswith(".SemanticModel") and entry.is_dir():
                return str(entry)
    return None


def _find_pbip_file(model_path: str) -> Optional[str]:
    """Return the .pbip file path for a PBIP model root, or None.

    Accepts:
    - The PBIP root directory (scanned directly)
    - The .SemanticModel directory (parent is scanned, but the .pbip
      whose stem matches the .SemanticModel directory's stem is preferred
      so flat layouts with multiple models in one folder still resolve
      to the correct .pbip)
    """
    p = Path(model_path)
    if not p.exists():
        return None
    # If given the .SemanticModel dir, prefer the .pbip whose stem matches
    # the directory's stem.  This makes ``examples/`` (which holds
    # SampleModel.pbip, RLS_Model.pbip, OLS_Model.pbip side-by-side)
    # resolve correctly instead of picking whichever .pbip iterdir() yields
    # first.
    if p.is_dir() and p.name.endswith(".SemanticModel"):
        stem = p.name[: -len(".SemanticModel")]
        sibling = p.parent / f"{stem}.pbip"
        if sibling.is_file():
            return str(sibling)
        p = p.parent
    for entry in p.iterdir():
        if entry.name.endswith(".pbip") and entry.is_file():
            return str(entry)
    return None


def _collect_dax_test_files(semantic_model_dir: str) -> list[str]:
    """Return all *.Tests.dax file paths from the DAXQueries/ folder."""
    dax_dir = Path(semantic_model_dir) / "DAXQueries"
    if not dax_dir.exists():
        return []
    return sorted(str(f) for f in dax_dir.iterdir() if f.name.endswith(".Tests.dax"))


def _parse_dax_test_file(file_path: str) -> PqlTest:
    """Parse a *.Tests.dax file into a PqlTest descriptor."""
    source = Path(file_path).read_text(encoding="utf-8")
    name = Path(file_path).stem  # basename without .dax extension
    func_match = re.search(r"FUNCTION\s+([\w.]+)\s*=", source, re.IGNORECASE)
    description = f"DAX function: {func_match.group(1)}" if func_match else None
    return PqlTest(
        name=name, file_path=file_path, source=source, description=description
    )


_LOCAL_TEST_FUNCTION_RE = re.compile(
    r"function\s+'([^']+\.(?:Test|Tests))'\s*=", re.IGNORECASE | re.MULTILINE
)


def _discover_local_test_names(model_path: str) -> set[str]:
    """Return the set of test names declared locally in *model_path*.

    A name is "local" if it appears either as a
    ``function '<Name>.Test(s)' = ...`` declaration in
    ``definition/functions.tmdl`` or as the stem of a
    ``DAXQueries/<Name>.Tests.dax`` file.

    Returns an empty set when the path is not a recognisable PBIP model
    directory (``local/<name>`` or Fabric ``workspace.semantic_model``)
    or when the model lacks any ownership-declaring artifact.  Use
    :func:`_has_local_ownership_sources` to disambiguate these cases.
    """
    names: set[str] = set()
    semantic_model_dir = _find_semantic_model_dir(model_path)
    if not semantic_model_dir:
        return names

    for f in _collect_dax_test_files(semantic_model_dir):
        names.add(Path(f).stem)

    functions_tmdl = Path(semantic_model_dir) / "definition" / "functions.tmdl"
    if functions_tmdl.is_file():
        try:
            text = functions_tmdl.read_text(encoding="utf-8")
        except OSError:
            text = ""
        for match in _LOCAL_TEST_FUNCTION_RE.finditer(text):
            names.add(match.group(1))

    return names


def _has_local_ownership_sources(model_path: str) -> bool:
    """Return True when *model_path* declares ownership-tracking artifacts.

    Returns True if any of these exist:
    - DAXQueries/ directory (even if empty)
    - definition/functions.tmdl file

    Used to distinguish "no tests found because this isn't a PBIP model"
    from "this is a PBIP model but it has no tests yet".
    """
    semantic_model_dir = _find_semantic_model_dir(model_path)
    if not semantic_model_dir:
        return False

    sm_path = Path(semantic_model_dir)
    dax_dir = sm_path / "DAXQueries"
    functions_tmdl = sm_path / "definition" / "functions.tmdl"

    return dax_dir.exists() or functions_tmdl.is_file()
