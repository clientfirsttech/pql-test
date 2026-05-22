# Development Plan

<!-- AI agents use this file to understand current priorities and progress. -->

## Active Work

- **Enable local execution** — validated 2026-05-21
- **Enable execution against the Power BI service** — partially validated (CI path proven; local-machine validation deferred pending `.env` credentials)
- **Provide baseline documentation and usage examples for contributors and early adopters** — see [CONTRIBUTING.md](CONTRIBUTING.md)

## Open Items

- **Empty-model exit code drift** — `pql-test run-tests` against an empty `DAXQueries/` directory currently exits 1; the unit tests `test_exits_0_and_shows_summary_for_empty_model` and `test_local_flag_exits_0_for_empty_model` expect exit 0. Either the CLI behavior changed or the test expectations are stale. Resolve in the next contributor pass.
- **Local-machine service smoke validation** — `python/tests/.env` is not configured on the maintainer's machine. CI's [run-tests-remote.yml](.github/workflows/run-tests-remote.yml) exercises the service path on every push, so the gap is informational only.
- **`.pbip` file as model path** — the README claims `pql-test run-tests ./examples/SampleModel.pbip` works; in practice it returns an empty test list silently. Either fix the runner's `.pbip` resolution or remove the claim from README's "Model Path Formats" table.

## Completed Work

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
- pytest suite now at **252 passed / 2 failed / 6 deselected (99.2% pass rate)**. The 2 remaining failures are the empty-model exit-code drift documented above.

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
