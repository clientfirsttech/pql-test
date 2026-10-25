# SPDX-License-Identifier: BUSL-1.1
"""
Local Power BI Desktop detection and connection resolution.

This module provides functions to discover Power BI Desktop instances
running on the local machine using:
1. Process enumeration (psutil) - Preferred, most reliable
2. Port file detection - Fallback when psutil unavailable

Mirrors Invoke-DQVTesting's Get-PowerBIFilesOpened cmdlet and -Local switch.
"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from pql_test.runner.adomd import get_adomd_connection_class, has_pyadomd
from pql_test.runner.model_path import _find_pbip_file
from pql_test.runner.models import LocalPbiInstance, ResolvedXmlaConnection

if TYPE_CHECKING:
    from pql_test import runner
else:
    # Import at runtime through the runner package so tests can patch
    # ``pql_test.runner.<helper>`` and have the patch observed by the
    # helpers defined in this module (get_pbi_files_opened,
    # resolve_local_xmla_connection, etc.).
    from pql_test import runner

__all__ = [
    "_detect_local_pbi_desktop_port",
    "_find_pbi_ancestor_pid",
    "_get_catalog_from_local_port",
    "_get_pbi_process_window_titles",
    "get_pbi_files_opened",
    "resolve_local_xmla_connection",
]

# Legacy window-title suffix appended by some Power BI Desktop builds.
# Newer/Store builds omit this suffix entirely, so it must only be
# stripped when present as a literal trailing match — never via a blind
# rfind(" - "), which would truncate model names that themselves contain
# " - " (e.g. "Component 4 - Daily Results Dashboard").
_PBI_DESKTOP_TITLE_SUFFIX = " - Power BI Desktop"

# Runtime import handling for optional dependencies
HAS_PSUTIL = False
_psutil = None
try:
    import psutil as _psutil  # type: ignore[import-untyped]

    HAS_PSUTIL = True
except ImportError:
    pass


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
    if not has_pyadomd():
        return None

    _AdomdConnection = get_adomd_connection_class()
    if _AdomdConnection is None:
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
    proc: _psutil.Process,  # type: ignore[name-defined]
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
    if not HAS_PSUTIL or _psutil is None:
        return None
    
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
    # Read HAS_PSUTIL / _psutil through the runner package so tests that toggle
    # ``pql_test.runner.HAS_PSUTIL`` (e.g. the psutil-unavailable case) see the
    # updated value.  Fall back to the module-local values for callers that
    # invoke this function before ``pql_test.runner`` has finished importing.
    has_psutil = getattr(runner, "HAS_PSUTIL", HAS_PSUTIL)
    psutil_mod = getattr(runner, "_psutil", _psutil)
    if not has_psutil or psutil_mod is None:
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
    for _fp in psutil_mod.process_iter(["pid", "name", "cmdline"]):
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
        except (psutil_mod.NoSuchProcess, psutil_mod.AccessDenied):
            continue
    pbi_pids = set(pbi_pid_to_model.keys())

    # Step 1b — PID → window title mapping.  Pass the known PBI pids so
    # newer-build windows (just the model name, no app suffix) are also
    # captured.  Title trumps cmdline because the title reflects the
    # currently-loaded model after Save As / rename, whereas the cmdline
    # is frozen at process start.  A title-derived name only OVERWRITES
    # the cmdline name when it's non-empty after suffix-stripping.
    pid_to_raw_title = runner._get_pbi_process_window_titles(known_pbi_pids=pbi_pids)
    for pid, title in pid_to_raw_title.items():
        # Only strip the legacy " - Power BI Desktop" app-name suffix when
        # the title actually ends with it.  Using rfind(" - ") unconditionally
        # would truncate model names that themselves contain " - " (e.g.
        # "Component 4 - Daily Results Dashboard") on newer builds whose
        # window title is just the model name with no app-name suffix.
        if title.endswith(_PBI_DESKTOP_TITLE_SUFFIX):
            model_name = title[: -len(_PBI_DESKTOP_TITLE_SUFFIX)].strip()
        else:
            model_name = title.strip()
        if model_name:
            pbi_pid_to_model[pid] = model_name
            pbi_pids.add(pid)

    # Portable LISTEN status — psutil < 6 exposed CONN_LISTEN; psutil 6+ uses
    # the plain string "LISTEN".  Accept both so the code works on any version.
    _listen_status: object = getattr(psutil_mod, "CONN_LISTEN", "LISTEN")

    # Pre-build a pid → listen_port map using the global net_connections call.
    # This is more reliable on Windows than per-process net_connections() because
    # it queries GetExtendedTcpTable once for all connections and doesn't require
    # per-process handle access.  Falls back to per-process inspection if the
    # global call raises an exception (e.g. on some test environments).
    _global_listen_ports: dict[int, int] = {}
    try:
        for _c in psutil_mod.net_connections(kind="tcp"):
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
    for proc in psutil_mod.process_iter(["pid", "name", "ppid"]):
        try:
            pname = (proc.info.get("name") or "").lower()
            if pname != "msmdsrv.exe":
                continue

            msmdsrv_pid: int = proc.info.get("pid") or 0

            # Try immediate parent first (fast path), then walk the tree.
            parent_pid: int = proc.info.get("ppid") or 0
            model_name = pbi_pid_to_model.get(parent_pid, "")
            if not model_name and pbi_pids:
                ancestor = runner._find_pbi_ancestor_pid(proc, pbi_pids)
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
                # Skip the ADOMD/DAX connectivity probe here — the caller
                # opens a real connection later and any bad port will fail
                # loudly there. Local AS auto-selects the single database,
                # so catalog is unconditionally empty.
                instances.append(
                    LocalPbiInstance(
                        model_name=model_name,
                        server=f"localhost:{port}",
                        catalog="",
                    )
                )
        except (psutil_mod.NoSuchProcess, psutil_mod.AccessDenied):
            continue

    return instances


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
    pbip = runner._find_pbip_file(model_path)
    model_name = Path(pbip).stem if pbip else None

    # Fallback: derive model name from the .SemanticModel directory stem
    if model_name is None:
        p = Path(model_path)
        if p.is_dir() and p.name.endswith(".SemanticModel"):
            model_name = p.name[: -len(".SemanticModel")]

    try:
        instances = runner.get_pbi_files_opened()
    except ImportError:
        # psutil not installed — fall back to port-file approach
        port = runner._detect_local_pbi_desktop_port()
        if port:
            return ResolvedXmlaConnection(server=port, catalog="")
        return None

    if not instances:
        # No running PBI Desktop found via process detection; try port-file
        port_str = runner._detect_local_pbi_desktop_port()
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
