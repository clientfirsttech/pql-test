# SPDX-License-Identifier: AGPL-3.0-only
"""
Tests that ADOMD.NET loading is deferred until first XMLA use.

See tasks/lazy-load-adomd-epic.md.  These tests spawn a fresh Python
subprocess so `sys.modules` reflects a clean import order, unpolluted by
prior tests in the pytest session that may have already triggered the
lazy load.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap


def _run_in_subprocess(code: str) -> subprocess.CompletedProcess:
    """Run *code* in a clean Python subprocess and return the result."""
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        timeout=30,
    )


class TestAdomdLazyLoad:
    def test_importing_pql_test_cli_does_not_load_clr(self):
        """
        Given `import pql_test.cli` (the CLI entry point that every command
        loads), should not import the pythonnet ``clr`` module — the CLR
        startup + ADOMD.NET assembly load must defer until the first XMLA
        connection request.  See tasks/lazy-load-adomd-epic.md.
        """
        result = _run_in_subprocess(
            """
            import sys
            import pql_test.cli  # noqa: F401
            assert "clr" not in sys.modules, (
                f"clr is loaded after `import pql_test.cli` — ADOMD.NET is "
                f"being loaded eagerly. sys.modules snapshot keys containing "
                f"'clr'/'Adomd': "
                f"{sorted(m for m in sys.modules if 'clr' in m.lower() or 'adomd' in m.lower())}"
            )
            """
        )
        assert result.returncode == 0, (
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )

    def test_importing_pql_test_runner_does_not_load_adomd_assembly(self):
        """
        Given `import pql_test.runner` (used by any programmatic caller of
        the library), should not import anything from the
        ``Microsoft.AnalysisServices.AdomdClient`` namespace.
        """
        result = _run_in_subprocess(
            """
            import sys
            import pql_test.runner  # noqa: F401
            offenders = [
                m for m in sys.modules
                if m.startswith("Microsoft.AnalysisServices.AdomdClient")
                or m == "clr"
            ]
            assert not offenders, f"ADOMD.NET loaded eagerly: {offenders}"
            """
        )
        assert result.returncode == 0, (
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )

    def test_calling_has_pyadomd_triggers_load(self):
        """
        Given `pql_test.runner.adomd.has_pyadomd()` is called explicitly,
        should return a boolean whose truth value matches the actual load
        outcome, and should perform the previously-deferred CLR handshake
        so subsequent XMLA calls have a ready connection class.
        """
        result = _run_in_subprocess(
            """
            import sys
            from pql_test.runner import adomd
            # Before the explicit call, no CLR — this is the whole point of lazy.
            assert "clr" not in sys.modules, "clr loaded before has_pyadomd() call"
            outcome = adomd.has_pyadomd()
            assert isinstance(outcome, bool), f"has_pyadomd() returned {outcome!r}"
            if outcome:
                assert adomd.get_adomd_connection_class() is not None
            """
        )
        assert result.returncode == 0, (
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
