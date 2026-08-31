# Development Plan

<!-- AI agents use this file to understand current priorities and progress. -->

## Active Work

- **Enable local execution** — validated 2026-05-21
- **Enable execution against the Power BI service** — partially validated (CI path proven; local-machine validation deferred pending `.env` credentials)
- **Provide baseline documentation and usage examples for contributors and early adopters** — see [CONTRIBUTING.md](CONTRIBUTING.md)
- **Refactor runner.py monolith into focused module package** — CRITICAL for maintainability (promoted from backlog 2026-08-30). File is 1,947 lines mixing 9+ responsibilities, causing high regression risk and slow code review velocity. Split into `runner/` package with 9 focused modules (~150-350 lines each). See [tasks/runner-refactor-epic.md](tasks/runner-refactor-epic.md). Estimated 2-3 days.
- **Implement token validation in auth/manager.py** — TODO at line 123 needs implementation for OWASP A07 (Authentication Failures). Validate JWT expiry without making service calls. Estimated 4 hours.
- **Security audit and OWASP Top 10 compliance** — Run `pip-audit`, threat-model authentication flows (5 methods), validate RLS/OLS role assignment security, add audit logging for auth attempts. Address A01, A04, A06, A07 findings from 2026-08-30 AIDD review. Estimated 1 day.
- **Test coverage metrics and tracking** — Run `pytest --cov`, set minimum 80% threshold in `pyproject.toml`, add coverage badge to README, track trend in CI. Currently 252 tests passing but coverage percentage unknown. Estimated 2 hours.

## Open Items

- **Local-machine service smoke validation** — `python/tests/.env` is not configured on the maintainer's machine. CI's [run-tests-remote.yml](.github/workflows/run-tests-remote.yml) exercises the service path on every push, so the gap is informational only.

- **PyPI initial release — manual steps remain** — code/config side is ready ([python/pyproject.toml](python/pyproject.toml), [.github/workflows/release.yml](.github/workflows/release.yml), MIT [LICENSE.txt](LICENSE.txt) synced to `python/`, release checklist in [CONTRIBUTING.md](CONTRIBUTING.md)).  Maintainer still has to: (1) `cd python && python -m build && twine check --strict dist/*` locally to confirm a clean build, (2) create accounts on https://test.pypi.org and https://pypi.org if they don't exist, (3) register trusted publishers on both for `pql-test` with workflow name `release.yml` and environments `testpypi` / `pypi`, (4) create matching GitHub Environments in repo settings, (5) `git tag v0.1.0 && git push --tags` to fire the release workflow.  See the "Releasing a new version" section in [CONTRIBUTING.md](CONTRIBUTING.md).

## Backlog

- **~~Split `python/pql_test/runner.py` into a focused module package~~** — PROMOTED TO ACTIVE WORK (2026-08-30). See above and [tasks/runner-refactor-epic.md](tasks/runner-refactor-epic.md).

- **Restore interactive prompt for service-principal-with-certificate auth** — removed from `pql-test auth login`'s interactive menu on 2026-05-27 to keep the first-run UX focused on the two most common paths (browser interactive, SPN with secret). The underlying support is still wired end-to-end: `AuthMethod.SERVICE_PRINCIPAL_CERT`, the factory in [python/pql_test/auth/factory.py](python/pql_test/auth/factory.py), and the `--certificate` / `-u` / `--tenant` flag combination in [cli.py:cmd_auth_login](python/pql_test/cli.py) all still work for power users. Re-expose in the prompt once we have a real user asking for it, or after the public launch when we want to broaden the documented auth surface.

- **Restore interactive prompt for managed-identity auth** — removed from `pql-test auth login`'s interactive menu on 2026-05-27 alongside the certificate path. Underlying support is intact: `AuthMethod.MANAGED_IDENTITY` (system- and user-assigned), the factory, and the `--identity` flag all still function. Most useful when pql-test is invoked from inside Azure VMs / containers / Azure DevOps agents where no secret needs to be stored at all. Re-expose in the prompt when we have a customer running pql-test from inside Azure infrastructure.

- **Document type suppressions** — 42 `type: ignore` and `noqa` suppressions lack inline justification. Add comments explaining why each is necessary (e.g., .NET interop, TextIO protocol limitations). Estimated 2 hours.

- **Expand deprecated features documentation** — Add "Deprecated Features" section to README documenting `<workspace>.<model>` dot notation deprecation and migration guide to Fabric-style `<workspace>.Workspace/<model>.SemanticModel` syntax. Link from CLI deprecation warnings. Estimated 1 hour.

- **Document hermetic test mode** — Add `PQL_TEST_HERMETIC` environment variable documentation to CONTRIBUTING.md for test developers. Currently undocumented but used throughout test suite. Estimated 30 minutes.

## Completed Work

### 2026-05-28 — Issue Review Agent Workflow

- **Issue Review Agent Workflow** — See [tasks/archive/2026-05-28-issue-review-agent.md](tasks/archive/2026-05-28-issue-review-agent.md)
  - GitHub Agentic Workflow triggered by issue creation or manual dispatch
  - Two-phase execution: bash pre-computation + Copilot agent instructions
  - Automated issue analysis, code generation, and PR creation
  - Tool restrictions for security (edit + limited bash commands)
  - Comprehensive documentation with usage examples

### 2026-05-27 — PyPI publishing prep

- **License resolved + corrected** — repo previously had a contradiction: [LICENSE.txt](LICENSE.txt) was Business Source License 1.1 (with a stale "Power Query Lint VS Code Extension" Licensed-Work name copy-pasted from the sibling repo) while [python/pyproject.toml](python/pyproject.toml) claimed MIT.  Maintainer confirmed BSL 1.1 is the intended license, matching the sibling [power-query-lint-vs-code-extension](https://github.com/clientfirsttech/power-query-lint-vs-code-extension) repo.  LICENSE.txt now uses the upstream BSL 1.1 text verbatim with `Licensed Work: pql-test`, `Additional Use Grant: None`, `Change Date: Four years from publish`, `Change License: GNU Affero General Public License v3.0`.  Synced to `python/LICENSE.txt` so the wheel ships it.
- **[python/pyproject.toml](python/pyproject.toml)** polished for PyPI: PEP 639 SPDX form (`license = "BUSL-1.1"` + `license-files`), explicit `authors`/`maintainers`, ten classifiers including the `Operating System :: Microsoft :: Windows` constraint that reflects pyadomd's reality, `[project.urls]` block, expanded `dev` extras to include `build` + `twine`, `setuptools>=77` requirement (for PEP 639 support).  No `License :: OSI Approved :: ...` classifier — BSL 1.1 is source-available, not OSI-approved.
- **Release workflow added** — [.github/workflows/release.yml](.github/workflows/release.yml) uses PyPI Trusted Publishing (OIDC) instead of stored tokens.  Tag-triggered for real PyPI, workflow_dispatch for TestPyPI rehearsal.  Includes a tag-vs-pyproject version guard that fails fast on mismatch.
- **Release checklist** added to [CONTRIBUTING.md](CONTRIBUTING.md) covering version bump, optional TestPyPI rehearsal, tagging, and post-publish smoke test.
- `README.md` and `LICENSE.txt` copied into `python/` so setuptools can find them at build time without restructuring the repo.  Both copies stay in sync via the release checklist (manual until/unless we automate it).

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
