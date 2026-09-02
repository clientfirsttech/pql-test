# Lazy-Load ADOMD.NET at First XMLA Use Epic

**Status**: ✅ COMPLETED (2026-09-01)
**Goal**: Move ADOMD.NET assembly loading out of `pql_test.runner.adomd` module import so commands that never open an XMLA connection (`--help`, `--version`, `check-prereqs`, `retrieve-tests` from filesystem, `run-tests local/<miss>`) don't pay the ~4s pythonnet/CLR startup cost.

## Overview

Every `pql-test` invocation today pays a fixed ~4s cold-start tax because `pql_test/runner/adomd.py` runs `import clr`, `clr.AddReference(...)`, and `from Microsoft.AnalysisServices.AdomdClient import AdomdConnection` at module scope — the .NET runtime spins up and the ADOMD assembly loads even for `pql-test --help`, `pql-test check-prereqs`, or a `local/<name>` miss that never opens a connection. Only `run-tests` against a reachable model and `retrieve-tests` via live XMLA actually need ADOMD.NET, so the whole load should defer until the first `AdomdConnection` request. `check-prereqs` remains eager (its whole job is to verify ADOMD.NET loads), and NuGet auto-install stays bundled with the deferred load path so the first XMLA call still self-heals a machine without ADOMD.

---

## Defer ADOMD.NET Import Until First Access

Replace the module-scope `try: import clr; …; HAS_PYADOMD = True` block with a memoized `_ensure_adomd_loaded()` helper invoked only by `has_pyadomd()` and `get_adomd_connection_class()`.

**Requirements**:
- Given `import pql_test.cli` (or any transitive import of `pql_test.runner`), should not import `clr`, should not call `clr.AddReference`, and should not import anything from `Microsoft.AnalysisServices.AdomdClient` — verified by asserting `"clr"` is not in `sys.modules` after import.
- Given `_ensure_adomd_loaded()` succeeds once, subsequent calls should be no-ops (memoized) so repeated `get_adomd_connection_class()` invocations don't repeat the CLR handshake.
- Given `_ensure_adomd_loaded()` raises during ADOMD discovery (missing assemblies), should cache the failure so subsequent calls return `False` without retrying the expensive filesystem/NuGet probe.
- Given the module still exports a `HAS_PYADOMD` name for backwards compatibility, reading it should trigger the same lazy load — no consumer that today writes `if HAS_PYADOMD:` should silently see `False` after the load completes elsewhere. (Achieved via module `__getattr__` so `from pql_test.runner.adomd import HAS_PYADOMD` still works but the load only fires when the name is bound.)

## Migrate Consumers to the Lazy Accessor

Change every reader of `HAS_PYADOMD` and every caller of `get_adomd_connection_class` inside the package so lazy loading is the load-bearing path, and eager consumers are explicit.

**Requirements**:
- Given `pql-test check-prereqs` is invoked, should call `has_pyadomd()` explicitly so the report reflects the true load state and the user sees the same "ok / not installed" line they see today — `check-prereqs` is the one command that MUST trigger the load.
- Given `pql-test --help`, `pql-test --version`, or any Click argument parsing runs, should complete without triggering ADOMD.NET load (measured: no `clr` in `sys.modules` afterwards).
- Given `pql-test run-tests` against a reachable local or remote model, should still succeed — the lazy load fires from `xmla.py` when the connection is first opened.
- Given `pql-test run-tests local/<name>` misses (no matching instance found), should complete without triggering ADOMD.NET load — the resolver returns `None` before any XMLA connection is attempted.
- Given existing tests import `HAS_PYADOMD` as a `pytest.skip` guard, should keep working unchanged — the module-attribute path stays functional.

## Verify Cold-Start Regression Guard

Add a lightweight test that catches accidental eager ADOMD loads in future refactors.

**Requirements**:
- Given a fresh Python subprocess runs `python -c "import pql_test.cli; assert 'clr' not in sys.modules; assert 'Microsoft.AnalysisServices.AdomdClient' not in sys.modules"`, should exit 0 — this guards against a future import order accidentally reintroducing eager load.
- Given the same subprocess then calls `pql_test.runner.adomd.has_pyadomd()`, should return `True` on machines where ADOMD.NET is present and `False` otherwise, matching today's `HAS_PYADOMD` semantics after load.
- Given the guard test runs on a machine without ADOMD.NET installed, should still pass — assertion is about eager load, not about whether the load ultimately succeeds.

---
