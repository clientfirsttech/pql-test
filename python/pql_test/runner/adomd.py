# SPDX-License-Identifier: AGPL-3.0-only
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
- PQL_DEBUG=1 — Print ADOMD.NET assembly load diagnostics to stderr
- PQL_TEST_HERMETIC=1 — Skip all auto-detection (test mode)
- PQL_TEST_NO_AUTO_INSTALL_ADOMD=1 — Skip NuGet auto-install
"""

from __future__ import annotations

import glob
import os
import shutil
import sys
from typing import Optional

__all__ = [
    "HAS_PYADOMD",
    "_adomd_assemblies_present",
    "_adomd_auto_install_cache_dir",
    "_auto_install_adomd_from_nuget",
    "_discover_adomd_search_dirs",
    "get_adomd_connection_class",
    "has_pyadomd",
]

# Load state.  Both remain False/None until `_ensure_adomd_loaded()` fires
# on first XMLA use — see tasks/archive/2026-09-01-lazy-load-adomd.md.
HAS_PYADOMD = False
_AdomdConnection = None
_load_attempted = False


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


# SHA-512 of microsoft.analysisservices.adomdclient 19.114.0 (the nupkg), matching the
# packageHash in NuGet's catalog entry (checked 2026-10-28). Bump it with the version.
ADOMD_NUPKG_SHA512 = (
    "4f564865082d7007b2590802e680a7ecd5e4991d758c6f589925a4a50b02e758"
    "b3d3730ee0c8606419a297160e7312d37c79cfec8db90287caf0323e7c47a7fd"
)


# Written into the cache after a verified install: the SHA-512 the package was checked against.
_MARKER = ".pql-test-verified"


def _read_marker(cache_dir: str) -> Optional[str]:
    try:
        with open(os.path.join(cache_dir, _MARKER), encoding="ascii") as f:
            return f.read().strip()
    except OSError:
        return None


def _auto_install_adomd_from_nuget() -> Optional[str]:
    """Download Microsoft.AnalysisServices.AdomdClient NuGet package.

    Extracts lib/net472/ contents to user cache. Returns the directory
    holding the extracted DLLs on success, or None on any failure.

    This function is intentionally tolerant: callers fall back to the
    standard "ADOMD.NET not loaded" path when it returns None.

    Opt-outs:
    - not Windows — skip (the net472 assemblies only load on Windows)
    - PQL_TEST_HERMETIC=1 — skip (test mode)
    - PQL_TEST_NO_AUTO_INSTALL_ADOMD=1 — skip (user preference)
    """
    if sys.platform != "win32":
        return None
    if os.environ.get("PQL_TEST_HERMETIC") or os.environ.get(
        "PQL_TEST_NO_AUTO_INSTALL_ADOMD"
    ):
        return None

    cache_dir = _adomd_auto_install_cache_dir()
    if cache_dir is None:
        return None

    # Already installed and verified by a prior run — fast path. A cache without the
    # marker (an older, unverified install, or one cut short) is replaced below.
    if _read_marker(cache_dir) == ADOMD_NUPKG_SHA512:
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

    import hashlib
    import tempfile
    import urllib.request
    import zipfile

    tmp_path: Optional[str] = None
    staging: Optional[str] = None
    try:
        # A fixed https URL; the package is verified against a pinned hash before use.
        with urllib.request.urlopen(nupkg_url, timeout=120) as response:  # nosec B310
            package = response.read()
        digest = hashlib.sha512(package).hexdigest()
        if digest != ADOMD_NUPKG_SHA512:
            raise RuntimeError(
                f"{pkg} {version} from nuget.org does not match its pinned SHA-512 "
                f"(got {digest[:16]}…); refusing to load it"
            )
        with tempfile.NamedTemporaryFile(suffix=".nupkg", delete=False) as f:
            tmp_path = f.name
            f.write(package)
        # Extract into a fresh folder next to the cache, and swap it in only when complete.
        parent = os.path.dirname(os.path.abspath(cache_dir))
        os.makedirs(parent, exist_ok=True)
        staging = tempfile.mkdtemp(prefix=".adomd-", dir=parent)
        root = os.path.realpath(staging)
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
                dest = os.path.realpath(os.path.join(staging, *rel.split("/")))
                if os.path.commonpath([root, dest]) != root:
                    # Zip slip: a member like lib/net472/../../x.dll would land outside the cache.
                    raise RuntimeError(f"{pkg} contains a path outside its folder: {member}")
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with z.open(member) as src, open(dest, "wb") as out:
                    out.write(src.read())
        with open(os.path.join(staging, _MARKER), "w", encoding="ascii") as marker:
            marker.write(ADOMD_NUPKG_SHA512)
        if os.path.isdir(cache_dir):
            shutil.rmtree(cache_dir)
        os.replace(staging, cache_dir)
        staging = None
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
        if staging and os.path.isdir(staging):
            shutil.rmtree(staging, ignore_errors=True)
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def get_adomd_connection_class():
    """Return the AdomdConnection class, loading ADOMD.NET on first call."""
    _ensure_adomd_loaded()
    return _AdomdConnection


def has_pyadomd() -> bool:
    """Return True iff ADOMD.NET is loadable.  Triggers the lazy load."""
    _ensure_adomd_loaded()
    return HAS_PYADOMD


# ---------------------------------------------------------------------------
# Lazy ADOMD.NET load — deferred until has_pyadomd() or
# get_adomd_connection_class() is first called so `pql-test --help`,
# `check-prereqs`, and `local/<name>` misses don't pay the CLR startup
# cost.  See tasks/lazy-load-adomd-epic.md.
# ---------------------------------------------------------------------------

def _ensure_adomd_loaded() -> None:
    """Discover, auto-install (if needed), and load ADOMD.NET exactly once."""
    global HAS_PYADOMD, _AdomdConnection, _load_attempted
    if _load_attempted:
        return
    _load_attempted = True

    search_dirs = _discover_adomd_search_dirs()
    if not _adomd_assemblies_present(search_dirs):
        auto_dir = _auto_install_adomd_from_nuget()
        if auto_dir:
            search_dirs.append(auto_dir)

    try:
        import clr  # type: ignore[import-untyped]  # pythonnet

        for _d in search_dirs:
            if os.path.isdir(_d) and _d not in sys.path:
                sys.path.append(_d)

        # PBI Desktop ships Microsoft.PowerBI.AdomdClient.dll; the NuGet package
        # and standalone ADOMD.NET ship Microsoft.AnalysisServices.AdomdClient.dll.
        # The embedded .NET namespace is Microsoft.AnalysisServices.AdomdClient in
        # both, so the from-import stays the same — only the assembly name differs.
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
            AdomdConnection as _AdomdConnectionClass,
        )  # type: ignore[import]
        _AdomdConnection = _AdomdConnectionClass
        HAS_PYADOMD = True

        if os.environ.get("PQL_DEBUG") == "1":
            try:
                from System.Reflection import (
                    Assembly as _Assembly,  # type: ignore[import]
                )

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


def __getattr__(name: str):
    """Module-level lazy resolver.

    Preserves the historical ``from pql_test.runner.adomd import HAS_PYADOMD``
    call pattern: the load fires only when the name is actually bound by a
    consumer, not at module import time.
    """
    if name == "HAS_PYADOMD":
        _ensure_adomd_loaded()
        return HAS_PYADOMD
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
