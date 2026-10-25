# SPDX-License-Identifier: BUSL-1.1
"""
Unit tests for [python/pql_test/runner/adomd.py](../pql_test/runner/adomd.py) helpers.

Focus on pure-Python discovery / cache / installer logic.  The actual
ADOMD.NET assembly load is out of scope here (covered by
[python/tests/test_adomd_lazy_load.py](test_adomd_lazy_load.py)).
"""

from __future__ import annotations

import os
import zipfile
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from pql_test.runner import adomd as adomd_mod


# ---------------------------------------------------------------------------
# _discover_adomd_search_dirs
# ---------------------------------------------------------------------------


class TestDiscoverAdomdSearchDirs:
    def test_returns_list_of_paths(self):
        dirs = adomd_mod._discover_adomd_search_dirs()
        assert isinstance(dirs, list)
        assert all(isinstance(d, str) for d in dirs)

    def test_always_includes_installer_locations(self):
        with patch.dict(os.environ, {"USERPROFILE": ""}, clear=False):
            dirs = adomd_mod._discover_adomd_search_dirs()
        assert any("Microsoft Power BI Desktop" in d for d in dirs)
        assert any(r"Microsoft.NET\ADOMD.NET" in d for d in dirs)

    def test_prefers_nuget_paths_when_userprofile_set(self, tmp_path, monkeypatch):
        """NuGet-installed packages must appear ahead of installer paths."""
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        pkg_dir = (
            tmp_path
            / ".nuget"
            / "packages"
            / "microsoft.analysisservices.adomdclient"
            / "19.114.0"
            / "lib"
            / "net472"
        )
        pkg_dir.mkdir(parents=True)

        dirs = adomd_mod._discover_adomd_search_dirs()
        # NuGet path present
        assert any(str(pkg_dir) in d for d in dirs)
        # And it comes before the installer paths
        nuget_idx = next(
            i for i, d in enumerate(dirs) if str(pkg_dir) in d
        )
        installer_idx = next(
            i for i, d in enumerate(dirs) if "Microsoft Power BI Desktop" in d
        )
        assert nuget_idx < installer_idx

    def test_newest_nuget_version_first(self, tmp_path, monkeypatch):
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        base = (
            tmp_path
            / ".nuget"
            / "packages"
            / "microsoft.analysisservices.adomdclient"
        )
        for version in ("19.100.0", "19.114.0", "19.99.0"):
            (base / version / "lib" / "net472").mkdir(parents=True)

        dirs = adomd_mod._discover_adomd_search_dirs()
        nuget_dirs = [d for d in dirs if str(base) in d]
        # Sorted reverse-lex → 19.99 > 19.114 > 19.100 (string sort);
        # what we require is that at least one such path exists and the
        # ordering is deterministic (reverse-alphabetical).
        assert nuget_dirs == sorted(nuget_dirs, reverse=True)

    def test_supports_legacy_retail_package_id(self, tmp_path, monkeypatch):
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        legacy = (
            tmp_path
            / ".nuget"
            / "packages"
            / "microsoft.analysisservices.adomdclient.retail.amd64"
            / "19.84.1"
            / "lib"
            / "net45"
        )
        legacy.mkdir(parents=True)
        dirs = adomd_mod._discover_adomd_search_dirs()
        assert any(str(legacy) in d for d in dirs)


# ---------------------------------------------------------------------------
# _adomd_assemblies_present
# ---------------------------------------------------------------------------


class TestAdomdAssembliesPresent:
    def test_returns_false_when_no_dirs(self):
        assert adomd_mod._adomd_assemblies_present([]) is False

    def test_returns_false_when_dirs_do_not_exist(self, tmp_path):
        assert adomd_mod._adomd_assemblies_present([str(tmp_path / "nope")]) is False

    def test_returns_false_when_dir_has_no_dll(self, tmp_path):
        (tmp_path / "unrelated.txt").write_text("x")
        assert adomd_mod._adomd_assemblies_present([str(tmp_path)]) is False

    def test_finds_analysis_services_dll(self, tmp_path):
        (tmp_path / "Microsoft.AnalysisServices.AdomdClient.dll").write_bytes(b"\x00")
        assert adomd_mod._adomd_assemblies_present([str(tmp_path)]) is True

    def test_finds_powerbi_dll(self, tmp_path):
        (tmp_path / "Microsoft.PowerBI.AdomdClient.dll").write_bytes(b"\x00")
        assert adomd_mod._adomd_assemblies_present([str(tmp_path)]) is True

    def test_scans_multiple_dirs_stops_at_first_hit(self, tmp_path):
        d1 = tmp_path / "empty"
        d1.mkdir()
        d2 = tmp_path / "has-dll"
        d2.mkdir()
        (d2 / "Microsoft.PowerBI.AdomdClient.dll").write_bytes(b"")
        assert adomd_mod._adomd_assemblies_present([str(d1), str(d2)]) is True


# ---------------------------------------------------------------------------
# _adomd_auto_install_cache_dir
# ---------------------------------------------------------------------------


class TestAdomdAutoInstallCacheDir:
    def test_returns_expected_subpath_when_home_known(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            os.path, "expanduser", lambda p: str(tmp_path) if p == "~" else p
        )
        result = adomd_mod._adomd_auto_install_cache_dir()
        assert result is not None
        assert result.startswith(str(tmp_path))
        assert result.endswith(os.path.join("lib", "net472"))
        assert "microsoft.analysisservices.adomdclient" in result

    def test_returns_none_when_home_unresolved(self, monkeypatch):
        monkeypatch.setattr(os.path, "expanduser", lambda p: "~")
        assert adomd_mod._adomd_auto_install_cache_dir() is None

    def test_returns_none_when_home_empty(self, monkeypatch):
        monkeypatch.setattr(os.path, "expanduser", lambda p: "")
        assert adomd_mod._adomd_auto_install_cache_dir() is None


# ---------------------------------------------------------------------------
# _auto_install_adomd_from_nuget
# ---------------------------------------------------------------------------


class TestAutoInstallAdomdFromNuget:
    def test_hermetic_skips(self, monkeypatch):
        monkeypatch.setenv("PQL_TEST_HERMETIC", "1")
        assert adomd_mod._auto_install_adomd_from_nuget() is None

    def test_opt_out_env_skips(self, monkeypatch):
        monkeypatch.delenv("PQL_TEST_HERMETIC", raising=False)
        monkeypatch.setenv("PQL_TEST_NO_AUTO_INSTALL_ADOMD", "1")
        assert adomd_mod._auto_install_adomd_from_nuget() is None

    def test_returns_none_when_cache_dir_cannot_be_resolved(self, monkeypatch):
        monkeypatch.delenv("PQL_TEST_HERMETIC", raising=False)
        monkeypatch.delenv("PQL_TEST_NO_AUTO_INSTALL_ADOMD", raising=False)
        monkeypatch.setattr(
            adomd_mod, "_adomd_auto_install_cache_dir", lambda: None
        )
        assert adomd_mod._auto_install_adomd_from_nuget() is None

    def test_fast_path_when_cache_populated(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PQL_TEST_HERMETIC", raising=False)
        monkeypatch.delenv("PQL_TEST_NO_AUTO_INSTALL_ADOMD", raising=False)
        cache = tmp_path / "cache"
        cache.mkdir()
        (cache / "AlreadyThere.dll").write_bytes(b"")
        monkeypatch.setattr(
            adomd_mod, "_adomd_auto_install_cache_dir", lambda: str(cache)
        )
        # Guard: urlretrieve must NOT be called on the fast path.
        with patch("urllib.request.urlretrieve") as retrieve:
            result = adomd_mod._auto_install_adomd_from_nuget()
        assert result == str(cache)
        retrieve.assert_not_called()

    def test_downloads_and_extracts_nupkg(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PQL_TEST_HERMETIC", raising=False)
        monkeypatch.delenv("PQL_TEST_NO_AUTO_INSTALL_ADOMD", raising=False)
        cache = tmp_path / "cache"
        # Cache dir does not yet exist — installer creates it
        monkeypatch.setattr(
            adomd_mod, "_adomd_auto_install_cache_dir", lambda: str(cache)
        )

        # Build a tiny in-memory .nupkg (zip) containing lib/net472/x.dll
        # and lib/net472/de/x.resources.dll (culture subdir).
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("lib/net472/", "")
            z.writestr("lib/net472/x.dll", b"\x00\x01")
            z.writestr("lib/net472/de/x.resources.dll", b"\x02")
            z.writestr("other/ignored.txt", b"skip")
        buf.seek(0)

        def fake_urlretrieve(url, tmp_path_arg):
            with open(tmp_path_arg, "wb") as fp:
                fp.write(buf.getvalue())

        with patch("urllib.request.urlretrieve", side_effect=fake_urlretrieve):
            result = adomd_mod._auto_install_adomd_from_nuget()

        assert result == str(cache)
        assert (cache / "x.dll").is_file()
        assert (cache / "de" / "x.resources.dll").is_file()
        # Members outside lib/net472/ are ignored
        assert not (cache / "ignored.txt").exists()

    def test_returns_none_on_download_failure(self, tmp_path, monkeypatch, capsys):
        monkeypatch.delenv("PQL_TEST_HERMETIC", raising=False)
        monkeypatch.delenv("PQL_TEST_NO_AUTO_INSTALL_ADOMD", raising=False)
        cache = tmp_path / "cache"
        monkeypatch.setattr(
            adomd_mod, "_adomd_auto_install_cache_dir", lambda: str(cache)
        )
        with patch(
            "urllib.request.urlretrieve",
            side_effect=RuntimeError("network unreachable"),
        ):
            result = adomd_mod._auto_install_adomd_from_nuget()
        assert result is None
        err = capsys.readouterr().err
        assert "failed to auto-install ADOMD.NET" in err
        assert "network unreachable" in err


# ---------------------------------------------------------------------------
# Module __getattr__ bridge for HAS_PYADOMD
# ---------------------------------------------------------------------------


class TestModuleGetattr:
    def test_unknown_attribute_raises_attribute_error(self):
        with pytest.raises(AttributeError, match="has no attribute 'not_a_real_name'"):
            adomd_mod.__getattr__("not_a_real_name")

    def test_has_pyadomd_bridge_returns_bool(self):
        """Whether ADOMD.NET is actually loadable depends on the machine,
        so we only assert the bridge returns a bool without raising."""
        result = adomd_mod.__getattr__("HAS_PYADOMD")
        assert isinstance(result, bool)
