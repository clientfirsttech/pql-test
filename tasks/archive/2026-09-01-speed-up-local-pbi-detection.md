# Speed Up Local Power BI Desktop Detection Epic

**Status**: ✅ COMPLETED (2026-09-01)
**Goal**: Make `local/<model_name>` resolution — especially on a name miss — return in well under a second instead of paying an ADOMD-probe cost per open Power BI Desktop instance.

## Overview

Users typing a wrong or unopened `local/<model_name>` today wait several seconds for a "not found" diagnostic because `get_pbi_files_opened()` opens a real MSOLAP/ADOMD.NET connection and executes `EVALUATE INFO.VIEW.MEASURES()` against **every** running Power BI Desktop instance before the resolver even attempts a name match, and the CLI then re-runs the whole enumeration a second time while formatting the miss diagnostic. The ADOMD probe's return value is discarded (the resulting catalog is always empty on success and the fallback path already returns instances when it fails), and the duplicate enumeration duplicates every probe. Removing the probe from the enumeration path and caching the enumeration for the duration of a single CLI invocation eliminates the biggest chunks of wasted work without changing observable behavior.

---

## Drop ADOMD Connectivity Probe from Local Instance Enumeration

Remove the per-port `_get_catalog_from_local_port` call inside `get_pbi_files_opened` so enumeration no longer opens ADOMD sessions or runs a DAX metadata query per detected instance.

**Requirements**:
- Given N Power BI Desktop instances are running, should call `_get_catalog_from_local_port` zero times during `get_pbi_files_opened()` — the enumeration must never touch pyadomd or the AS engine.
- Given an instance is enumerated, should return `LocalPbiInstance.catalog == ""` so downstream connection strings continue to omit `Initial Catalog` and let Analysis Services auto-select the local database (matches today's success behavior).
- Given pyadomd/pythonnet is unavailable on the machine, should still enumerate every running instance successfully — enumeration must not depend on the .NET runtime.
- Given a caller wants to verify port connectivity, the existing `_get_catalog_from_local_port` function must remain callable directly (not deleted) so future opt-in probes stay possible.

---

## Cache Enumeration Within a Single CLI Invocation

Ensure `resolve_local_xmla_connection_by_name`, the verbose "Detected instances" printout, and `_format_local_miss_diagnostic` share one call to `get_pbi_files_opened()` per CLI invocation instead of enumerating processes/windows/ports two or three times.

**Requirements**:
- Given a single `pql-test run-tests local/<name>` invocation that misses (name not found), should perform process/window/port enumeration exactly once — no code path may trigger a second scan while producing the miss diagnostic.
- Given a `pql-test run-tests local/<name>` invocation with `--verbose` that misses, should still perform enumeration exactly once — verbose output must reuse the cached result.
- Given a fresh CLI invocation (new process), should perform a fresh enumeration — the cache must not persist across processes or leak between tests.
- Given tests patch `pql_test.runner.get_pbi_files_opened`, should observe the patched return value on every call within the invocation — the cache must not defeat existing mocking patterns.

---
