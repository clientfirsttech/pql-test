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
from dataclasses import dataclass
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


def get_pbi_files_opened() -> list[LocalPbiInstance]:
    """
    Discover all Power BI Desktop instances open on this machine.

    Mirrors Invoke-DQVTesting's ``Get-PowerBIFilesOpened``:

    1. Enumerate visible windows via ``EnumWindows`` + ``GetWindowText`` to
       find PBIDesktop.exe PIDs and model names (window title minus the
       " - Power BI Desktop" suffix).
    2. Find ``msmdsrv.exe`` processes and their LISTEN TCP ports using psutil
       (equivalent to ``Get-NetTCPConnection`` / ``Get-CimInstance Win32_Process``).
    3. Map each msmdsrv process to its parent PBIDesktop process via PPID.
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
    pid_to_raw_title = _get_pbi_process_window_titles()
    pbi_pid_to_model: dict[int, str] = {}
    for pid, title in pid_to_raw_title.items():
        idx = title.rfind(" - ")
        model_name = title[:idx].strip() if idx > 0 else title
        pbi_pid_to_model[pid] = model_name

    if not pbi_pid_to_model:
        return []

    # Step 2 & 3 — msmdsrv ports mapped back to parent PBIDesktop via PPID
    instances: list[LocalPbiInstance] = []
    for proc in _psutil.process_iter(["pid", "name", "ppid"]):
        try:
            pname = (proc.info.get("name") or "").lower()
            if pname != "msmdsrv.exe":
                continue
            parent_pid: int = proc.info.get("ppid") or 0
            model_name = pbi_pid_to_model.get(parent_pid, "")

            for conn in proc.net_connections(kind="tcp"):
                if (
                    getattr(conn, "status", None) == _psutil.CONN_LISTEN
                    and conn.laddr
                    and conn.laddr.ip in ("0.0.0.0", "::", "127.0.0.1")
                ):
                    port = conn.laddr.port
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
                    break
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
        # No name match — warn but do not guess a random model
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
    ws_base = (
        Path(local_app_data)
        / "Microsoft"
        / "Power BI Desktop"
        / "AnalysisServicesWorkspaces"
    )
    if not ws_base.exists():
        return None
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

def resolve_xmla_connection(
    model_path: str,
    opts: XmlaConnectionOptions,
) -> Optional[ResolvedXmlaConnection]:
    """
    Resolve which XMLA endpoint to use for test execution.

    Priority:
      1. Remote Power BI Premium / Fabric workspace (when tenant_id,
         workspace_id, dataset_id are all provided), matching Invoke-DQVTesting.
      2. Local Power BI Desktop instance (auto-detected via port file).

    Returns None when no connection can be established.
    """
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

    # Option 2 — local Power BI Desktop
    # Use process-based detection first (mirrors Get-PowerBIFilesOpened), which
    # also resolves the correct catalog GUID via $SYSTEM.DBSCHEMA_CATALOGS.
    return resolve_local_xmla_connection(model_path)


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

def retrieve_tests(model_path: str) -> list[PqlTest]:
    """
    Retrieve all DAX test suites from a PBIP model directory.

    Scans the SemanticModel's DAXQueries/ folder for *.Tests.dax files
    and returns a descriptor for each.

    Parameters
    ----------
    model_path:
        Root directory of the PBIP model (contains the .pbip file).

    Returns
    -------
    List of PqlTest descriptors; empty list when none are found.
    """
    semantic_model_dir = _find_semantic_model_dir(model_path)
    if not semantic_model_dir:
        return []
    return [_parse_dax_test_file(f) for f in _collect_dax_test_files(semantic_model_dir)]


def retrieve_test_by_name(model_path: str, test_name: str) -> Optional[PqlTest]:
    """
    Retrieve a single DAX test suite by name (case-insensitive).

    The name is matched against the file stem without .dax extension,
    e.g. "Calculations.DEV.Tests".
    """
    for t in retrieve_tests(model_path):
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
            )
        ]

    try:
        rows = _execute_dax_query(connection, test.source)

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
                )
            ]

        results: list[TestResult] = []
        for row in rows:
            row_test_name = _get_col(row, "TestName") or test.name
            passed_val = _get_col(row, "Passed").lower()
            passed = passed_val in ("true", "1")
            expected = _get_col(row, "Expected")
            actual = _get_col(row, "Actual")
            rule_desc = _get_col(row, "RuleDescription")

            parts = [f"Expected: {expected}", f"Actual: {actual}"]
            if rule_desc:
                parts.append(f"Rule: {rule_desc}")

            results.append(
                TestResult(
                    test_name=row_test_name,
                    passed=passed,
                    message=" | ".join(parts),
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

    if test_name:
        found = retrieve_test_by_name(model_path, test_name)
        tests: list[PqlTest] = [found] if found else []
    else:
        tests = retrieve_tests(model_path)

    # Use a pre-resolved connection when supplied (e.g. from --local detection),
    # otherwise resolve from conn_opts as normal.
    if connection is None:
        connection = resolve_xmla_connection(model_path, conn_opts)
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
