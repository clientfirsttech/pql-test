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

_ADOMD_SEARCH_DIRS = [
    # Power BI Desktop — always present on a developer machine
    r"C:\Program Files\Microsoft Power BI Desktop\bin",
    r"C:\Program Files (x86)\Microsoft Power BI Desktop\bin",
    # Standalone ADOMD.NET client (various versions)
    r"C:\Program Files\Microsoft.NET\ADOMD.NET\160",
    r"C:\Program Files\Microsoft.NET\ADOMD.NET\150",
    r"C:\Program Files\Microsoft.NET\ADOMD.NET\140",
]

try:
    import clr  # type: ignore[import-untyped]  # pythonnet

    for _d in _ADOMD_SEARCH_DIRS:
        if os.path.isdir(_d) and _d not in sys.path:
            sys.path.append(_d)

    # The DLL shipped with PBI Desktop is named Microsoft.PowerBI.AdomdClient.dll
    # and its embedded assembly name is also Microsoft.PowerBI.AdomdClient — that
    # is what clr.AddReference must match.  The .NET *namespace* inside the DLL
    # is still Microsoft.AnalysisServices.AdomdClient, so the from-import stays.
    clr.AddReference("Microsoft.PowerBI.AdomdClient")
    from Microsoft.AnalysisServices.AdomdClient import AdomdConnection as _AdomdConnection  # type: ignore[import]
    HAS_PYADOMD = True
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
    2. Does **not** start with ``./``, ``/``, or ``\\``; contains at least
       one ``.``; the value does not exist on the filesystem → ``kind='service'``,
       split on the **last** dot into *workspace_name* and *model_name*.
    3. Otherwise → ``kind='path'`` (traditional filesystem path).
    """
    # 1. local/<model_name>
    if model_path.startswith("local/") and not Path(model_path).exists():
        name = model_path[len("local/"):]
        return ModelIdentifier(kind="local", model_name=name, raw=model_path)

    # 2. workspace.semanticmodel (Fabric CLI dot notation)
    if (
        not model_path.startswith(("./", "/", "\\"))
        and "." in model_path
        and not Path(model_path).exists()
    ):
        dot_idx = model_path.rfind(".")
        ws = model_path[:dot_idx]
        sm = model_path[dot_idx + 1:]
        if ws and sm:
            return ModelIdentifier(
                kind="service",
                workspace_name=ws,
                model_name=sm,
                raw=model_path,
            )

    # 3. Filesystem path (default)
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

    For remote Power BI Premium / Fabric connections all three of
    tenant_id, workspace_id, and dataset_id are required.

    client_id + client_secret are used to acquire an OAuth2 bearer
    token via the MSAL service-principal (client-credentials) flow.
    This is the same authentication pattern used by Invoke-DQVTesting
    when running in CI/CD pipelines against cloud-hosted models.
    """

    tenant_id: Optional[str] = None
    workspace_id: Optional[str] = None
    dataset_id: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    environment: Environment = Environment.PUBLIC


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
    - A .pbip file (parent directory is used)
    """
    p = Path(model_path)
    if not p.exists():
        return None
    # Passed the .SemanticModel directory directly
    if p.is_dir() and p.name.endswith(".SemanticModel"):
        return str(p)
    # Passed a .pbip file — use its parent
    if p.is_file() and p.suffix == ".pbip":
        p = p.parent
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
    - The .SemanticModel directory (parent is scanned)
    """
    p = Path(model_path)
    if not p.exists():
        return None
    # If given the .SemanticModel dir, look in the parent for the .pbip
    if p.is_dir() and p.name.endswith(".SemanticModel"):
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
    return sorted(
        str(f) for f in dax_dir.iterdir() if f.name.endswith(".Tests.dax")
    )


def _parse_dax_test_file(file_path: str) -> PqlTest:
    """Parse a *.Tests.dax file into a PqlTest descriptor."""
    source = Path(file_path).read_text(encoding="utf-8")
    name = Path(file_path).stem  # basename without .dax extension
    func_match = re.search(r"FUNCTION\s+([\w.]+)\s*=", source, re.IGNORECASE)
    description = f"DAX function: {func_match.group(1)}" if func_match else None
    return PqlTest(name=name, file_path=file_path, source=source, description=description)


# ---------------------------------------------------------------------------
# Local Power BI Desktop detection — process-based (mirrors Invoke-DQVTesting)
# ---------------------------------------------------------------------------

def _get_pbi_process_window_titles() -> dict[int, str]:
    """
    Return {pid: window_title} for all visible Power BI Desktop windows.

    Mirrors the ``GetWindowText`` + ``EnumWindows`` approach used in
    Invoke-DQVTesting's Get-PowerBIFilesOpened to identify which
    PBIDesktop.exe processes are open and their model names.

    Windows only; returns an empty dict on other platforms.
    """
    import ctypes  # noqa: PLC0415

    titles: dict[int, str] = {}
    if not hasattr(ctypes, "windll"):
        return titles

    user32 = ctypes.windll.user32
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def _callback(hwnd: int, _: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length: int = user32.GetWindowTextLengthW(hwnd) + 1
        if length <= 1:
            return True
        buf = ctypes.create_unicode_buffer(length)
        user32.GetWindowTextW(hwnd, buf, length)
        title: str = buf.value
        if "Power BI Desktop" in title:
            pid = ctypes.c_ulong(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value and pid.value not in titles:
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

    # Step 1 — PID → window title mapping
    # This may return an empty dict (e.g. Store app, UAC elevation, hidden
    # window) — we do NOT return early; msmdsrv scanning always continues.
    pid_to_raw_title = _get_pbi_process_window_titles()
    pbi_pid_to_model: dict[int, str] = {}
    for pid, title in pid_to_raw_title.items():
        idx = title.rfind(" - ")
        model_name = title[:idx].strip() if idx > 0 else title
        pbi_pid_to_model[pid] = model_name

    # Step 1b — command-line fallback.
    # When window enumeration returns nothing (UAC elevation mismatch or
    # Microsoft Store isolation), scan PBIDesktop.exe processes and extract
    # the model name from the file-path argument:
    #   PBIDesktop.exe "C:\...\RLS_Model.pbip"  →  "RLS_Model"
    # This is more reliable than EnumWindows in those scenarios because
    # psutil can access the process list even across elevation boundaries.
    if not pbi_pid_to_model:
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
        Path(local_app_data) / "Microsoft" / "Power BI Desktop" / "AnalysisServicesWorkspaces",
    ]
    # Microsoft Store version stores data under the package's LocalState
    _packages_root = Path(local_app_data) / "Packages"
    if _packages_root.exists():
        for _pkg in _packages_root.iterdir():
            if _pkg.name.startswith("Microsoft.MicrosoftPowerBIDesktop"):
                _ws_candidates.append(
                    _pkg / "LocalState" / "Microsoft" / "Power BI Desktop" / "AnalysisServicesWorkspaces"
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
      3. Stored credentials (from pql-test auth login)

    Returns:
        Updated XmlaConnectionOptions with credentials from stored config if needed
        
    Note: Only applies stored credentials when NO credentials are provided at all.
          Partial credentials are left as-is to preserve validation behavior.
    """
    # If any credentials are already provided (even partial), return as-is
    # This preserves the existing validation behavior where partial credentials fail
    if opts.tenant_id or opts.client_id or opts.client_secret:
        return opts

    # Check if credentials are in environment variables
    import os
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

        # For service principal with secret, extract the credentials
        config = manager._store.load()
        if config and config.method == AuthMethod.SERVICE_PRINCIPAL_SECRET:
            return XmlaConnectionOptions(
                tenant_id=config.tenant_id or opts.tenant_id,
                workspace_id=opts.workspace_id,
                dataset_id=opts.dataset_id,
                client_id=config.client_id or opts.client_id,
                client_secret=config.client_secret or opts.client_secret,
                environment=config.environment,
            )

        # For other auth methods, we can't extract credentials
        return opts

    except ImportError:
        # auth module not available
        return opts
    except Exception:
        # Any error in loading stored credentials - return original opts
        return opts


def resolve_xmla_connection(
    model_path: str,
    opts: XmlaConnectionOptions,
) -> Optional[ResolvedXmlaConnection]:
    """
    Resolve which XMLA endpoint to use for test execution.

    Priority:
      1. Remote Power BI Premium / Fabric workspace (when tenant_id,
         workspace_id, dataset_id are all provided), matching Invoke-DQVTesting.
      2. ``local/<model_name>`` identifier — name-based local detection via
         ``resolve_local_xmla_connection_by_name``.  Never falls back to an
         arbitrary running PBI Desktop instance.
      3. Filesystem path — process-based local detection via
         ``resolve_local_xmla_connection``.

    Returns None when no connection can be established.
    """
    # Try to resolve credentials from stored config if not provided
    opts = _resolve_authentication_with_stored_credentials(opts)

    # Option 1 — remote workspace (service principal)
    if opts.tenant_id and opts.workspace_id and opts.dataset_id:
        # The XMLA endpoint requires the workspace display name and dataset
        # display name — not GUIDs.  Resolve both via the Power BI REST API
        # using the service-principal token we're about to acquire anyway.
        endpoints = get_api_endpoints(opts.environment)
        token = _acquire_service_principal_token(
            opts.tenant_id,
            opts.client_id,
            opts.client_secret,
            login_url=endpoints.login_url,
            resource_url=endpoints.resource_url,
        )
        workspace_name, dataset_name = _resolve_pbi_workspace_and_dataset_names(
            workspace_id=opts.workspace_id,
            dataset_id=opts.dataset_id,
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

    # Option 2 — local/<model_name> identifier
    # When model_path uses the local/<model_name> format, use name-based
    # matching so we never fall back to an arbitrary running PBI instance.
    ident = parse_model_identifier(model_path)
    if ident.kind == "local":
        return resolve_local_xmla_connection_by_name(ident.model_name)

    # Option 3 — local Power BI Desktop (filesystem path)
    # Use process-based detection first (mirrors Get-PowerBIFilesOpened), which
    # also resolves the correct catalog GUID via $SYSTEM.DBSCHEMA_CATALOGS.
    return resolve_local_xmla_connection(model_path)


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

    *tenant_id*, *client_id*, and *client_secret* must still be provided
    inside *opts* for service-principal authentication.
    """
    # Try to resolve credentials from stored config if not provided
    opts = _resolve_authentication_with_stored_credentials(opts)

    if not opts.tenant_id or not opts.client_id or not opts.client_secret:
        return None

    endpoints = get_api_endpoints(opts.environment)
    token = _acquire_service_principal_token(
        opts.tenant_id,
        opts.client_id,
        opts.client_secret,
        login_url=endpoints.login_url,
        resource_url=endpoints.resource_url,
    )
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

    for inst in instances:
        if inst.model_name.lower() == model_name.lower():
            return ResolvedXmlaConnection(
                server=inst.server,
                catalog=inst.catalog,
            )

    # No exact name match — if there is exactly one unnamed instance, use it
    unnamed = [i for i in instances if not i.model_name]
    named = [i for i in instances if i.model_name]
    if unnamed and not named and len(instances) == 1:
        return ResolvedXmlaConnection(
            server=instances[0].server,
            catalog=instances[0].catalog,
        )

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
    result = app.acquire_token_for_client(
        scopes=[f"{resource_url}/.default"]
    )
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

    Auth priority:
      1. Bearer token (access_token) — preferred, acquired via MSAL.
      2. Service principal direct credentials (app:{clientId}@{tenantId}).
      3. Local / integrated auth — no extra parameters.
    """
    catalog_part = f";Initial Catalog={conn.catalog}" if conn.catalog else ""
    base = f"Provider=MSOLAP;Data Source={conn.server}{catalog_part};"
    if conn.access_token:
        return base + f"Password={conn.access_token};"
    if conn.client_id and conn.client_secret and conn.tenant_id:
        return (
            base
            + f"User ID=app:{conn.client_id}@{conn.tenant_id};"
            + f"Password={conn.client_secret};"
            + "Integrated Security=ClaimsToken;"
        )
    if conn.roles:
        return base + f"Roles={conn.roles};"
    if conn.effective_user_name:
        return base + f"EffectiveUserName={conn.effective_user_name};"
    return base


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
                rows.append(
                    {col: reader[i] for i, col in enumerate(columns)}
                )
            return rows
        finally:
            reader.Close()
    finally:
        adomd_conn.Close()


# ---------------------------------------------------------------------------
# Public API — discovery
# ---------------------------------------------------------------------------

def _retrieve_tests_via_dax(
    connection: "ResolvedXmlaConnection",
) -> Optional[list["PqlTest"]]:
    """
    Discover test functions from a live model using XMLA.

    Tries ``PQL.Assert.RetrieveTestsV2()`` first (returns Name, Description,
    PQLAssert_ImpersonatedUserName).  Falls back to ``PQL.Assert.RetrieveTests()``
    (returns Name only) when V2 is absent from the model.

    Returns a (possibly empty) list of PqlTest objects when either query
    succeeds, or ``None`` when both queries fail (e.g. PQL.Assert is not
    installed in this model), signalling the caller to fall back to the
    file-based scan.
    """
    rows: list[dict] | None = None
    has_v2_columns = False

    try:
        rows = _execute_dax_query(connection, "EVALUATE PQL.Assert.RetrieveTestsV2()")
        has_v2_columns = True
    except Exception:  # noqa: BLE001
        pass

    if rows is None:
        try:
            rows = _execute_dax_query(connection, "EVALUATE PQL.Assert.RetrieveTests()")
        except Exception:  # noqa: BLE001
            return None  # neither function available — fall back to file scan

    tests: list[PqlTest] = []
    for row in rows or []:
        name = _get_col(row, "Name")
        if not name:
            continue
        description = (_get_col(row, "Description") or None) if has_v2_columns else None
        impersonated_user = (
            _get_col(row, "PQLAssert_ImpersonatedUserName") or None
        ) if has_v2_columns else None
        role_name = (
            _get_col(row, "PQLAssert_RoleName") or None
        ) if has_v2_columns else None
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
    return tests


def retrieve_tests(
    model_path: str,
    connection: Optional["ResolvedXmlaConnection"] = None,
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

    Returns
    -------
    List of PqlTest descriptors; empty list when none are found.
    """
    if connection is not None:
        live = _retrieve_tests_via_dax(connection)
        if live is not None:  # None means both queries failed
            return live

    # Offline fallback: scan DAXQueries/ folder for *.Tests.dax files
    semantic_model_dir = _find_semantic_model_dir(model_path)
    if not semantic_model_dir:
        return []
    return [_parse_dax_test_file(f) for f in _collect_dax_test_files(semantic_model_dir)]


def retrieve_test_by_name(
    model_path: str,
    test_name: str,
    connection: Optional["ResolvedXmlaConnection"] = None,
) -> Optional[PqlTest]:
    """
    Retrieve a single DAX test suite by name (case-insensitive).

    The name is matched against the function name (e.g. "Calcs.DEV.Tests").
    When *connection* is supplied live discovery is used; otherwise the
    DAXQueries/ folder is scanned.
    """
    for t in retrieve_tests(model_path, connection=connection):
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

    # When the test declares RLS metadata (from RetrieveTestsV2), create a
    # per-test connection that applies the correct impersonation:
    #   • Local connections (localhost:…): use Roles=<role_name> — local AS
    #     does not accept AAD UPNs for EffectiveUserName.
    #   • Service connections (XMLA endpoint): use EffectiveUserName=<UPN>.
    effective_connection = connection
    if connection:
        _is_local = connection.server.lower().startswith("localhost:")
        if _is_local and test.role_name:
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

    Returns
    -------
    TestSuite with discovery info and execution results.
    """
    if conn_opts is None:
        conn_opts = XmlaConnectionOptions()

    # Use a pre-resolved connection when supplied (e.g. from --local detection),
    # otherwise resolve from conn_opts as normal.
    if connection is None:
        connection = resolve_xmla_connection(model_path, conn_opts)

    if test_name:
        found = retrieve_test_by_name(model_path, test_name, connection=connection)
        tests: list[PqlTest] = [found] if found else []
    else:
        tests = retrieve_tests(model_path, connection=connection)
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
