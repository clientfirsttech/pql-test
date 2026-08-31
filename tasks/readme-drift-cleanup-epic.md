# README Drift Cleanup Epic

**Status**: 🚧 IN PROGRESS (2026-05-26)
**Goal**: Close every gap between what `README.md` documents and what the CLI actually does, so users running through the docs do not hit silent surprises (especially around auto-detection, exit codes, and `.env` file placement).

## Overview

A README audit found four drift items:

1. `retrieve-tests <path>` does not auto-detect a locally open Power BI Desktop instance, while `run-tests <path>` does — the README §"Connection Options" treats both commands as equivalent.
2. The §"Exit Codes" table predates the `fail-cli-when-no-tests-executed-epic` work and does not mention that exit 1 now also fires when every discovered test was skipped (CI misconfig guard).
3. README line 896 directs CI / local-dev users to place credentials in `python/tests/.env`, but the CLI loads `.env` from CWD (the repo root or `python/`). The `python/tests/.env` path only applies to the live integration tests.
4. README run-tests argument table omits `--client-id`, `--client-secret`, `--environment`; retrieve-tests example outputs show human-formatted text without showing the `--human` flag that produced them; and the "Local Power BI Desktop (auto-detected)" subsection describes the port-file fallback as the primary mechanism when the actual primary is process inspection via `psutil`.

---

## Make `retrieve-tests` Auto-Detect Local PBI Desktop Like `run-tests`

**Requirements**:
- Given `retrieve-tests <filesystem-path>` with no XMLA flags and no env vars, when a Power BI Desktop instance is open with the matching model, should resolve a local XMLA connection and use it for live test discovery (matches `run-tests` behavior)
- Given `retrieve-tests <filesystem-path>` with no XMLA flags and no open Power BI Desktop instance, should fall back to scanning `DAXQueries/` for `*.Tests.dax` files (same as today)
- Given `retrieve-tests <filesystem-path>` with XMLA flags or env vars, should keep today's behavior and use the remote service connection

---

## Update Exit Codes Table to Match Current Runner Behavior

**Requirements**:
- Given the README §"Exit Codes" table is read by a CI engineer, should list every condition that currently produces a non-zero exit code, including the "all discovered tests skipped" case
- Given the table also describes exit 0, should distinguish between "no tests discovered" (exit 0) and "tests discovered but at least one ran and all passed" (exit 0) so the two cases are not conflated with "all skipped"

---

## Clarify `.env` File Placement

**Requirements**:
- Given a user is reading the README §"Connection Options" to set up credentials for the CLI, should be told the `.env` file goes at the **CWD where the CLI is invoked** (repo root or `python/`), not in `python/tests/`
- Given a user is setting up `python/tests/.env`, should be told that path is only for the live integration tests in `test_live_service.py`

---

## Tighten Argument Tables and Mechanism Description

**Requirements**:
- Given the §"run-tests" argument table, should list every supported CLI flag including `--client-id`, `--client-secret`, and `--environment`
- Given the §"Local Power BI Desktop (auto-detected)" subsection, should describe `psutil` process detection as the primary discovery mechanism and the `msmdsrv.port.txt` path as a fallback

---

## Epic Vision (Definition of Done)

### Quality Gates (All Must Pass)

✅ **Ruff Check**: All code passes `ruff check python/` with zero violations

✅ **Code Review**: 
- README accurately reflects all CLI behavior
- No remaining drift between docs and implementation
- Examples are executable without modification

✅ **Test Coverage**: 
- Overall test coverage ≥ 80% (`pytest --cov=pql_test --cov-fail-under=80`)
- All retrieve-tests auto-detection scenarios covered
- All existing tests continue to pass

✅ **Documentation**: 
- README.md updated with accurate connection options, exit codes, .env placement
- All CLI flags documented in argument tables
- Local detection mechanism accurately described
