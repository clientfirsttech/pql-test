"""
ADOMD.NET assembly loading and auto-install.

This module handles discovery, loading, and auto-installation of ADOMD.NET
assemblies required for XMLA connectivity via pythonnet.

Key Features:
- Auto-discovers ADOMD.NET from NuGet, Power BI Desktop, or system paths
- Auto-installs from NuGet if not found (opt-out via environment variable)
- Supports both Microsoft.PowerBI.AdomdClient and Microsoft.AnalysisServices.AdomdClient
- Provides HAS_PYADOMD constant for feature detection

Search Priority:
1. NuGet packages (~/.nuget/packages/) — preferred, actively maintained
2. Power BI Desktop installer (C:\\Program Files\\Microsoft Power BI Desktop\\bin)
3. Standalone ADOMD.NET (C:\\Program Files\\Microsoft.NET\\ADOMD.NET\\*)

Environment Variables:
- PQL_TEST_HERMETIC=1 — Skip all auto-detection (test mode)
- PQL_TEST_NO_AUTO_INSTALL_ADOMD=1 — Skip NuGet auto-install
"""

from __future__ import annotations

import glob
import os
import sys
from typing import Optional

__all__ = [
    "HAS_PYADOMD",
    "_adomd_assemblies_present",
    "_adomd_auto_install_cache_dir",
    "_auto_install_adomd_from_nuget",
    "_discover_adomd_search_dirs",
    "get_adomd_connection_class",
]

# Module-level constants
HAS_PYADOMD = False
_AdomdConnection = None  # set to AdomdConnection class after successful load


def _discover_adomd_search_dirs() -> list[str]:
    """Discover directories that may contain ADOMD.NET assemblies.

    Returns a list of directories in priority order. ORDER MATTERS: pythonnet's
    clr.AddReference resolves by name against whatever's first on sys.path.
    """
    # ORDER MATTERS: pythonnet's clr.AddReference resolves by name against
    # whatever's first on sys.path.  We put NuGet ahead of system-wide
    # Microsoft.NET\\ADOMD.NET paths because GitHub windows-latest runners
    # ship with an old AS client under C:\\Program Files\\Microsoft.NET\\
    # ADOMD.NET\\160 that mishandles bearer-token + Roles= + RLS-filter
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


def _adomd_assemblies_present(search_dirs: list[str]) -> bool:
    """Return True when any search_dirs entry contains an ADOMD.NET DLL.

    We accept either the standalone client (Microsoft.AnalysisServices.
    AdomdClient.dll, NuGet / installer redist) or the Power BI Desktop
    flavour (Microsoft.PowerBI.AdomdClient.dll) — the .NET namespace
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
        "microsoft.analysisservices.adomdclient",
        "19.114.0",
        "lib",
        "net472",
    )


def _auto_install_adomd_from_nuget() -> Optional[str]:
    """Download Microsoft.AnalysisServices.AdomdClient NuGet package.

    Extracts lib/net472/ contents to user cache. Returns the directory
    holding the extracted DLLs on success, or None on any failure.

    This function is intentionally tolerant: callers fall back to the
    standard "ADOMD.NET not loaded" path when it returns None.

    Opt-outs:
    - PQL_TEST_HERMETIC=1 — skip (test mode)
    - PQL_TEST_NO_AUTO_INSTALL_ADOMD=1 — skip (user preference)
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

    pkg = "microsoft.analysisservices.adomdclient"
    version = "19.114.0"
    # NuGet flat-container public endpoint — no auth required.
    nupkg_url = (
        f"https://api.nuget.org/v3-flatcontainer/{pkg}/{version}/{pkg}.{version}.nupkg"
    )

    print(
        f"ADOMD.NET assemblies not detected. Downloading "
        f"{pkg} {version} from nuget.org to {cache_dir} (one-time, ~5 MB)...",
        file=sys.stderr,
    )

    import tempfile
    import urllib.request
    import zipfile

    tmp_path: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".nupkg", delete=False) as f:
            tmp_path = f.name
        urllib.request.urlretrieve(nupkg_url, tmp_path)
        os.makedirs(cache_dir, exist_ok=True)
        member_prefix = "lib/net472/"
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


def get_adomd_connection_class():
    """Return the AdomdConnection class if loaded, None otherwise."""
    return _AdomdConnection


# ---------------------------------------------------------------------------
# Module initialization: Auto-discover and load ADOMD.NET
# ---------------------------------------------------------------------------

_ADOMD_SEARCH_DIRS = _discover_adomd_search_dirs()

# Bootstrap: when none of the discovered directories already carry ADOMD
# assemblies, attempt a one-time fetch into the user-local cache.  No-op
# when assemblies are already present anywhere on the search path.
if not _adomd_assemblies_present(_ADOMD_SEARCH_DIRS):
    _auto_dir = _auto_install_adomd_from_nuget()
    if _auto_dir:
        _ADOMD_SEARCH_DIRS.append(_auto_dir)

# Attempt to load ADOMD.NET via pythonnet
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
