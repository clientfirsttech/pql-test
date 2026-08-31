"""
PQL Test Runner — Core library for discovering and executing DAX tests.

Tests live in the SemanticModel's DAXQueries/ folder as .dax files whose
names match the pattern *.Tests.dax (e.g. Calculations.DEV.Tests.dax).

Execution uses pyadomd (ADOMD.NET Python wrapper) to send DAX queries via
XMLA to either a locally-open Power BI Desktop instance or a Power BI
Premium / Fabric workspace endpoint — mirroring the Invoke-DQVTesting pattern.

Service principal authentication is supported via msal for remote XMLA
connections, which enables row-level security calls with service principals.

XMLA connection resolution priority:
  1. Remote workspace endpoint (tenant_id + workspace_id + dataset_id).
     Service principal credentials (client_id + client_secret) are used
     to acquire an OAuth2 access token via MSAL — matching the auth flow
     used by Invoke-DQVTesting for CI/CD build agents.
  2. Local Power BI Desktop (localhost:NNNNN) — detected automatically when
     a .pbip file exists in model_path and a PBIDesktop process is running.

Results are parsed from the standard 4-column PQL.Assert schema:
  [TestName], [Expected], [Actual], [Passed]
Best-practice files (BestPractices.*.Tests.dax) return a 5-column schema;
the extra RuleDescription column is surfaced automatically.

Dependencies
------------
  pyadomd  — pip install pyadomd  (requires .NET / ADOMD.NET on Windows)
  msal     — pip install msal     (required for service-principal auth)
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
from dataclasses import dataclass, replace as _dc_replace
from enum import Enum
from pathlib import Path
from typing import ClassVar, Optional

# Force UTF-8 on stdout/stderr so Unicode glyphs (e.g. ✗, ✓) and any non-ASCII
# data in DAX results don't crash on Windows, where stdout defaults to cp1252.
# Wrapped in try/except because in pytest capture and some embedded contexts
# stdout/stderr can be a buffer object that doesn't expose .reconfigure().
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

# ---------------------------------------------------------------------------
# ADOMD.NET loading
#
# pip install pythonnet   (pythonnet >= 3)
# pip install pyadomd     (optional convenience wrapper — not used directly)
#
# Pattern (mirrors the official pythonnet example):
#   sys.path.append(<dir containing the ADOMD DLL>)
#   clr.AddReference("Microsoft.AnalysisServices.AdomdClient")
#   from Microsoft.AnalysisServices.AdomdClient import AdomdConnection
#
# PBI Desktop ships Microsoft.PowerBI.AdomdClient.dll in its bin/ folder, but
# the .NET namespace inside is still Microsoft.AnalysisServices.AdomdClient, so
# clr.AddReference works once the DLL directory is on sys.path.
# ---------------------------------------------------------------------------

HAS_PYADOMD = False
_AdomdConnection = None  # set to AdomdConnection class after successful load


def _discover_adomd_search_dirs() -> list[str]:
    import glob

    # ORDER MATTERS: pythonnet's clr.AddReference resolves by name against
    # whatever's first on sys.path.  We put NuGet ahead of system-wide
    # Microsoft.NET\ADOMD.NET paths because GitHub windows-latest runners
    # ship with an old AS client under C:\Program Files\Microsoft.NET\
    # ADOMD.NET\160 that mishandles bearer-token + Roles= + RLS-filter
    # roles (causes "Either the database '<name>' does not exist..." even
    # when the SPN is a workspace admin).  The actively-maintained NuGet
    # package fixes the bug.
    dirs: list[str] = []

    # 1. NuGet-installed AdomdClient — preferred.  Two package ids supported:
    #   • Microsoft.AnalysisServices.AdomdClient (modern, actively
    #     maintained, lib/net472 — required for the bearer + Roles= +
    #     RLS-filter combination)
    #   • Microsoft.AnalysisServices.AdomdClient.retail.amd64 (legacy,
    #     lib/net45 — capped at 19.84.1, contains the RLS bug)
    user_profile = os.environ.get("USERPROFILE", "")
    if user_profile:
        for pkg_id, lib_dir in (
            ("microsoft.analysisservices.adomdclient", "net472"),
            ("microsoft.analysisservices.adomdclient.retail.amd64", "net45"),
        ):
            nuget_glob = os.path.join(
                user_profile,
                ".nuget",
                "packages",
                pkg_id,
                "*",
                "lib",
                lib_dir,
            )
            # Newest version first
            dirs.extend(sorted(glob.glob(nuget_glob), reverse=True))

    # 2. Power BI Desktop installer version (.exe download).  Its bundled
    #    DLL is typically newer than the standalone ADOMD.NET releases.
    dirs.extend(
        [
            r"C:\Program Files\Microsoft Power BI Desktop\bin",
            r"C:\Program Files (x86)\Microsoft Power BI Desktop\bin",
        ]
    )

    # 3. Last resort: standalone Microsoft.NET ADOMD client paths.  Older
    #    builds here are the source of the CI RLS bug — keep them at the
    #    end so they're only used when nothing better is on the box.
    dirs.extend(
        [
            r"C:\Program Files\Microsoft.NET\ADOMD.NET\160",
            r"C:\Program Files\Microsoft.NET\ADOMD.NET\150",
            r"C:\Program Files\Microsoft.NET\ADOMD.NET\140",
        ]
    )
    return dirs


_ADOMD_SEARCH_DIRS = _discover_adomd_search_dirs()


# ---------------------------------------------------------------------------
# ADOMD.NET auto-install (NuGet bootstrap)
# ---------------------------------------------------------------------------
#
# When ADOMD.NET assemblies aren't already installed in any of the standard
# locations, we download the official Microsoft NuGet package
# (Microsoft.AnalysisServices.AdomdClient) and unpack its lib/net472/ DLLs
# into a user-local cache directory.  The next import (or this one, after
# the fetch) finds them via clr.AddReference exactly as if they'd been
# installed manually.
#
# This turns the brand-new-user install story from
#   1. install Python  2. install ADOMD.NET MSI  3. pip install pql-test
# into just
#   1. install Python  2. pip install pql-test         (auto-fetch on first use)
#
# Opt-outs:
#   * PQL_TEST_HERMETIC=1        — used by the test suite; skips everything.
#   * PQL_TEST_NO_AUTO_INSTALL_ADOMD=1  — for users who manage ADOMD.NET
#                                  themselves (corporate-managed machines,
#                                  air-gapped envs, custom NuGet feeds).

_ADOMD_AUTO_INSTALL_VERSION = "19.114.0"
_ADOMD_AUTO_INSTALL_PKG_ID = "microsoft.analysisservices.adomdclient"
_ADOMD_AUTO_INSTALL_LIB_FOLDER = "lib/net472"


def _adomd_assemblies_present(search_dirs: list[str]) -> bool:
    """Return True when any *search_dirs* entry contains an ADOMD.NET DLL.

    We accept either the standalone client (`Microsoft.AnalysisServices.
    AdomdClient.dll`, NuGet / installer redist) or the Power BI Desktop
    flavour (`Microsoft.PowerBI.AdomdClient.dll`) — the .NET namespace
    inside is the same.
    """
    candidate_files = (
        "Microsoft.AnalysisServices.AdomdClient.dll",
        "Microsoft.PowerBI.AdomdClient.dll",
    )
    for d in search_dirs:
        if not os.path.isdir(d):
            continue
        for name in candidate_files:
            if os.path.isfile(os.path.join(d, name)):
                return True
    return False


def _adomd_auto_install_cache_dir() -> Optional[str]:
    """Return the user-local cache path the auto-installer extracts to."""
    home = os.path.expanduser("~")
    if not home or home == "~":
        return None
    return os.path.join(
        home,
        ".pql-test",
        "adomd",
        _ADOMD_AUTO_INSTALL_PKG_ID,
        _ADOMD_AUTO_INSTALL_VERSION,
        *_ADOMD_AUTO_INSTALL_LIB_FOLDER.split("/"),
    )


def _auto_install_adomd_from_nuget() -> Optional[str]:
    """Download the Microsoft.AnalysisServices.AdomdClient NuGet package and
    extract its `lib/net472/` contents to the user cache.

    Returns the directory holding the extracted DLLs on success, or None on
    any failure (network error, opt-out, missing home directory, …).  This
    function is intentionally tolerant: callers fall back to the standard
    "ADOMD.NET not loaded" path when it returns None.
    """
    if os.environ.get("PQL_TEST_HERMETIC") or os.environ.get(
        "PQL_TEST_NO_AUTO_INSTALL_ADOMD"
    ):
        return None

    cache_dir = _adomd_auto_install_cache_dir()
    if cache_dir is None:
        return None

    # Already cached from a prior run — fast path.
    if os.path.isdir(cache_dir) and any(
        f.lower().endswith(".dll") for f in os.listdir(cache_dir)
    ):
        return cache_dir

    pkg = _ADOMD_AUTO_INSTALL_PKG_ID
    version = _ADOMD_AUTO_INSTALL_VERSION
    # NuGet flat-container public endpoint — no auth required.
    nupkg_url = (
        f"https://api.nuget.org/v3-flatcontainer/{pkg}/{version}/{pkg}.{version}.nupkg"
    )

    print(
        f"ADOMD.NET assemblies not detected. Downloading "
        f"{pkg} {version} from nuget.org to {cache_dir} (one-time, ~5 MB)...",
        file=sys.stderr,
    )

    import tempfile  # noqa: PLC0415 — avoid the cost on the fast path
    import urllib.request  # noqa: PLC0415
    import zipfile  # noqa: PLC0415

    tmp_path: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".nupkg", delete=False) as f:
            tmp_path = f.name
        urllib.request.urlretrieve(nupkg_url, tmp_path)
        os.makedirs(cache_dir, exist_ok=True)
        member_prefix = _ADOMD_AUTO_INSTALL_LIB_FOLDER + "/"
        with zipfile.ZipFile(tmp_path) as z:
            for member in z.namelist():
                if not member.startswith(member_prefix) or member.endswith("/"):
                    continue
                # Preserve subdirectory structure under lib/net472/ — the
                # NuGet package ships satellite-resource DLLs in culture
                # subdirs (de/, es/, zh-Hans/, …) and the .NET assembly
                # loader expects them in those subdirs to localise error
                # messages.  Flattening would collide every culture's
                # `*.resources.dll` to the same path.
                rel = member[len(member_prefix):]
                dest = os.path.join(cache_dir, *rel.split("/"))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with z.open(member) as src, open(dest, "wb") as out:
                    out.write(src.read())
        print(
            f"ADOMD.NET assemblies installed to {cache_dir}.  Subsequent runs "
            "use the cached install.",
            file=sys.stderr,
        )
        return cache_dir
    except Exception as exc:  # noqa: BLE001
        print(
            f"Warning: failed to auto-install ADOMD.NET ({type(exc).__name__}: "
            f"{exc}). Install manually from https://learn.microsoft.com/en-us/"
            f"analysis-services/client-libraries and retry, or run with "
            f"PQL_TEST_NO_AUTO_INSTALL_ADOMD=1 to silence this attempt.",
            file=sys.stderr,
        )
        return None
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


# Bootstrap: when none of the discovered directories already carry ADOMD
# assemblies, attempt a one-time fetch into the user-local cache.  No-op
# when assemblies are already present anywhere on the search path.
if not _adomd_assemblies_present(_ADOMD_SEARCH_DIRS):
    _auto_dir = _auto_install_adomd_from_nuget()
    if _auto_dir:
        _ADOMD_SEARCH_DIRS.append(_auto_dir)


try:
    import clr  # type: ignore[import-untyped]  # pythonnet

    for _d in _ADOMD_SEARCH_DIRS:
        if os.path.isdir(_d) and _d not in sys.path:
            sys.path.append(_d)

    # PBI Desktop ships Microsoft.PowerBI.AdomdClient.dll; the NuGet package and
    # standalone ADOMD.NET ship Microsoft.AnalysisServices.AdomdClient.dll. The
    # embedded .NET namespace is Microsoft.AnalysisServices.AdomdClient in both,
    # so the from-import stays the same — only the assembly name differs.
    for _assembly_name in (
        "Microsoft.PowerBI.AdomdClient",
        "Microsoft.AnalysisServices.AdomdClient",
    ):
        try:
            clr.AddReference(_assembly_name)
            break
        except Exception:
            continue
    from Microsoft.AnalysisServices.AdomdClient import (
        AdomdConnection as _AdomdConnection,
    )  # type: ignore[import]

    HAS_PYADOMD = True

    # One-line diagnostic so CI logs (and any local debugging) show exactly
    # which ADOMD.NET assembly pythonnet resolved — this caught a CI bug
    # where the older AS-shipped client on the runner shadowed our NuGet
    # install and triggered the bearer + Roles + RLS-filter failure.
    try:
        from System.Reflection import Assembly as _Assembly  # type: ignore[import]

        _asm = _Assembly.GetAssembly(_AdomdConnection)
        if _asm is not None:
            print(
                f"ADOMD.NET loaded: {_asm.Location} (version {_asm.GetName().Version})",
                file=sys.stderr,
            )
    except Exception:
        pass
except Exception:
    pass

try:
    import msal  # type: ignore[import-untyped]

    HAS_MSAL = True
except ImportError:
    HAS_MSAL = False

try:
    import psutil as _psutil  # type: ignore[import-untyped]

    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


# ---------------------------------------------------------------------------
# Cloud environment support
# ---------------------------------------------------------------------------


class Environment(str, Enum):
    """Supported Power BI cloud environments."""

    PUBLIC = "Public"
    GERMANY = "Germany"
    CHINA = "China"
    US_GOV = "USGov"
    US_GOV_HIGH = "USGovHigh"
    US_GOV_DOD = "USGovDoD"


@dataclass
class Endpoints:
    """API and auth endpoints for a Power BI cloud environment."""

    api_prefix: str
    resource_url: str
    login_url: str


def get_api_endpoints(environment: Environment = Environment.PUBLIC) -> Endpoints:
    """Return the correct API and auth endpoints for the given cloud environment."""
    if environment == Environment.GERMANY:
        return Endpoints(
            api_prefix="https://api.powerbi.de",
            resource_url="https://analysis.cloudapi.de/powerbi/api",
            login_url="https://login.microsoftonline.com",
        )
    if environment == Environment.CHINA:
        return Endpoints(
            api_prefix="https://api.powerbi.cn",
            resource_url="https://analysis.chinacloudapi.cn/powerbi/api",
            login_url="https://login.partner.microsoftonline.cn",
        )
    if environment == Environment.US_GOV:
        return Endpoints(
            api_prefix="https://api.powerbigov.us",
            resource_url="https://analysis.usgovcloudapi.net/powerbi/api",
            login_url="https://login.microsoftonline.com",
        )
    if environment == Environment.US_GOV_HIGH:
        return Endpoints(
            api_prefix="https://api.high.powerbigov.us",
            resource_url="https://analysis.high.usgovcloudapi.net/powerbi/api",
            login_url="https://login.microsoftonline.us",
        )
    if environment == Environment.US_GOV_DOD:
        return Endpoints(
            api_prefix="https://api.mil.powerbi.us",
            resource_url="https://analysis.dod.usgovcloudapi.net/powerbi/api",
            login_url="https://login.microsoftonline.us",
        )
    # Default: Public commercial cloud
    return Endpoints(
        api_prefix="https://api.powerbi.com",
        resource_url="https://analysis.windows.net/powerbi/api",
        login_url="https://login.microsoftonline.com",
    )


# ---------------------------------------------------------------------------
# Model identifier parsing
# ---------------------------------------------------------------------------


@dataclass
class ModelIdentifier:
    """Parsed model identifier from the CLI model_path argument.

    Supports three formats:

    * ``local/<model_name>`` — connect to a locally-open Power BI Desktop
      instance matching *model_name* (case-insensitive).  File-based test
      discovery is skipped; only live XMLA discovery is used.
    * ``<workspace>.<semantic_model>`` — connect to a remote Fabric /
      Power BI Premium workspace using the workspace and semantic-model
      display names directly, following the Fabric CLI dot notation
      (e.g. ``fab run``).  No local file path is needed.
    * A regular filesystem path — legacy behaviour, unchanged.
    """

    kind: str
    """One of ``'local'``, ``'service'``, or ``'path'``."""
    model_name: Optional[str] = None
    """Semantic-model display name (``local`` and ``service`` modes)."""
    workspace_name: Optional[str] = None
    """Workspace display name (``service`` mode only)."""
    raw: str = ""
    """The original model_path string as supplied by the user."""


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


# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------


@dataclass
class PqlTest:
    """A single DAX test file discovered in a PBIP model."""

    name: str
    """Test suite name derived from the file stem (e.g. 'Calculations.DEV.Tests')."""
    file_path: str
    """Absolute path to the .dax source file."""
    source: str
    """Raw DAX source."""
    description: Optional[str] = None
    """Optional description (FUNCTION name when present in the DAX source)."""
    impersonated_user_name: Optional[str] = None
    """RLS impersonation user (AAD UPN) from PQL.Assert.RetrieveTestsV2.  Used with service endpoints."""
    role_name: Optional[str] = None
    """RLS role name from PQL.Assert.RetrieveTestsV2 (PQLAssert_RoleName annotation).  Used with local connections."""


@dataclass
class TestResult:
    """Result of executing a single DAX assertion row."""

    # Suppress pytest collection: name starts with 'Test' but this is a dataclass
    __test__: ClassVar[bool] = False

    test_name: str
    passed: bool
    message: str
    skipped: bool = False
    error: Optional[str] = None
    duration_ms: Optional[float] = None
    actual: Optional[str] = None
    expected: Optional[str] = None
    suite_name: Optional[str] = None


@dataclass
class TestSuite:
    """Summary of a full test run against a model."""

    model_path: str
    tests: list[PqlTest]
    results: list[TestResult]
    passed: int
    failed: int
    skipped: int
    total: int


@dataclass
class XmlaConnectionOptions:
    """
    Connection parameters for XMLA execution.

    For remote Power BI Premium / Fabric connections, tenant_id and
    workspace_id are required, plus EITHER dataset_id OR dataset_name
    (the dataset's display name as it appears in the workspace).  When
    only dataset_name is supplied the resolver looks up the dataset via
    REST so the caller doesn't need to store GUIDs anywhere.

    client_id + client_secret are used to acquire an OAuth2 bearer
    token via the MSAL service-principal (client-credentials) flow.
    This is the same authentication pattern used by Invoke-DQVTesting
    when running in CI/CD pipelines against cloud-hosted models.

    access_token is an optional pre-acquired bearer token.  When set, the
    downstream resolver skips MSAL and uses this token directly.  Populated
    by ``_resolve_authentication_with_stored_credentials`` when a non-secret
    stored credential (interactive, certificate, federated, managed identity)
    is found — see tasks/unified-auth-runtime-epic.md.
    """

    tenant_id: Optional[str] = None
    workspace_id: Optional[str] = None
    dataset_id: Optional[str] = None
    dataset_name: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    environment: Environment = Environment.PUBLIC
    access_token: Optional[str] = None


@dataclass
class ResolvedXmlaConnection:
    """Resolved XMLA server, catalog, and optional auth details."""

    server: str
    catalog: str
    tenant_id: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    access_token: Optional[str] = None
    effective_user_name: Optional[str] = None
    """AAD UPN passed as EffectiveUserName; used for service-endpoint RLS simulation."""
    roles: Optional[str] = None
    """Semi-colon-separated role name(s) passed as Roles=; used for local-AS RLS simulation."""


@dataclass
class LocalPbiInstance:
    """
    A Power BI Desktop instance open on the local machine.

    Mirrors the custom object returned by Invoke-DQVTesting's
    Get-PowerBIFilesOpened for each detected process.
    """

    model_name: str
    """Window title with " - Power BI Desktop" suffix stripped."""
    server: str
    """XMLA server string, e.g. "localhost:63402"."""
    catalog: str
    """Catalog name or GUID from DBSCHEMA_CATALOGS."""


# ---------------------------------------------------------------------------
# Model discovery helpers
# ---------------------------------------------------------------------------


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

    A filesystem PBIP "owns" the tests it declares when its SemanticModel
    has a ``DAXQueries/`` directory (the canonical location for
    ``*.Tests.dax`` files) or a ``definition/functions.tmdl`` file.
    Returning True means an empty local test set is meaningful ("this
    model genuinely has no tests") and live discovery should be filtered
    strictly against it.  Returning False means the path either isn't a
    filesystem PBIP (``local/<name>``, Fabric ``workspace.model``) or is
    a bare PBIP skeleton with no declaration locations — in either case,
    live discovery is passed through unfiltered.
    """
    semantic_model_dir = _find_semantic_model_dir(model_path)
    if not semantic_model_dir:
        return False
    base = Path(semantic_model_dir)
    return (base / "DAXQueries").is_dir() or (base / "definition" / "functions.tmdl").is_file()


# ---------------------------------------------------------------------------
# Local Power BI Desktop detection — process-based (mirrors Invoke-DQVTesting)
# ---------------------------------------------------------------------------


def _get_pbi_process_window_titles(
    known_pbi_pids: Optional[set] = None,
) -> dict[int, str]:
    """
    Return {pid: window_title} for all visible Power BI Desktop windows.

    Mirrors the ``GetWindowText`` + ``EnumWindows`` approach used in
    Invoke-DQVTesting's Get-PowerBIFilesOpened to identify which
    PBIDesktop.exe processes are open and their model names.

    A window is included when EITHER its title contains the legacy
    ``" - Power BI Desktop"`` substring OR its PID belongs to
    *known_pbi_pids* (typically the set of running PBIDesktop.exe PIDs
    discovered via psutil).  The second path catches newer / Store
    builds whose window title is just the model name (e.g. ``OLS_Model``)
    with no app-name suffix.

    Windows only; returns an empty dict on other platforms.
    """
    import ctypes  # noqa: PLC0415

    titles: dict[int, str] = {}
    if not hasattr(ctypes, "windll"):
        return titles

    user32 = ctypes.windll.user32
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    known_pids = known_pbi_pids or set()

    def _callback(hwnd: int, _: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length: int = user32.GetWindowTextLengthW(hwnd) + 1
        if length <= 1:
            return True
        buf = ctypes.create_unicode_buffer(length)
        user32.GetWindowTextW(hwnd, buf, length)
        title: str = buf.value
        pid = ctypes.c_ulong(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value or pid.value in titles:
            return True
        if "Power BI Desktop" in title or pid.value in known_pids:
            titles[pid.value] = title
        return True

    user32.EnumWindows(WNDENUMPROC(_callback), 0)
    return titles


def _get_catalog_from_local_port(port: int) -> Optional[str]:
    """
    Verify connectivity to a local Power BI Desktop Analysis Services port
    by executing ``EVALUATE INFO.VIEW.MEASURES()``.

    For local PBI Desktop instances there is only one database per port, so
    no ``Initial Catalog`` is needed — the AS engine selects it automatically.
    Returns ``""`` (empty string) when the connection succeeds, or ``None``
    when pyadomd is unavailable or the connection fails.
    """
    if not HAS_PYADOMD:
        return None
    try:
        conn_str = f"Provider=MSOLAP;Data Source=localhost:{port};"
        adomd_conn = _AdomdConnection(conn_str)  # type: ignore[misc]
        adomd_conn.Open()
        try:
            cmd = adomd_conn.CreateCommand()
            cmd.CommandText = "EVALUATE INFO.VIEW.MEASURES()"
            reader = cmd.ExecuteReader()
            reader.Close()
            return ""
        finally:
            adomd_conn.Close()
    except Exception:  # noqa: BLE001
        pass
    return None


def _find_pbi_ancestor_pid(
    proc: "_psutil.Process",  # type: ignore[name-defined]
    pbi_pids: set,
    max_depth: int = 6,
) -> Optional[int]:
    """
    Walk the process parent chain of *proc* and return the first PID that
    appears in *pbi_pids* (a set of known PBIDesktop.exe PIDs).

    This handles the case where msmdsrv.exe is not a direct child of
    PBIDesktop.exe — modern Power BI Desktop versions may interpose one or more
    intermediate host processes between the two.
    """
    current = proc
    for _ in range(max_depth):
        try:
            ppid = current.ppid()
            if ppid in pbi_pids:
                return ppid
            current = _psutil.Process(ppid)
        except (_psutil.NoSuchProcess, _psutil.AccessDenied, ValueError):
            break
    return None


def get_pbi_files_opened() -> list[LocalPbiInstance]:
    """
    Discover all Power BI Desktop instances open on this machine.

    Mirrors Invoke-DQVTesting's ``Get-PowerBIFilesOpened``:

    1. Enumerate visible windows via ``EnumWindows`` + ``GetWindowText`` to
       find PBIDesktop.exe PIDs and model names (window title minus the
       " - Power BI Desktop" suffix).  When window enumeration fails (e.g.
       UAC integrity mismatch or Microsoft Store variant of PBI Desktop),
       this step produces an empty map but scanning continues.
    2. Find ``msmdsrv.exe`` processes.  Port detection uses the global
       ``psutil.net_connections()`` call (more reliable on Windows than
       per-process access) with a per-process fallback.
    3. Map each msmdsrv process to its parent PBIDesktop process by walking
       the process tree.  When no PBI window was found for a process, the
       model_name is left empty — resolve_local_xmla_connection handles the
       unnamed-instance fallback.
    4. Query ``$SYSTEM.DBSCHEMA_CATALOGS`` on each port (via pyadomd) to
       resolve the real catalog name/GUID that Power BI Desktop loaded.

    Requires ``psutil`` (``pip install psutil``).
    """
    if not HAS_PSUTIL:
        raise ImportError(
            "psutil is required for local Power BI Desktop detection. "
            "Install with: pip install psutil"
        )

    # Step 1a — discover the set of running PBIDesktop.exe PIDs and their
    # cmdline-derived model names (when the .pbip path is present).  We
    # do this BEFORE window enumeration so the EnumWindows pass can
    # accept any visible window owned by a known PBI pid — newer/Store
    # builds drop the legacy " - Power BI Desktop" suffix and would
    # otherwise be filtered out by the title-substring check.
    pbi_pid_to_model: dict[int, str] = {}
    for _fp in _psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            _pname = (_fp.info.get("name") or "").lower()
            if _pname != "pbidesktop.exe":
                continue
            _pid = int(_fp.info.get("pid") or 0)
            if not _pid:
                continue
            _model = ""
            for _arg in (_fp.info.get("cmdline") or [])[1:]:
                _p = Path(_arg)
                if _p.suffix.lower() in (".pbix", ".pbip"):
                    _model = _p.stem
                    break
            pbi_pid_to_model[_pid] = _model
        except (_psutil.NoSuchProcess, _psutil.AccessDenied):
            continue
    pbi_pids = set(pbi_pid_to_model.keys())

    # Step 1b — PID → window title mapping.  Pass the known PBI pids so
    # newer-build windows (just the model name, no app suffix) are also
    # captured.  Title trumps cmdline because the title reflects the
    # currently-loaded model after Save As / rename, whereas the cmdline
    # is frozen at process start.  A title-derived name only OVERWRITES
    # the cmdline name when it's non-empty after suffix-stripping.
    pid_to_raw_title = _get_pbi_process_window_titles(known_pbi_pids=pbi_pids)
    for pid, title in pid_to_raw_title.items():
        idx = title.rfind(" - ")
        model_name = title[:idx].strip() if idx > 0 else title.strip()
        if model_name:
            pbi_pid_to_model[pid] = model_name
            pbi_pids.add(pid)

    # Portable LISTEN status — psutil < 6 exposed CONN_LISTEN; psutil 6+ uses
    # the plain string "LISTEN".  Accept both so the code works on any version.
    _listen_status: object = getattr(_psutil, "CONN_LISTEN", "LISTEN")

    # Pre-build a pid → listen_port map using the global net_connections call.
    # This is more reliable on Windows than per-process net_connections() because
    # it queries GetExtendedTcpTable once for all connections and doesn't require
    # per-process handle access.  Falls back to per-process inspection if the
    # global call raises an exception (e.g. on some test environments).
    _global_listen_ports: dict[int, int] = {}
    try:
        for _c in _psutil.net_connections(kind="tcp"):
            _c_status = getattr(_c, "status", None)
            if (
                (_c_status == _listen_status or _c_status == "LISTEN")
                and _c.laddr
                and _c.laddr.ip in ("0.0.0.0", "::", "127.0.0.1")
                and getattr(_c, "pid", None) is not None
            ):
                _global_listen_ports[_c.pid] = _c.laddr.port
    except Exception:  # noqa: BLE001
        pass  # global call not available — fall back to per-process inspection

    # Step 2 & 3 — msmdsrv ports mapped back to parent PBIDesktop via PPID
    # (walking the full process tree, not just the immediate parent)
    instances: list[LocalPbiInstance] = []
    for proc in _psutil.process_iter(["pid", "name", "ppid"]):
        try:
            pname = (proc.info.get("name") or "").lower()
            if pname != "msmdsrv.exe":
                continue

            msmdsrv_pid: int = proc.info.get("pid") or 0

            # Try immediate parent first (fast path), then walk the tree.
            parent_pid: int = proc.info.get("ppid") or 0
            model_name = pbi_pid_to_model.get(parent_pid, "")
            if not model_name and pbi_pids:
                ancestor = _find_pbi_ancestor_pid(proc, pbi_pids)
                if ancestor is not None:
                    model_name = pbi_pid_to_model.get(ancestor, "")

            # Resolve the listen port: global map first, per-process fallback.
            port: Optional[int] = _global_listen_ports.get(msmdsrv_pid)
            if port is None:
                for conn in proc.net_connections(kind="tcp"):
                    conn_status = getattr(conn, "status", None)
                    if (
                        (conn_status == _listen_status or conn_status == "LISTEN")
                        and conn.laddr
                        and conn.laddr.ip in ("0.0.0.0", "::", "127.0.0.1")
                    ):
                        port = conn.laddr.port
                        break

            if port is not None:
                # Step 4 — verify connectivity; local AS auto-selects the single database
                _cat = _get_catalog_from_local_port(port)
                catalog = _cat if _cat is not None else ""
                instances.append(
                    LocalPbiInstance(
                        model_name=model_name,
                        server=f"localhost:{port}",
                        catalog=catalog,
                    )
                )
        except (_psutil.NoSuchProcess, _psutil.AccessDenied):
            continue

    return instances


def resolve_local_xmla_connection(
    model_path: str,
) -> Optional[ResolvedXmlaConnection]:
    """
    Resolve XMLA connection for a locally open Power BI Desktop model.

    Mirrors Invoke-DQVTesting's ``-Local`` switch:

    1. Calls ``get_pbi_files_opened()`` to enumerate all running PBI Desktop
       instances using process inspection + TCP port detection.
    2. Matches the detected model name (window title) against the ``.pbip``
       file stem from ``model_path`` (case-insensitive).
    3. Falls back to reading the ``msmdsrv.port.txt`` file when psutil is
       unavailable.

    Parameters
    ----------
    model_path:
        Root directory of the PBIP model.
    """
    pbip = _find_pbip_file(model_path)
    model_name = Path(pbip).stem if pbip else None

    # Fallback: derive model name from the .SemanticModel directory stem
    if model_name is None:
        p = Path(model_path)
        if p.is_dir() and p.name.endswith(".SemanticModel"):
            model_name = p.name[: -len(".SemanticModel")]

    try:
        instances = get_pbi_files_opened()
    except ImportError:
        # psutil not installed — fall back to port-file approach
        port = _detect_local_pbi_desktop_port()
        if port:
            return ResolvedXmlaConnection(server=port, catalog="")
        return None

    if not instances:
        # No running PBI Desktop found via process detection; try port-file
        port_str = _detect_local_pbi_desktop_port()
        if port_str:
            return ResolvedXmlaConnection(server=port_str, catalog="")
        return None

    if model_name:
        for inst in instances:
            if inst.model_name.lower() == model_name.lower():
                return ResolvedXmlaConnection(
                    server=inst.server,
                    catalog=inst.catalog,
                )
        # No exact name match.  If all detected instances have an empty
        # model_name (process-tree walk couldn't link them to a PBI window)
        # and there is exactly one PBI Desktop window open, it is safe to
        # assume that the single running instance belongs to the requested
        # model.  This handles edge cases where msmdsrv.exe cannot be linked
        # to its PBIDesktop.exe ancestor via the process tree.
        unnamed = [i for i in instances if not i.model_name]
        named = [i for i in instances if i.model_name]
        if unnamed and not named:
            # Every detected port is unlinked; use the first one only when
            # there is a single PBI Desktop window (unambiguous).
            if len(instances) == 1:
                return ResolvedXmlaConnection(
                    server=instances[0].server,
                    catalog=instances[0].catalog,
                )
        return None

    # No .pbip file in model_path — use the first detected instance
    inst = instances[0]
    return ResolvedXmlaConnection(server=inst.server, catalog=inst.catalog)


# ---------------------------------------------------------------------------
# Local Power BI Desktop detection — port-file fallback
# ---------------------------------------------------------------------------


def _detect_local_pbi_desktop_port() -> Optional[str]:
    """
    Detect the Analysis Services port used by an open Power BI Desktop instance.

    Power BI Desktop writes the port number to:
      %LOCALAPPDATA%\\Microsoft\\Power BI Desktop\\
          AnalysisServicesWorkspaces\\AnalysisServicesWorkspace<port>\\
          Data\\msmdsrv.port.txt

    Returns a connection string like "localhost:50001" when found.
    """
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return None

    # Candidate base paths — standard installer and Microsoft Store package
    _ws_candidates = [
        Path(local_app_data)
        / "Microsoft"
        / "Power BI Desktop"
        / "AnalysisServicesWorkspaces",
    ]
    # Microsoft Store version stores data under the package's LocalState
    _packages_root = Path(local_app_data) / "Packages"
    if _packages_root.exists():
        for _pkg in _packages_root.iterdir():
            if _pkg.name.startswith("Microsoft.MicrosoftPowerBIDesktop"):
                _ws_candidates.append(
                    _pkg
                    / "LocalState"
                    / "Microsoft"
                    / "Power BI Desktop"
                    / "AnalysisServicesWorkspaces"
                )
                break  # only one PBI Desktop Store package expected

    for ws_base in _ws_candidates:
        if not ws_base.exists():
            continue
        for ws_dir in ws_base.iterdir():
            port_file = ws_dir / "Data" / "msmdsrv.port.txt"
            if port_file.exists():
                # PBI Desktop writes this file as UTF-16 LE (no BOM)
                port = port_file.read_text(encoding="utf-16-le").strip()
                if port.isdigit():
                    return f"localhost:{port}"
    return None


# ---------------------------------------------------------------------------
# XMLA connection resolution
# ---------------------------------------------------------------------------


def _resolve_authentication_with_stored_credentials(
    opts: XmlaConnectionOptions,
) -> XmlaConnectionOptions:
    """
    Resolve authentication credentials with fallback to stored credentials.

    Priority:
      1. CLI flags (opts.tenant_id, opts.client_id, opts.client_secret)
      2. Environment variables (PQL_TENANT_ID, PQL_CLIENT_ID, PQL_CLIENT_SECRET)
      3. Stored credentials (from ``pql-test auth login``)

    For stored credentials the behavior depends on the chosen auth method:

    * ``SERVICE_PRINCIPAL_SECRET`` — the secret is forwarded as
      ``client_secret`` so the downstream resolver runs MSAL's
      client-credentials flow (legacy code path, preserved bit-for-bit).
    * ``INTERACTIVE`` / ``SERVICE_PRINCIPAL_CERT`` /
      ``SERVICE_PRINCIPAL_FEDERATED`` / ``MANAGED_IDENTITY`` — a bearer token
      is acquired via ``AuthenticationManager.get_access_token`` (which uses
      the appropriate ``azure-identity`` credential class under the hood) and
      attached to ``opts.access_token``. The downstream resolver then hands
      that bearer to ADOMD via the existing MSOLAP ``Password=<bearer>;``
      connection-string segment.

    See tasks/unified-auth-runtime-epic.md.
    """
    # Hermetic test mode skips all developer-machine state: no .env, no
    # stored credentials, no token acquisition.  Tests that need a
    # connection mock it explicitly.
    import os
    if os.environ.get("PQL_TEST_HERMETIC"):
        return opts

    # If any credentials are already provided (even partial), return as-is
    # This preserves the existing validation behavior where partial credentials fail
    if opts.tenant_id or opts.client_id or opts.client_secret:
        return opts

    # Check if credentials are in environment variables

    env_tenant = os.getenv("PQL_TENANT_ID")
    env_client = os.getenv("PQL_CLIENT_ID")
    env_secret = os.getenv("PQL_CLIENT_SECRET")

    if env_tenant or env_client or env_secret:
        # Use environment variables (may be partial, but that's intentional)
        return XmlaConnectionOptions(
            tenant_id=env_tenant or opts.tenant_id,
            workspace_id=opts.workspace_id,
            dataset_id=opts.dataset_id,
            client_id=env_client or opts.client_id,
            client_secret=env_secret or opts.client_secret,
            environment=opts.environment,
        )

    # Fallback to stored credentials only when NO credentials provided at all
    try:
        from pql_test.auth import AuthenticationManager, AuthMethod

        manager = AuthenticationManager()
        status = manager.get_status()

        if not status.authenticated:
            return opts  # No stored credentials

        config = manager._store.load()
        if config is None:
            return opts

        # The stored credential records which cloud it was created for
        # (`pql-test auth login --environment`), so the credential and its
        # cloud travel together — a USGov login should never be aimed at
        # the Public endpoints.  Fall back to opts.environment when the
        # stored value doesn't parse.
        stored_env = opts.environment
        for e in Environment:
            if e.value.lower() == (config.environment or "").strip().lower():
                stored_env = e
                break

        # SPN-with-secret: forward the secret so MSAL acquires the token
        # downstream.  Keeps the legacy code path intact for the SPN happy
        # path (env-based CI workflows).
        if config.method == AuthMethod.SERVICE_PRINCIPAL_SECRET:
            return XmlaConnectionOptions(
                tenant_id=config.tenant_id or opts.tenant_id,
                workspace_id=opts.workspace_id,
                dataset_id=opts.dataset_id,
                client_id=config.client_id or opts.client_id,
                client_secret=config.client_secret or opts.client_secret,
                environment=stored_env,
            )

        # INTERACTIVE: refuse to launch the browser in non-interactive
        # environments (CI runners) where no one is there to complete the
        # OAuth dance.  We warn + return opts unchanged so the caller can
        # still fall back to local detection — and so generic runner-level
        # callers don't crash just because the user happens to have stored
        # interactive creds on their dev box.  CLI commands that NEED a
        # service connection (e.g. ``run-tests workspace.model``) surface a
        # dedicated error to the user; see cli.py.
        if config.method == AuthMethod.INTERACTIVE:
            import sys

            in_ci = bool(os.getenv("CI"))
            no_tty = not (hasattr(sys.stdin, "isatty") and sys.stdin.isatty())
            if in_ci or no_tty:
                print(
                    "Warning: stored interactive credentials cannot be used in "
                    "a non-interactive environment (no TTY or CI=true). "
                    "Falling back to local detection. For CI, log in with "
                    "`pql-test auth login` using a service principal or "
                    "managed identity, or supply --tenant-id / --client-id / "
                    "--client-secret flags.",
                    file=sys.stderr,
                )
                return opts

        # All other azure-identity-backed methods (interactive in a TTY,
        # cert, federated, managed identity) — acquire a bearer via the
        # manager and surface it on opts.access_token.
        token = manager.get_access_token()
        if not token:
            return opts
        return XmlaConnectionOptions(
            tenant_id=config.tenant_id or opts.tenant_id,
            workspace_id=opts.workspace_id,
            dataset_id=opts.dataset_id,
            client_id=config.client_id or opts.client_id,
            client_secret=opts.client_secret,
            environment=stored_env,
            access_token=token,
        )

    except ImportError:
        # auth module not available
        return opts
    except Exception as exc:  # noqa: BLE001
        # Surface unexpected errors on stderr so the user can diagnose
        # why their stored credentials aren't being honored.  The bridge
        # still returns opts unchanged so the caller can fall back to
        # other code paths (file-based discovery, local PBI Desktop, etc.).
        # Without this, the run silently fails with the generic "Service
        # connection requires --tenant-id..." error, masking the real
        # cause (corrupt AuthenticationRecord, expired token, MSAL cache
        # access failure, etc.).
        print(
            f"Warning: failed to acquire token from stored credentials: "
            f"{type(exc).__name__}: {str(exc)[:300]}",
            file=sys.stderr,
        )
        return opts


def resolve_xmla_connection(
    model_path: str,
    opts: XmlaConnectionOptions,
) -> Optional[ResolvedXmlaConnection]:
    """
    Resolve which XMLA endpoint to use for test execution.

    Priority:
      1. ``local/<model_name>`` identifier — strict name-based local
         detection.  Never falls back to a remote service connection
         (even if PQL_* credentials are present in the environment) and
         never falls back to an arbitrary running PBI Desktop instance.
         When the named instance isn't open, returns None so the caller
         can surface a clear "instance not found" error instead of
         silently running tests against the deployed dataset.
      2. Remote Power BI Premium / Fabric workspace (when tenant_id,
         workspace_id, dataset_id are all provided), matching Invoke-DQVTesting.
      3. Filesystem path — process-based local detection via
         ``resolve_local_xmla_connection``.

    Returns None when no connection can be established.
    """
    # Try to resolve credentials from stored config if not provided
    opts = _resolve_authentication_with_stored_credentials(opts)

    # Hermetic test mode disables auto-detection paths (stored
    # credentials, local PBI Desktop) so tests don't pick up developer-
    # machine state.  Explicit credentials passed on the command line
    # are still honored — tests that exercise the remote path supply
    # --tenant-id / --workspace-id / --dataset-id directly.
    import os
    hermetic = bool(os.environ.get("PQL_TEST_HERMETIC"))

    # Option 1 — local/<model_name> identifier (strict).
    # Short-circuit before any remote-service path so credentials in the
    # environment can't silently redirect a user's "run against my open
    # PBI Desktop instance" request to the deployed dataset.
    ident = parse_model_identifier(model_path)
    if ident.kind == "local":
        if hermetic:
            return None
        return resolve_local_xmla_connection_by_name(ident.model_name)

    # Option 2 — remote workspace (service principal).
    # If the service path raises (bad creds, dead workspace, unreachable
    # endpoint, etc.) we fall through to local detection instead of letting
    # the exception propagate or returning None silently.  Stale `.env`
    # files would otherwise mask "no connection" when a perfectly good
    # local Power BI Desktop session was sitting right there.
    #
    # The dataset can be identified either by GUID (opts.dataset_id) or by
    # display name (opts.dataset_name).  Name-based resolution lets callers
    # avoid storing dataset GUIDs as secrets — the CLI derives the name
    # from the `.SemanticModel` directory stem and the resolver verifies
    # the dataset exists in the workspace via REST.
    if opts.tenant_id and opts.workspace_id and (opts.dataset_id or opts.dataset_name):
        try:
            return _resolve_service_xmla_connection(opts)
        except Exception as exc:  # noqa: BLE001 — log + fall through to local
            print(
                f"Warning: remote XMLA connection failed ({type(exc).__name__}: "
                f"{exc}). Falling back to local Power BI Desktop detection.",
                file=sys.stderr,
            )
            # Fall through to local detection below.

    # Option 3 — local Power BI Desktop (filesystem path).  Skipped in
    # hermetic test mode so a running PBI Desktop instance on the
    # developer's machine doesn't leak into test subprocess results.
    if hermetic:
        return None
    return resolve_local_xmla_connection(model_path)


def _resolve_service_xmla_connection(
    opts: XmlaConnectionOptions,
) -> ResolvedXmlaConnection:
    """Build a service-XMLA connection from *opts*; raises on any failure.

    Extracted from ``resolve_xmla_connection`` so the caller can wrap the
    whole service path in a single try/except and fall back to local
    detection when something goes wrong.

    The dataset can be identified by either:
      * ``opts.dataset_id`` — GUID.  Both workspace and dataset display
        names are resolved via REST (the legacy ``Invoke-DQVTesting`` flow).
      * ``opts.dataset_name`` — display name.  Only the workspace display
        name is resolved via REST; the dataset name is used directly and
        merely verified to exist in the workspace.  This lets callers stop
        storing dataset GUIDs as secrets.
    """
    endpoints = get_api_endpoints(opts.environment)

    # If a bearer has already been acquired by the auth subsystem (interactive
    # / cert / federated / managed identity flows), use it directly.  Only
    # call MSAL when we genuinely have an SPN-secret triple.
    if opts.access_token:
        token = opts.access_token
    else:
        token = _acquire_service_principal_token(
            opts.tenant_id,
            opts.client_id,
            opts.client_secret,
            login_url=endpoints.login_url,
            resource_url=endpoints.resource_url,
        )

    if opts.dataset_id:
        workspace_name, dataset_name = _resolve_pbi_workspace_and_dataset_names(
            workspace_id=opts.workspace_id,
            dataset_id=opts.dataset_id,
            access_token=token,
            api_prefix=endpoints.api_prefix,
        )
    else:
        workspace_name = _resolve_pbi_workspace_name(
            workspace_id=opts.workspace_id,
            access_token=token,
            api_prefix=endpoints.api_prefix,
        )
        dataset_name = opts.dataset_name
        _verify_dataset_exists_in_workspace(
            workspace_id=opts.workspace_id,
            dataset_name=dataset_name,
            access_token=token,
            api_prefix=endpoints.api_prefix,
        )

    # Derive the XMLA scheme prefix from the REST API prefix.
    # e.g. https://api.powerbi.com → powerbi://api.powerbi.com
    xmla_prefix = endpoints.api_prefix.replace("https://", "powerbi://")
    server = f"{xmla_prefix}/v1.0/myorg/{workspace_name}"
    return ResolvedXmlaConnection(
        server=server,
        catalog=dataset_name,
        tenant_id=opts.tenant_id,
        client_id=opts.client_id,
        client_secret=opts.client_secret,
        access_token=token,
    )


def resolve_service_xmla_connection_by_name(
    workspace_name: str,
    semantic_model_name: str,
    opts: XmlaConnectionOptions,
) -> Optional[ResolvedXmlaConnection]:
    """
    Resolve a remote XMLA connection using workspace and semantic-model
    **display names** directly, skipping the GUID-based REST API resolution.

    This mirrors the Fabric CLI ``fab run <workspace>.<semantic_model>`` flow
    where display names are supplied by the caller instead of GUIDs.

    Authentication is resolved from (in priority order): explicit *opts*
    fields, ``PQL_*`` environment variables, or a stored credential from
    ``pql-test auth login`` (any method — interactive, SPN-secret,
    SPN-cert, federated, or managed identity).  When the stored method is
    non-secret-based, the bearer token is acquired via ``azure-identity``
    and surfaced on ``opts.access_token``; this function passes it through
    to ADOMD via the existing MSOLAP ``Password=<bearer>;`` segment.
    """
    # Resolve credentials from CLI flags / env vars / stored config.
    opts = _resolve_authentication_with_stored_credentials(opts)

    endpoints = get_api_endpoints(opts.environment)

    if opts.access_token:
        # Pre-acquired bearer from a non-secret auth flow (interactive /
        # cert / federated / managed identity).
        token = opts.access_token
    elif opts.tenant_id and opts.client_id and opts.client_secret:
        # Legacy SPN-secret path — acquire via MSAL client-credentials.
        token = _acquire_service_principal_token(
            opts.tenant_id,
            opts.client_id,
            opts.client_secret,
            login_url=endpoints.login_url,
            resource_url=endpoints.resource_url,
        )
    else:
        # No usable credentials.
        return None

    xmla_prefix = endpoints.api_prefix.replace("https://", "powerbi://")
    server = f"{xmla_prefix}/v1.0/myorg/{workspace_name}"
    return ResolvedXmlaConnection(
        server=server,
        catalog=semantic_model_name,
        tenant_id=opts.tenant_id,
        client_id=opts.client_id,
        client_secret=opts.client_secret,
        access_token=token,
    )


def resolve_local_xmla_connection_by_name(
    model_name: str,
) -> Optional[ResolvedXmlaConnection]:
    """
    Resolve a local XMLA connection by matching *model_name* against
    running Power BI Desktop instances (case-insensitive).

    Used by the ``local/<model_name>`` model-identifier format where no
    local filesystem path is available.
    """
    try:
        instances = get_pbi_files_opened()
    except ImportError:
        port = _detect_local_pbi_desktop_port()
        if port:
            return ResolvedXmlaConnection(server=port, catalog="")
        return None

    if not instances:
        port_str = _detect_local_pbi_desktop_port()
        if port_str:
            return ResolvedXmlaConnection(server=port_str, catalog="")
        return None

    needle = model_name.lower()
    for inst in instances:
        # Use a substring (``in``) match against the detected name so this
        # works for both window-title formats: newer builds show just the
        # model name (``OLS_Model``) while older builds appended a suffix
        # (``OLS_Model - Power BI Desktop``).  We keep suffix-stripping in
        # the title parser so the displayed name stays clean, but a fall-
        # back substring check here means callers also resolve correctly
        # if the suffix-strip ever misses an unusual variant.
        if needle and needle in inst.model_name.lower():
            return ResolvedXmlaConnection(
                server=inst.server,
                catalog=inst.catalog,
            )

    # No name match.  The user typed a specific model name via
    # ``local/<name>`` — we MUST honor it strictly.  The previous
    # unnamed-instance fallback (when window-title detection failed) caused
    # silent connections to the wrong model — e.g. ``local/SampleModel``
    # silently connecting to an open RLS_Model and running its tests under
    # SampleModel's name.  See tasks/surface-silent-test-discovery-failures-epic.md.
    #
    # If window-title detection is unreliable on your machine (Microsoft Store
    # packaging, UAC mismatch), open Power BI Desktop from an elevated
    # terminal or use the filesystem-path form instead.
    return None


# ---------------------------------------------------------------------------
# Power BI REST API helpers
# ---------------------------------------------------------------------------


def _resolve_pbi_workspace_and_dataset_names(
    workspace_id: str,
    dataset_id: str,
    access_token: str,
    *,
    api_prefix: str = "https://api.powerbi.com",
) -> tuple[str, str]:
    """
    Resolve the display names for a Power BI workspace (group) and dataset
    from their GUIDs using the Power BI REST API.

    The XMLA endpoint requires display names, not GUIDs:
      powerbi://<api_host>/v1.0/myorg/<WorkspaceName>
      Initial Catalog = <DatasetName>

    Returns (workspace_name, dataset_name).
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    base = f"{api_prefix}/v1.0/myorg"

    def _get(url: str) -> dict:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())

    workspace_data = _get(f"{base}/groups/{workspace_id}")
    workspace_name: str = workspace_data["name"]

    dataset_data = _get(f"{base}/groups/{workspace_id}/datasets/{dataset_id}")
    dataset_name: str = dataset_data["name"]

    return workspace_name, dataset_name


def _resolve_pbi_workspace_name(
    workspace_id: str,
    access_token: str,
    *,
    api_prefix: str = "https://api.powerbi.com",
) -> str:
    """Look up a Power BI workspace's display name from its GUID."""
    req = urllib.request.Request(
        f"{api_prefix}/v1.0/myorg/groups/{workspace_id}",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())["name"]


def _verify_dataset_exists_in_workspace(
    workspace_id: str,
    dataset_name: str,
    access_token: str,
    *,
    api_prefix: str = "https://api.powerbi.com",
) -> None:
    """
    Raise a clear ``ValueError`` if *dataset_name* is not present in the
    workspace's dataset list.  Lets the caller skip storing a GUID secret
    and rely on the deployed dataset's display name (case-insensitive)
    matching the local ``.SemanticModel`` directory stem.
    """
    req = urllib.request.Request(
        f"{api_prefix}/v1.0/myorg/groups/{workspace_id}/datasets",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    with urllib.request.urlopen(req) as resp:
        datasets = json.loads(resp.read().decode()).get("value", [])
    available = [d.get("name") for d in datasets]
    if not any((n or "").lower() == dataset_name.lower() for n in available):
        raise ValueError(
            f"Dataset {dataset_name!r} not found in workspace {workspace_id}. "
            f"Available datasets: {', '.join(repr(n) for n in available) or '<none>'}"
        )


# ---------------------------------------------------------------------------
# MSAL token acquisition (service principal / client-credentials flow)
# ---------------------------------------------------------------------------


def _acquire_service_principal_token(
    tenant_id: str,
    client_id: str,
    client_secret: str,
    *,
    login_url: str = "https://login.microsoftonline.com",
    resource_url: str = "https://analysis.windows.net/powerbi/api",
) -> str:
    """
    Acquire an OAuth2 access token for a service principal via MSAL.

    Uses the client-credentials flow targeting the Power BI / Analysis
    Services scope for the given cloud environment.
    This mirrors the authentication approach used by Invoke-DQVTesting
    for build-agent pipelines that require row-level security evaluation.
    """
    if not HAS_MSAL:
        raise ImportError(
            "msal is required for service principal authentication. "
            "Install with: pip install msal"
        )
    app = msal.ConfidentialClientApplication(
        client_id=client_id,
        client_credential=client_secret,
        authority=f"{login_url}/{tenant_id}",
    )
    result = app.acquire_token_for_client(scopes=[f"{resource_url}/.default"])
    if "access_token" in result:
        return result["access_token"]
    raise RuntimeError(
        "Failed to acquire access token: "
        + result.get("error_description", result.get("error", "Unknown error"))
    )


# ---------------------------------------------------------------------------
# XMLA query execution via pyadomd (ADOMD.NET)
# ---------------------------------------------------------------------------


def _build_connection_string(conn: ResolvedXmlaConnection) -> str:
    """
    Build an ADOMD.NET connection string for the given resolved connection.

    The auth segment and the impersonation segment compose: e.g. a
    service-principal bearer token MUST coexist with ``Roles=`` /
    ``EffectiveUserName=`` so OLS/RLS rules are evaluated against the
    impersonated identity in CI.  Earlier the function returned at the
    first auth branch and silently dropped impersonation, which caused
    ``PQL.Assert.OLS.*`` tests to report ``Actual: VISIBLE (OLS not working)``
    against deployed datasets even when the test functions carried
    ``PQLAssert_RoleName`` / ``PQLAssert_ImpersonatedUserName`` annotations.

    Auth priority (highest to lowest):
      1. Bearer token (access_token) — preferred, acquired via MSAL.
      2. Service principal direct credentials (app:{clientId}@{tenantId}).
      3. Local / integrated auth — no extra parameters.

    Impersonation priority when both are set:
      1. Roles= (named role).  AS applies that role's rules directly.
      2. EffectiveUserName= (AAD UPN).  AS applies whatever roles the
         user is a member of.
    """
    catalog_part = f";Initial Catalog={conn.catalog}" if conn.catalog else ""
    parts: list[str] = [f"Provider=MSOLAP;Data Source={conn.server}{catalog_part};"]

    if conn.access_token:
        parts.append(f"Password={conn.access_token};")
    elif conn.client_id and conn.client_secret and conn.tenant_id:
        parts.append(
            f"User ID=app:{conn.client_id}@{conn.tenant_id};"
            f"Password={conn.client_secret};"
            "Integrated Security=ClaimsToken;"
        )

    if conn.roles:
        parts.append(f"Roles={conn.roles};")
    elif conn.effective_user_name:
        parts.append(f"EffectiveUserName={conn.effective_user_name};")

    return "".join(parts)


def _get_col(row: dict[str, object], key: str) -> str:
    """
    Case-insensitive column lookup for ADOMD.NET result rows.

    DAX/ADOMD.NET may return column names with a table prefix
    (e.g. "Calculations[TestName]") so we match by substring to handle
    both plain column names ("TestName") and bracket notation.
    """
    key_lower = key.lower()
    for k, v in row.items():
        k_lower = k.lower()
        # Exact match or bracket-notation prefix: "testname" or "table[testname]"
        if k_lower == key_lower or k_lower.endswith(f"[{key_lower}]"):
            return str(v) if v is not None else ""
    return ""


def _execute_dax_query(
    conn: ResolvedXmlaConnection,
    dax_query: str,
) -> list[dict[str, object]]:
    """
    Execute a DAX query via ADOMD.NET (pyadomd) and return rows as dicts.

    For service-principal connections an OAuth2 bearer token is acquired
    via MSAL when raw credentials are supplied without a pre-existing token.
    Token-based auth is preferred because it supports row-level security
    evaluation with service principals — the primary use-case for build agents.
    """
    if not HAS_PYADOMD:
        raise ImportError(
            "pyadomd is required for XMLA query execution. "
            "Install with: pip install pyadomd"
        )

    # Acquire bearer token for service principal if credentials supplied
    if (
        conn.client_id
        and conn.client_secret
        and conn.tenant_id
        and not conn.access_token
    ):
        conn.access_token = _acquire_service_principal_token(
            conn.tenant_id, conn.client_id, conn.client_secret
        )

    conn_str = _build_connection_string(conn)

    adomd_conn = _AdomdConnection(conn_str)  # type: ignore[misc]
    adomd_conn.Open()
    try:
        cmd = adomd_conn.CreateCommand()
        cmd.CommandText = dax_query
        reader = cmd.ExecuteReader()
        try:
            field_count = reader.FieldCount
            if field_count == 0:
                return []
            columns = [reader.GetName(i) for i in range(field_count)]
            rows: list[dict[str, object]] = []
            while reader.Read():
                rows.append({col: reader[i] for i, col in enumerate(columns)})
            return rows
        finally:
            reader.Close()
    finally:
        adomd_conn.Close()


# ---------------------------------------------------------------------------
# Public API — discovery
# ---------------------------------------------------------------------------


def _test_matches_environment(test_name: str, environment: str) -> bool:
    """Return True when *test_name* targets *environment* by naming convention.

    Test suites encode their target environment as the second-to-last
    dot-separated segment: ``<Suite>.<ENV>.Tests`` (or ``.Test``), e.g.
    ``Calculations.DEV.Tests``, ``BestPractices.ANY.Tests``,
    ``ColumnTests.BKUP.Test``.  Matching is case-insensitive and exact —
    ``--env DEV`` selects only ``*.DEV.Tests`` suites; ``ANY`` is an ordinary
    environment token, not a wildcard.  Names without an environment segment
    (e.g. ``Calcs.Tests``) never match an environment filter.
    """
    parts = test_name.split(".")
    if len(parts) < 3 or parts[-1].lower() not in ("test", "tests"):
        return False
    return parts[-2].lower() == environment.lower()


def _retrieve_tests_via_dax(
    connection: "ResolvedXmlaConnection",
    environment: Optional[str] = None,
) -> Optional[list["PqlTest"]]:
    """
    Discover test functions from a live model using XMLA.

    Tries ``PQL.Assert.RetrieveTestsV2()`` first (returns Name, Description,
    PQLAssert_ImpersonatedUserName).  Falls back to ``PQL.Assert.RetrieveTests()``
    (returns Name only) when V2 is absent from the model.

    When *environment* is supplied, ``PQL.Assert.RetrieveTestsV2("<env>")``
    is tried first so the model's own UDF does the environment filtering
    server-side.  If that call fails (e.g. the installed V2 takes no
    arguments) discovery falls back to the parameterless queries and the
    environment filter is applied client-side against the
    ``<Suite>.<ENV>.Tests`` naming convention instead.

    Returns a (possibly empty) list of PqlTest objects when either query
    succeeds, or ``None`` when both queries fail (e.g. PQL.Assert is not
    installed in this model, OR an auth/permission/connectivity error
    occurred), signalling the caller to fall back to the file-based scan.

    When both queries fail, emits a one-line stderr warning with the verbatim
    exception so the user can distinguish "PQL.Assert isn't installed in
    this model" (legitimate fallback) from "I don't have access" /
    "authentication failed" (real problem).  See
    tasks/surface-silent-test-discovery-failures-epic.md.
    """
    rows: list[dict] | None = None
    has_v2_columns = False
    server_filtered = False

    if environment:
        env_literal = environment.replace('"', '""')
        try:
            rows = _execute_dax_query(
                connection,
                f'EVALUATE PQL.Assert.RetrieveTestsV2("{env_literal}")',
            )
            has_v2_columns = True
            server_filtered = True
        except Exception:  # noqa: BLE001
            pass

    if rows is None:
        try:
            rows = _execute_dax_query(connection, "EVALUATE PQL.Assert.RetrieveTestsV2()")
            has_v2_columns = True
        except Exception:  # noqa: BLE001
            pass

    if rows is None:
        try:
            rows = _execute_dax_query(connection, "EVALUATE PQL.Assert.RetrieveTests()")
        except Exception as exc:  # noqa: BLE001
            # Both discovery queries failed — surface the verbatim error so
            # the user knows whether it's "PQL.Assert not installed" or a
            # real auth/permissions/connectivity problem.
            target = (
                f"{connection.server} / {connection.catalog}"
                if connection
                else "<unknown>"
            )
            print(
                f"Warning: live test discovery failed against {target}: "
                f"{type(exc).__name__}: {str(exc)[:300]}",
                file=sys.stderr,
            )
            return None  # neither function available — fall back to file scan

    tests: list[PqlTest] = []
    for row in rows or []:
        name = _get_col(row, "Name")
        if not name:
            continue
        description = (_get_col(row, "Description") or None) if has_v2_columns else None
        impersonated_user = (
            (_get_col(row, "PQLAssert_ImpersonatedUserName") or None)
            if has_v2_columns
            else None
        )
        role_name = (
            (_get_col(row, "PQLAssert_RoleName") or None) if has_v2_columns else None
        )
        tests.append(
            PqlTest(
                name=name,
                file_path="",
                source=f"EVALUATE {name}()",
                description=description,
                impersonated_user_name=impersonated_user,
                role_name=role_name,
            )
        )
    if environment and not server_filtered:
        tests = [t for t in tests if _test_matches_environment(t.name, environment)]
    return tests


def retrieve_tests(
    model_path: str,
    connection: Optional["ResolvedXmlaConnection"] = None,
    environment: Optional[str] = None,
) -> list[PqlTest]:
    """
    Retrieve all DAX test suites for a PBIP model.

    When *connection* is supplied the live model is queried first via
    ``PQL.Assert.RetrieveTestsV2()`` (falling back to
    ``PQL.Assert.RetrieveTests()``).  This returns the authoritative set of
    test functions actually registered in the model — including tests defined
    directly in the model's ``functions.tmdl``, not just those in
    ``DAXQueries/``.

    When no connection is available (or both DAX queries fail) the function
    falls back to scanning the SemanticModel's DAXQueries/ folder for
    ``*.Tests.dax`` files.

    Parameters
    ----------
    model_path:
        Root directory of the PBIP model (contains the .pbip file).
    connection:
        Optional live XMLA connection.  Pass to enable live discovery.
    environment:
        Optional environment name (e.g. ``DEV``, ``PROD``, ``ANY``, ``BKUP``).
        When supplied, only suites targeting that environment are returned:
        live discovery passes it to ``PQL.Assert.RetrieveTestsV2("<env>")``,
        and file-scan / fallback paths match the ``<Suite>.<ENV>.Tests``
        naming convention (case-insensitive, exact).

    Returns
    -------
    List of PqlTest descriptors; empty list when none are found.
    """
    if connection is not None:
        live = _retrieve_tests_via_dax(connection, environment=environment)
        if live is not None:  # None means both queries failed
            # When model_path declares ownership-tracking artifacts (a
            # DAXQueries/ folder or a functions.tmdl), the local repo is the
            # source of truth — even an empty ownership set is meaningful (the
            # model declares no tests), so live discovery is filtered strictly.
            # Otherwise an auto-detected local Power BI Desktop instance
            # unrelated to this model would silently leak its tests into the
            # result.  For local/<name>, Fabric workspace.model paths, and bare
            # PBIP skeletons with no declaration location, we pass live
            # discovery through unfiltered.
            if _has_local_ownership_sources(model_path):
                local_names = _discover_local_test_names(model_path)
                # Scope the ownership comparison to the requested environment
                # so suites for other environments don't trigger spurious
                # "missing on server" warnings or leak past the filter.
                if environment:
                    local_names = {
                        n for n in local_names
                        if _test_matches_environment(n, environment)
                    }
                live_names = {t.name for t in live}
                if local_names:
                    extras_on_server = sorted(live_names - local_names)
                    missing_on_server = sorted(local_names - live_names)
                    if extras_on_server:
                        print(
                            "Warning: deployed dataset contains "
                            f"{len(extras_on_server)} test function(s) not declared "
                            f"locally — skipping: {', '.join(extras_on_server)}",
                            file=sys.stderr,
                        )
                    if missing_on_server:
                        print(
                            "Warning: "
                            f"{len(missing_on_server)} local test function(s) "
                            "are not registered in the deployed dataset — "
                            f"deployment may be out of date: "
                            f"{', '.join(missing_on_server)}",
                            file=sys.stderr,
                        )
                elif live_names:
                    print(
                        f"Warning: model at {model_path} declares no tests "
                        f"locally; ignoring {len(live_names)} test function(s) "
                        "found on the auto-detected XMLA connection (likely "
                        "an unrelated Power BI Desktop instance).",
                        file=sys.stderr,
                    )
                return [t for t in live if t.name in local_names]
            return live

    # Offline fallback: scan DAXQueries/ folder for *.Tests.dax files
    semantic_model_dir = _find_semantic_model_dir(model_path)
    if not semantic_model_dir:
        return []
    tests = [
        _parse_dax_test_file(f) for f in _collect_dax_test_files(semantic_model_dir)
    ]
    if environment:
        tests = [t for t in tests if _test_matches_environment(t.name, environment)]
    return tests


def retrieve_test_by_name(
    model_path: str,
    test_name: str,
    connection: Optional["ResolvedXmlaConnection"] = None,
    environment: Optional[str] = None,
) -> Optional[PqlTest]:
    """
    Retrieve a single DAX test suite by name (case-insensitive).

    The name is matched against the function name (e.g. "Calcs.DEV.Tests").
    When *connection* is supplied live discovery is used; otherwise the
    DAXQueries/ folder is scanned.  When *environment* is supplied the name
    must also belong to that environment's suite set.
    """
    for t in retrieve_tests(model_path, connection=connection, environment=environment):
        if t.name.lower() == test_name.lower():
            return t
    return None


# ---------------------------------------------------------------------------
# Public API — execution
# ---------------------------------------------------------------------------

_DEFAULT_SKIP_MESSAGE = (
    "No XMLA connection available. "
    "Open the model in Power BI Desktop or supply "
    "--tenant-id, --workspace-id, and --dataset-id."
)


def run_test(
    test: PqlTest,
    connection: Optional[ResolvedXmlaConnection] = None,
    skip_message: str = _DEFAULT_SKIP_MESSAGE,
) -> list[TestResult]:
    """
    Execute a single DAX test suite via ADOMD.NET / XMLA.

    Returns one TestResult per assertion row in the EVALUATE result set.
    When no connection is available a single failed/skipped result is
    returned so callers can still report the suite without throwing.
    """
    start = time.monotonic()

    if not connection:
        return [
            TestResult(
                test_name=test.name,
                passed=False,
                skipped=True,
                message=skip_message,
                duration_ms=(time.monotonic() - start) * 1000.0,
                suite_name=test.name,
            )
        ]

    # When the test declares RLS/OLS metadata (from RetrieveTestsV2), create
    # a per-test connection that applies the correct impersonation.
    #
    # Roles= is preferred over EffectiveUserName= whenever a role_name is
    # available, regardless of whether the connection is local or service:
    #   • Local AS doesn't accept AAD UPNs for EffectiveUserName.
    #   • Service principals can NEVER use EffectiveUserName= against the
    #     Power BI XMLA endpoint (Microsoft enforces this even for workspace
    #     admins — the resulting error message misleadingly says "not a
    #     workspace administrator").  Roles= works because the SPN can be
    #     granted role membership in the dataset.
    # EffectiveUserName= is still used as a fallback for service connections
    # that only carry an impersonated_user_name annotation — that path
    # requires the calling identity to be a real user that's a workspace
    # admin (i.e. not a service principal).
    effective_connection = connection
    if connection:
        _is_local = connection.server.lower().startswith("localhost:")
        if test.role_name:
            effective_connection = _dc_replace(connection, roles=test.role_name)
        elif not _is_local and test.impersonated_user_name:
            effective_connection = _dc_replace(
                connection, effective_user_name=test.impersonated_user_name
            )

    try:
        rows = _execute_dax_query(effective_connection, test.source)

        if not rows:
            return [
                TestResult(
                    test_name=test.name,
                    passed=False,
                    message=(
                        "Query returned no rows — "
                        "ensure the EVALUATE expression is correct."
                    ),
                    duration_ms=(time.monotonic() - start) * 1000.0,
                    suite_name=test.name,
                )
            ]

        results: list[TestResult] = []
        for row in rows:
            row_test_name = _get_col(row, "TestName") or test.name
            passed_val = _get_col(row, "Passed").lower()
            passed = passed_val in ("true", "1")
            row_expected = _get_col(row, "Expected")
            row_actual = _get_col(row, "Actual")
            rule_desc = _get_col(row, "RuleDescription")

            parts = [f"Expected: {row_expected}", f"Actual: {row_actual}"]
            if rule_desc:
                parts.append(f"Rule: {rule_desc}")

            results.append(
                TestResult(
                    test_name=row_test_name,
                    passed=passed,
                    message=" | ".join(parts),
                    actual=row_actual,
                    expected=row_expected,
                    suite_name=test.name,
                    duration_ms=(time.monotonic() - start) * 1000.0,
                )
            )
        return results

    except Exception as exc:  # noqa: BLE001
        return [
            TestResult(
                test_name=test.name,
                passed=False,
                message="Test execution failed",
                error=str(exc),
                duration_ms=(time.monotonic() - start) * 1000.0,
                suite_name=test.name,
            )
        ]


def run_tests(
    tests: list[PqlTest],
    connection: Optional[ResolvedXmlaConnection] = None,
    skip_message: str = _DEFAULT_SKIP_MESSAGE,
) -> list[TestResult]:
    """Execute all DAX test suites and return the flat list of assertion results."""
    results: list[TestResult] = []
    for t in tests:
        results.extend(run_test(t, connection, skip_message=skip_message))
    return results


def run_tests_from_model(
    model_path: str,
    test_name: Optional[str] = None,
    conn_opts: Optional[XmlaConnectionOptions] = None,
    connection: Optional[ResolvedXmlaConnection] = None,
    skip_message: str = _DEFAULT_SKIP_MESSAGE,
    environment: Optional[str] = None,
) -> TestSuite:
    """
    High-level helper: discover tests, optionally filter, execute, and summarise.

    Parameters
    ----------
    model_path:
        Root directory of the PBIP model.
    test_name:
        Optional. When supplied only that test suite is executed.
    conn_opts:
        XMLA connection options. Defaults to local auto-detection only.
    environment:
        Optional environment name (e.g. ``DEV``, ``PROD``, ``ANY``, ``BKUP``).
        When supplied, only suites targeting that environment are discovered
        and executed (see :func:`retrieve_tests`).

    Returns
    -------
    TestSuite with discovery info and execution results.
    """
    if conn_opts is None:
        conn_opts = XmlaConnectionOptions()

    # Use a pre-resolved connection when supplied (e.g. from local/<name>
    # detection), otherwise resolve from conn_opts as normal.
    if connection is None:
        connection = resolve_xmla_connection(model_path, conn_opts)

    if test_name:
        found = retrieve_test_by_name(
            model_path, test_name, connection=connection, environment=environment
        )
        tests: list[PqlTest] = [found] if found else []
    else:
        tests = retrieve_tests(model_path, connection=connection, environment=environment)
    results = run_tests(tests, connection, skip_message=skip_message)
    passed = sum(1 for r in results if r.passed)
    skipped = sum(1 for r in results if r.skipped)
    failed = sum(1 for r in results if not r.passed and not r.skipped)

    return TestSuite(
        model_path=model_path,
        tests=tests,
        results=results,
        passed=passed,
        failed=failed,
        skipped=skipped,
        total=len(results),
    )
