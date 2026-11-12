# Fast Local PBI Process Discovery Epic

**Status**: ✅ COMPLETED (2026-11-12)
**Goal**: Find local `msmdsrv.exe` ports and their parent `PBIDesktop.exe` without inspecting every process on the machine.

## Overview

Every `local/<model>` command pays for `get_pbi_files_opened()`, which inspected every process on the machine twice: one `process_iter` pass prefetched `cmdline` (a handle open plus a process-memory read) for every process, and a second pass prefetched `ppid` for every process. Filtering by name in a single `process_iter(["pid", "name"])` pass and reading `cmdline()` / `ppid()` only for the few `PBIDesktop.exe` / `msmdsrv.exe` matches removes that per-machine cost. A Toolhelp32 snapshot was benchmarked (9.1 ms) and rejected in favour of the pure-psutil name-only pass (3.6 ms).

---

## Capture Baseline Benchmark

Record end-to-end and per-phase timings of current discovery on a developer machine.

**Requirements**:
- Given two open PBIP models, should record median `get_pbi_files_opened()` time plus per-phase cost with process count and psutil version — 378 processes, psutil 7.2.2: 54.9 ms / 47.3 ms end-to-end; cmdline pass 18.8 ms, ppid pass 20.2 ms, `net_connections` 0.5 ms, `EnumWindows` 0.5 ms

---

## Single Name-Only Process Pass

Replace the two prefetching passes with one `process_iter(["pid", "name"])` pass that buckets PBIDesktop and msmdsrv processes.

**Requirements**:
- Given N processes on the machine, should call `process_iter` once with only `pid` and `name`, and never call `cmdline()`, `ppid()` or `net_connections()` on unrelated processes
- Given AccessDenied on a PBIDesktop `cmdline()`, should keep its pid so its window title can still name the model
- Given AccessDenied on an msmdsrv `ppid()`, should still report the port as an unnamed instance

---

## Resolve msmdsrv Parents Immediate-First

Map each `msmdsrv.exe` to its `PBIDesktop.exe` using the immediate parent first, then the existing ancestor walk.

**Requirements**:
- Given an `msmdsrv.exe` whose immediate parent is a known PBIDesktop PID, should resolve it without walking further
- Given existing callers of `_find_pbi_ancestor_pid`, should keep its signature and behavior working

---

## Benchmark After and Verify Live Detection

Re-run the baseline benchmark and confirm detection against real open models.

**Requirements**:
- Given the same machine and scenarios as the baseline, should report before/after medians — 54.9 → 3.8 ms and 47.3 → 2.5 ms (order swapped), about 14–19× faster
- Given `RLS_Model` and `SampleModel` open, should return the same model names and ports as before the change and connect via `run-tests local/<model>`
