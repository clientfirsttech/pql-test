# Development Plan

<!-- AI agents use this file to understand current priorities and progress. -->

## Active Work

- **Enable local execution** — validated 2026-05-21
- **Enable execution against the Power BI service** — partially validated (CI path proven; local-machine validation deferred pending `.env` credentials)
- **Provide baseline documentation and usage examples for contributors and early adopters** — see [CONTRIBUTING.md](CONTRIBUTING.md)

## Open Items

- **Local-machine service smoke validation** — `python/tests/.env` is not configured on the maintainer's machine. CI's [run-tests-remote.yml](.github/workflows/run-tests-remote.yml) exercises the service path on every push, so the gap is informational only.

## Backlog

- **Split `python/pql_test/runner.py` into a focused module package** — the file is currently ~1,800 lines mixing 9+ responsibilities (ADOMD loading, model-path parsing, data classes, PBIP filesystem helpers, local PBI Desktop process detection, auth bridge, Power BI REST helpers, MSAL, XMLA execution, test discovery, and the actual test runner). Proposed split into `python/pql_test/runner/` with `models.py`, `adomd.py`, `auth.py`, `pbi_rest.py`, `local_pbi.py`, `model_path.py`, `resolver.py`, `discovery.py`, and `execution.py` (~150–350 lines each). `runner/__init__.py` re-exports the current public API so existing `from pql_test.runner import ...` callers keep working. **Defer** until a feature lands that would otherwise pile more code into the monolith — single-PR mechanical refactor with high regression surface, only worth doing alongside a substantive change.

## Completed Work

### 2026-05-27 — Open-items + local-mode hardening

- **Empty-model exit code drift** fixed in [python/pql_test/runner.py](python/pql_test/runner.py): `retrieve_tests` now filters live discovery strictly against locally-declared test names whenever the model has an ownership-declaring artifact (a `DAXQueries/` directory or `definition/functions.tmdl`). Previously an empty `local_names` set fell through to "pass live discovery through unfiltered," which leaked tests from any unrelated PBI Desktop instance the auto-detector latched onto. New helper `_has_local_ownership_sources` keeps the `local/<name>` and Fabric `workspace.model` pass-through behavior intact (covered by `test_filter_skipped_for_local_model_identifier` and `test_no_local_files_passthrough_keeps_all_live_tests`). `test_exits_0_and_shows_summary_for_empty_model` now passes.
- **`.pbip` file as model path** fixed in `_find_semantic_model_dir`: when given a `.pbip` file, it now prefers the sibling `.SemanticModel` whose stem matches the `.pbip`'s stem (symmetric to the existing logic in `_find_pbip_file`). Before, flat layouts like `examples/` (three side-by-side `.pbip` files) resolved to whichever `.SemanticModel` `iterdir()` returned first, so `pql-test retrieve-tests ./examples/SampleModel.pbip` was silently picking up tests from `OLS_Model.SemanticModel`. Now matches README's claimed behavior end-to-end.
- **Strict `local/<model_name>`** — `resolve_xmla_connection` short-circuits on `ident.kind == "local"` before consulting service credentials. The previous priority order silently redirected `local/<name>` to the deployed dataset whenever `PQL_*` env vars or stored SPN creds were available. New regression test `test_local_identifier_does_not_fall_through_to_service` pins the behavior.
- **`local/<model_name>` diagnostics** — when name-based local detection misses, both `cmd_retrieve_tests` and `cmd_run_tests` now print the full list of detected PBI Desktop instances inline (no `--verbose` required), with `<unnamed>` for instances whose window title couldn't be read, plus a checklist of common causes (model not open, typo/case mismatch, Microsoft Store AppContainer ACL blocking window-title detection). Implemented as `_format_local_miss_diagnostic` in [python/pql_test/cli.py](python/pql_test/cli.py).

### 2026-05-21 — Validation milestone

- Removed dead duplicate package tree: `src/pql_test/`, root-level `tests/`, root `pyproject.toml`. Canonical tree is now unambiguously [python/pql_test/](python/pql_test/).
- Fixed 4 bugs surfaced by validation on a clean Windows machine:
  - `cli.py` — forced UTF-8 stdout to prevent `UnicodeEncodeError` on the ✅ / ❌ status markers when running in a default `cp1252` PowerShell session.
  - `runner.py` — added NuGet-installed `Microsoft.AnalysisServices.AdomdClient` to the assembly search path, plus a fallback to the `AnalysisServices` assembly name (the installer-version Power BI Desktop ships `Microsoft.PowerBI.AdomdClient`; NuGet and standalone ADOMD.NET ship `Microsoft.AnalysisServices.AdomdClient`).
  - `runner.py` — same change resolves the Microsoft Store Power BI Desktop sandbox issue (its `bin/` lives under ACL-protected `C:\Program Files\WindowsApps\` and is not loadable from outside its AppContainer).
  - `tests/test_pql_test_runner.py` + `tests/test_live_service.py` — corrected 14 imports from the phantom `pql_test_runner` module to `pql_test.runner`. Recovered 13 previously-failing tests.
- Fixed [README.md](README.md) path references throughout — the documented `./examples/SampleModel/` directory does not exist; the repo's `examples/` is a flat layout with three PBIP models side-by-side. Updated all command examples to use `./examples/SampleModel.SemanticModel`. Corrected the Troubleshooting section that previously gave inverted advice.
- Added [CONTRIBUTING.md](CONTRIBUTING.md) covering: prereqs (with NuGet ADOMD.NET recipe), Microsoft Store PBI Desktop gotcha, DAX user-defined-functions preview-feature requirement, local + service smoke-test recipes, and the PR checklist.
- Smoke-validated local execution end-to-end: `pql-test run-tests examples/SampleModel.SemanticModel` against Power BI Desktop returned `47 passed, 15 failed, 62 total` (the 15 failures are legitimate model-quality issues caught by the suite, not CLI bugs).
- pytest suite now at **252 passed / 2 failed / 6 deselected (99.2% pass rate)**. The 2 remaining failures were the empty-model exit-code drift, resolved in the 2026-05-27 hardening pass.

### Earlier

- **Fabric CLI Authentication** — See [tasks/fabric-cli-auth-epic.md](tasks/fabric-cli-auth-epic.md) (archived 2026-05-16)
  - Modern authentication with `azure-identity` and `keyring`
  - Support for 5 authentication methods (interactive, service principal with secret/cert, managed identity)
  - CLI commands: `auth login` / `logout` / `status`
  - Backward compatible with environment variables and CLI flags
  - 39 unit tests passing
- Core CLI implementation (`check-prereqs`, `retrieve-tests`, `retrieve-test`, `run-tests`)
- Three MODEL_PATH formats (filesystem, `local/`, `workspace.model`)
- CI pipeline with 3 stages (`validate-plugin`, `promptfoo-eval`, `run-tests-remote`)
- Copilot CLI plugin with 4 installable skills
- Service principal authentication via MSAL
- Example semantic models (`SampleModel`, `RLS_Model`, `OLS_Model`)
- Promptfoo skill evaluations migrated from Node.js to plain Python
