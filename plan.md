# Development Plan

<!-- AI agents use this file to understand current priorities and progress. -->

## Active Work

- **Enable local execution** — validated 2026-05-21
- **Enable execution against the Power BI service** — partially validated (CI path proven; local-machine validation deferred pending `.env` credentials)
- **Provide baseline documentation and usage examples for contributors and early adopters** — see [CONTRIBUTING.md](CONTRIBUTING.md)

## Open Items

- **Before the repository goes public.** History, pull request refs, and the Actions logs and artifacts the API still serves were scanned with gitleaks (2026-10-29): no real secret. The 2026-11-05 pre-launch review fixes are in [tasks/pre-launch-review-fixes-epic.md](tasks/pre-launch-review-fixes-epic.md). Maintainer steps left, in order:
  1. Delete old Actions runs before launch. 222 run logs could not be fetched for the scan (HTTP 500) and would become public.
  2. CLA ([CLA.md](CLA.md), [cla.yml](.github/workflows/cla.yml); the `cla-signatures` branch and `PERSONAL_ACCESS_TOKEN` secret are set up, and `kerski-cft` and `kerski` are allowlisted):
     - decide whether a Corporate CLA is needed (CLA section 4 refers to one), or reword that clause;
     - confirm the Company holds the rights to past contributors' code (employment or contractor terms, or a signed CLA), which dual licensing depends on;
     - decide whether other staff accounts go on the allowlist.
  3. Every maintainer runs `pip install pre-commit && pre-commit install` once per clone, and confirms the author and maintainer details in `python/pyproject.toml`.
  4. **At launch**, in the repository settings:
     - secret scanning and push protection; private vulnerability reporting (SECURITY.md links to it); "Require approval for all outside collaborators" for fork pull request workflows;
     - make `cla` a required status check on `main`;
     - give the `pypi` Environment (created by the first `release.yml` run) required reviewers and limit it to `v*` tags; add a tag ruleset protecting `v*`; optionally set `pypi` as the Environment name in the PyPI trusted publisher;
     - limit the `federated-smoke` and `certificate-smoke` Environments to `main`, with required reviewers.
  5. Release 0.2.0, the first AGPL-3.0-only release. v0.1.x stays BUSL-1.1.

  Done: identifying data in history stays (decided 2026-10-29, no history rewrite); repository settings for the private repo (Dependabot, read-only `GITHUB_TOKEN`, `main` protection with Code Owner review); the issue-review agent is manual only; `requires-python >= 3.10`; the expired test secret is deleted and `PQL_CLIENT_SECRET` renewed; pql-odcs is merged into pql-test under AGPL-3.0-only.

## Backlog

- **Contract commands: decisions in force**

  Decided 2026-10-25/26 (still in force): ODCS v3.2.x is supported; model names come only from the contract's `customProperties` (`pbiTable` / `pbiColumn`); generated `.dax` files can be regenerated in CI or committed with a drift check ([docs/contracts.md](docs/contracts.md)); PQL.Assert gaps are tracked in [docs/pql-assert-gap-plan.md](docs/pql-assert-gap-plan.md).

  Decided 2026-10-28: pql-odcs is merged into pql-test (`pql-test contract`), and the repository is AGPL-3.0-only. The design record is [docs/pql-odcs-implementation-plan.md](docs/pql-odcs-implementation-plan.md) (superseded).

- **Contract commands: next** — Contents:
  - query-scoped XMLA target (`--target query`) and the `<workspace>.Workspace/<model>.SemanticModel` MODEL_PATH;
  - the datacontract-cli side of the integration (a datacontract-cli engine or wrapper that calls `pql-test contract run` and reads its `--output` JSON). It must stay CLI-to-CLI: datacontract-cli is MIT and cannot import AGPL code. pql-test's half is done: the output is a versioned, tested schema.

- **Contract commands: later** — Contents:
  - a spike on TOM/TMSL/TMDL UDF scripting over XMLA;
  - then the persistent deploy target (`--target deploy`, `--install-library`, `--clean`, `--allow-production`).

- **Contract commands: optional** — Contents:
  - a Bitol RFC for a Power BI / Fabric semantic model `servers` type.
  - An upstream `datacontract export pql-assert` would need code under a license datacontract-cli accepts (MIT), so it is only possible as a separately licensed contribution.

- **Restore interactive prompt for service-principal-with-certificate auth** — removed from `pql-test auth login`'s interactive menu on 2026-05-27 to keep the first-run UX focused on the two most common paths (browser interactive, SPN with secret). The underlying support is still wired end-to-end: `AuthMethod.SERVICE_PRINCIPAL_CERT`, the factory in [python/pql_test/auth/factory.py](python/pql_test/auth/factory.py), and the `--certificate` / `-u` / `--tenant` flag combination in [cli.py:cmd_auth_login](python/pql_test/cli.py) all still work for power users. Re-expose in the prompt once we have a real user asking for it, or after the public launch when we want to broaden the documented auth surface.

- **Restore interactive prompt for managed-identity auth** — removed from `pql-test auth login`'s interactive menu on 2026-05-27 alongside the certificate path. Underlying support is intact: `AuthMethod.MANAGED_IDENTITY` (system- and user-assigned), the factory, and the `--identity` flag all still function. Most useful when pql-test is invoked from inside Azure VMs / containers / Azure DevOps agents where no secret needs to be stored at all. Re-expose in the prompt when we have a customer running pql-test from inside Azure infrastructure.

- **Security audit leftovers (2026-11-03)** — the federated example now has a manual workflow, [federated-smoke.yml](.github/workflows/federated-smoke.yml); a maintainer still has to create the Entra federated credential and the `federated-smoke` Environment, then run it once; the same for the certificate path ([certificate-smoke.yml](.github/workflows/certificate-smoke.yml), Environment `certificate-smoke`); add an Azure DevOps managed-identity example. See [docs/security-threat-model.md](docs/security-threat-model.md).

- **Document type suppressions** — 42 `type: ignore` and `noqa` suppressions lack inline justification. Add comments explaining why each is necessary (e.g., .NET interop, TextIO protocol limitations). Estimated 2 hours.

- **Expand deprecated features documentation** — Add "Deprecated Features" section to README documenting `<workspace>.<model>` dot notation deprecation and migration guide to Fabric-style `<workspace>.Workspace/<model>.SemanticModel` syntax. Link from CLI deprecation warnings. Estimated 1 hour.

- **Document hermetic test mode** — Add `PQL_TEST_HERMETIC` environment variable documentation to CONTRIBUTING.md for test developers. Currently undocumented but used throughout test suite. Estimated 30 minutes.

## Completed Work

### 2026-11-12 — Faster local Power BI Desktop discovery, version 0.2.1

`get_pbi_files_opened()` now makes one `process_iter(["pid", "name"])` pass and reads `cmdline()` / `ppid()` only for `PBIDesktop.exe` / `msmdsrv.exe`, instead of prefetching both for every process. Benchmarked with two models open (378 processes): 54.9 ms → 3.8 ms median. Version bumped to 0.2.1. Epic: [tasks/archive/2026-11-12-fast-local-pbi-process-discovery.md](tasks/archive/2026-11-12-fast-local-pbi-process-discovery.md).

### 2026-11-04 — Published JSON schema for `contract run` output (branch `dev-odcs`)

`contract run --output` and `contract trace --format json` now carry `schemaVersion: 1` and are described by `python/pql_test/odcs/contract-run-result.schema.json` (packaged). `tests/odcs/test_run_result_schema.py` validates real output against it and checks the schema agrees with the code. Documented in docs/contracts.md, "Reading the results from another tool".

### 2026-11-04 — Certificate expiry warning in `pql-test auth status` (branch `dev-odcs`)

`auth status` reads the stored service-principal certificate's expiry (PEM or PFX, public part only, via `cryptography`, already a dependency of msal) and warns at 30 days or fewer, or once expired. JSON output adds `certificateExpiresAt` and `certificateDaysRemaining`. See `python/pql_test/auth/cert_expiry.py`.

### 2026-11-04 — PQL.Assert minimum-version warning in `contract run` (branch `dev-odcs`)

`contract run` now warns when the connected model's PQL.Assert is older than the newest catalog (0.9), or older than an explicit `--pql-assert`. Non-blocking; shown on stderr and in the CI pre-warnings. See `pql_assert_version_warning` in `contract_run.py`.

### 2026-11-04 — Counsel review of the AGPL-3.0 relicensing dropped

Decided: AGPL-3.0-only stands as is, with no counsel review. Removed the "LAST EPIC" and the review gate on the 0.2.0 release.

### 2026-11-04 — By-name service path no longer raises on auth failures (branch `dev-odcs`)

`resolve_service_xmla_connection_by_name` now catches credential and token failures, warns on stderr, and returns None, so `run-tests`, `retrieve-tests`, and `retrieve-test` print one clean error instead of a traceback (their message no longer blames missing flags). Two tests added. Added the manual `federated-smoke.yml` workflow for the federated-credential example.

### 2026-11-03 — Security audit: OWASP A01, A04, A06 (branch `dev-odcs`)

- See [tasks/archive/2026-11-03-security-audit.md](tasks/archive/2026-11-03-security-audit.md) and [docs/security-threat-model.md](docs/security-threat-model.md).
- `pip-audit` (requirements and project dependencies) and `bandit -ll` found nothing. Dependabot covers pip and GitHub Actions; every workflow sets `permissions:`.
- **Fixed:** the XMLA connection string quoted catalog, role, and user values but not the client secret, token, client ID, or server, so a secret containing `;Roles=Admin` added a `Roles=` key. All values now go through `_conn_value` (`python/pql_test/runner/xmla.py`), with tests.
- **Fixed:** `.github/copilot-setup-steps.yml` used an unpinned `actions/checkout@v4`.
- **Documented:** federated-credential subject claims with a GitHub Actions example (not yet run end to end), and managed-identity least privilege, in CONTRIBUTING.md; the threat model's statuses, duplicates, and compliance table are current.

### 2026-11-03 — Plan cleanup: two Active Work items were already done

- **Runner refactor** — `python/pql_test/runner/` is already a package of 15 focused modules (`xmla.py`, `adomd.py`, `resolver.py`, `discovery.py`, `execution.py`, `local_pbi.py`, `coverage*.py`, `cli_format.py`, and others); the monolith was removed 2026-09-02 and `tasks/runner-refactor-epic.md` no longer exists.
- **Token validation (OWASP A07)** — `_decode_jwt_expiry()` in [python/pql_test/auth/manager.py](python/pql_test/auth/manager.py) reads the JWT `exp` claim without a service call, and the token-acquire path reports `token_expires_at` / `token_is_valid`. The "TODO at line 123" no longer exists.

### 2026-11-02 — Adopt PQL.Assert 0.9.0: native refresh-recency check (branch `dev-odcs`)

- See [tasks/archive/2026-11-02-pql-assert-0-9.md](tasks/archive/2026-11-02-pql-assert-0-9.md).
- Vendored fixture replaced: `python/tests/odcs/fixtures/pql-assert-0.9.0/` (0.9 is additive-only, so one copy covers all three catalogs); `Tbl.LastRefreshShouldBeWithinHours` classified `mapped` in `pql_assert_functions.yaml`.
- New `pql_assert_0_9.yaml` catalog (`extends: pql_assert_0_8`) maps ODCS `frequency` to `Tbl.LastRefreshShouldBeWithinHours(testName, tableName, maxAgeHours)` instead of 0.8's inline `INFO.PARTITIONS()` expression; still reported **approximated**. `--pql-assert 0.7` and `0.8` output is unchanged. `--pql-assert 0.9` is now a valid choice on `generate`, `coverage`, `trace`, and `run`; the default stays `0.7`.
- **Found while vendoring:** `engine: pql-test` direct calls are validated against the newest vendored PQL.Assert signatures, not a fixed version, so bumping the fixture to 0.9.0 silently raised the version a direct call needs from `--pql-assert 0.8` to `0.9` (the same thing happened, unnoticed in docs, when 0.7.1 → 0.8.0 shipped). Fixed the skip message to read the version dynamically (`pql_test/odcs/mapping/dax_rules.py`) instead of a hardcoded literal, and documented the behavior change in [docs/contracts.md](docs/contracts.md#pqlassert-09): a contract with a direct call that generated fine under `--pql-assert 0.8` now reports it skipped until it moves to `0.9`.
- `docs/contracts.md` gets a `### PQL.Assert 0.9` section; `docs/pql-assert-freshness-request.md` and the R8 note in `docs/pql-assert-gap-plan.md` are marked fulfilled.
- `tests/odcs/test_pql_assert_0_9.py` (new) plus updates across `test_function_matrix.py`, `test_library_conformance.py`, `test_docs_contracts_agreement.py`, `test_dax_rules.py`, `test_contract_run.py`, and a new `rule-coverage-0-9` golden case. Full suite: 1149 passed, 0 failed, 2 skipped (`pytest -m "not live"`; `test_properties.py` excluded, `hypothesis` not installed in this environment).
- Version stays `0.2.0` (still unreleased per `aidd-custom/skills/pql-test-version-bump/SKILL.md`'s own rule: pyproject is already ahead of the latest tag `v0.1.13`, so this folds into that pending release).
- **Live validation (user deployed, 2026-11-02):** `examples/SampleModel.SemanticModel/definition/functions.tmdl` bumped to 0.9.0 and republished to the test Fabric workspace; `contract doctor` confirms deployed and model-folder both report `--pql-assert 0.9` with no drift, and `contract run --pql-assert 0.9` against the live model passes every rule in `examples/contracts/freshness.odcs.yaml`, including the new `Tbl.LastRefreshShouldBeWithinHours`-backed refresh-age check.
  - Caught a hardcoded `"0.8.0"` string literal in `PQL.Assert.LibraryVersion()`'s function body (the version bump script only touched `DAXLIB_PackageVersion` annotations) — the deployed model kept reporting 0.8.0 live until this was fixed and republished.
  - Caught two gaps in `tests/test_contract_live.py` only visible once `-m live` actually ran against the republished model (the epic itself never exercises `-m live`): `EXPECTED_RULE_COVERAGE` still pinned outcomes for two `engine: pql-test` direct-call rules that now always skip under `--pql-assert 0.8` (direct calls need `LATEST_PQL_ASSERT`, now 0.9); and `_committed_catalog()` capped at `"0.8"` regardless of how new the committed version actually was. Full live suite now 19 passed; offline suite still 1149 passed, 0 failed, 2 skipped.

### 2026-10-29 — Contract gap detection: ODCS rule matrix, docs agreement, gap-check skill, examples (branch `dev-odcs`)

- See [tasks/archive/2026-10-29-contract-gap-detection.md](tasks/archive/2026-10-29-contract-gap-detection.md) and [docs/contracts.md](docs/contracts.md#how-we-keep-this-mapping-complete).
- `test_odcs_rule_matrix.py` classifies every value in ODCS's closed vocabularies (`pql_test/odcs/catalog/odcs_rules.yaml`), mirroring the PQL.Assert function matrix; a new ODCS release's metric, quality type, `logicalType`, relationship type, or `logicalTypeOptions` key fails a test until classified and demonstrated in a fixture.
- `test_docs_contracts_agreement.py` checks `docs/contracts.md`'s mapping tables against the catalogs, both directions, plus six skip reasons against what the mapper actually produces.
- `aidd-custom/skills/pql-test-contract-gap-check/SKILL.md`, wired into `/aidd-review` step 9 alongside the docs check: checks for a new Bitol ODCS or PQL.Assert release and runs both matrices plus the docs-agreement test.
- `examples/contracts/` (`starter.odcs.yaml`, `scenario-tests.odcs.yaml`, `freshness.odcs.yaml`): runnable, live-verified example contracts for learners, linked from `docs/contracts.md` and the contract skill in place of pointing at test fixtures.

### 2026-10-29 — Contract rule coverage: value rules, DAX rules, latency vs frequency (branch `dev-odcs`)

- See [tasks/archive/2026-10-29-contract-rule-coverage.md](tasks/archive/2026-10-29-contract-rule-coverage.md) and [docs/contracts.md](docs/contracts.md).
- With `--pql-assert 0.8`: numeric bounds, text length, `enum`, `invalidValues` value lists, `missingValues`, and `relationships` map to PQL.Assert; `lint` checks relationships against the TMDL. 0.7 output is unchanged.
- `type: custom` rules with `engine: pql-test` carry DAX (an expression and a comparator, or a direct PQL.Assert call), run in their own `ContractDax` suite. `pql_assert_functions.yaml` classifies all 126 PQL.Assert 0.8.0 functions, and a test fails on an unclassified one.
- Freshness: `latency` is data age (a timestamp column), `frequency` is refresh recency (`INFO.PARTITIONS()`, in its own `RefreshAge` suite). [docs/pql-assert-freshness-request.md](docs/pql-assert-freshness-request.md) asks PQL.Assert 0.9.0 for a refresh function and docs that separate the two.
- Proven live against SampleModel (`rule-coverage-live.odcs.yaml`, 45 rules with pinned outcomes and failure text). Confirmed 2026-10-29: the standard service principal in `python/.env` reads `INFO.PARTITIONS()` fine (it already does, for `Partitions.*`), so `RefreshAge` runs cleanly end to end with the identity pql-test uses everywhere; no separate restricted-identity gap to chase.

### 2026-10-28 — pql-odcs merged into pql-test; AGPL-3.0-only (branch `dev-odcs`)

- See [tasks/archive/2026-10-28-merge-pql-odcs-agpl.md](tasks/archive/2026-10-28-merge-pql-odcs-agpl.md).
- One package and one CLI: `pql-test contract lint|coverage|generate|trace|run|doctor`, with the same MODEL_PATH forms everywhere (`local/<name>` included). The standalone `pql-odcs` CLI, its skill command, the plugin loader, and the `contracts` extra are gone.
- The repository is AGPL-3.0-only; the license-boundary CI checks are replaced by a Linux stage for the file-based commands ([linux.yml](.github/workflows/linux.yml), ci.yml Stage 3c).

### 2026-10-27 — pql-odcs adopts PQL.Assert 0.8.0 (branch `dev-odcs`)

- See [tasks/archive/2026-10-27-pql-odcs-pql-assert-0-8.md](tasks/archive/2026-10-27-pql-odcs-pql-assert-0-8.md) and [docs/pql-assert-gap-plan.md](docs/pql-assert-gap-plan.md).
- A second catalog, `pql_assert_0_8.yaml`, extends the 0.7 one. `--pql-assert 0.7|0.8` on `generate`, `coverage`, and `trace` picks it; the default stays 0.7 and its golden files are unchanged.
- With 0.8: exact `required`, `primaryKey`, `unique`, and `duplicateValues`; null and duplicate ceilings; percent null rates; multi-column keys (R3); `mustNotBeBetween` (R2); simple anchored patterns (R7); `latency` freshness (R8, approximated).
- `pql-test contract run` defaults to `--pql-assert auto`: it queries `PQL.Assert.LibraryVersion()` and falls back to 0.7. The connection is now resolved before generating.
- Still open: run the 0.8 output against a model with PQL.Assert 0.8.0 (the gap plan's unrun variants), and the v0.2 items that need no 0.8 function (types, relationships, ranges, text length, value lists, `missingValues`, the query-scoped XMLA target, the datacontract-cli adapter).

### 2026-10-25 — pql-odcs v0.1: ODCS data contracts → PQL.Assert suites (branch `dev-odcs`)

- See [tasks/archive/2026-10-25-pql-odcs-v0.1.md](tasks/archive/2026-10-25-pql-odcs-v0.1.md) and [docs/pql-odcs-implementation-plan.md](docs/pql-odcs-implementation-plan.md).
- **pql-odcs** is a new MIT package under `packages/pql-odcs/`. It:
  - loads ODCS v3.0.x, v3.1.x, and v3.2.x contracts and validates them against the bundled Bitol schemas;
  - resolves model names from `pbiTable`/`pbiColumn` customProperties on the contract, else the logical name;
  - maps each rule through a PQL.Assert 0.7.1 catalog (data only);
  - writes `<Prefix>.<Suite>.<ENV>[WARN].Tests.dax` suites;
  - reports every rule as mapped, approximated, or skipped (`coverage`);
  - joins pql-test results back to rule ids (`trace`);
  - checks names against the model's TMDL (`lint --model`);
  - ships as the standalone `pql-odcs` CLI.
- **pql-test 0.2.0** loads plugins from the `pql_test.commands` entry point and adds `pql-test contract run`. It installs the plugin through the optional `contracts` extra. Generated suites run from their own DEFINE FUNCTION text, so they don't depend on the model's registered tests.
- **License boundary**:
  - the `LICENSE.txt` scope note, `LICENSES.md`, CODEOWNERS, and the DCO guidance;
  - SPDX headers on every `python/` and pql-odcs `.py` file;
  - CI checks: SPDX, import-linter, wheel contents, and dependency licenses.
- **CI and release**:
  - `pql-odcs.yml` runs Linux, macOS, and Windows on Python 3.9 and 3.13, plus a standalone install and a plugin install;
  - `release-pql-odcs.yml` publishes on `pql-odcs-v*` tags;
  - `pytest.yml` now installs the `contracts` extra.
- **Testing**:
  - the live `contract run` against SampleModel in Fabric passed: the good contract passes every mapped rule, and the must-fail contract fails exactly the 5 planted rules;
  - pql-odcs: 136 tests at 95% coverage, including golden files and hypothesis tests, passing on Python 3.9 and 3.12;
  - pql-test suite green.
- **Review**: an AIDD review found and fixed these issues:
  - cross-contract suite overwrite and deletion;
  - trace now joins on the `ODCS <id> <ruleId>:` prefix;
  - header injection through the contract id;
  - duplicate rule ids;
  - NaN/inf thresholds;
  - malformed sidecar crash (the sidecar was later removed, 2026-10-26);
  - release could publish from a non-tag ref;
  - `contract run` now emits `--log-format` annotations and writes the per-rule trace into `--output`;
  - `primaryKey`/`unique`/`duplicateValues`, and `required` on string columns, are now reported as approximated, with the DAX semantics as the reason (gap plan C4/C5).

### 2026-10-22 — certifi floor for PYSEC-2026-4320, bump to 0.1.20

- Added `certifi>=2026.10.19` to [python/pyproject.toml](python/pyproject.toml) and [python/requirements.txt](python/requirements.txt). certifi arrives transitively via `msal`/`azure-core` → `requests`; versions before 2026.10.18 trust the `emSign ECC Root CA - G3` root whose intermediates have compromised keys, which would allow on-path interception of the Entra ID token traffic.
- virtualenv CVE-2026-113725 / CVE-2026-113722 reviewed: not a dependency, not applicable.
- Version bumped 0.1.19 → 0.1.20 across all manifests and skills.

### 2026-09-23 — `--min-coverage` parity with pytest-cov, threshold-aware colors, version alignment

- See [tasks/archive/2026-09-23-min-coverage-parity-version-alignment.md](tasks/archive/2026-09-23-min-coverage-parity-version-alignment.md)
- **CI-gate semantics** — `--min-coverage` already exited 1 below the threshold (same as pytest-cov `--cov-fail-under`, Jest, nyc). Added coverage.py's guard so a percentage only rounds to 100% when every eligible object is covered (`coverage_percent()` in [python/pql_test/runner/coverage_report.py](python/pql_test/runner/coverage_report.py)), and a pytest-cov-style `Required coverage of N% reached` line when the gate passes (stderr when JSON is on stdout).
- **Colors** — replaced the hard-coded 100%/0%/partial coloring with `coverage_status()`: default 50/80 watermarks (Istanbul/Jest), or binary pass/fail against `--min-coverage` when set. The overall line is now colored too.
- **Version alignment** — `plugin.json` bumped from its never-updated `0.1.0` to `0.1.18b1`. New [aidd-custom/skills/pql-test-version-bump/SKILL.md](aidd-custom/skills/pql-test-version-bump/SKILL.md) lists every file that carries the version; [python/tests/test_version_alignment.py](python/tests/test_version_alignment.py) and a new validate-plugin CI step fail on drift.
- **Docs/evals** — `code-coverage` promptfoo eval added; skill exit codes and color rules documented; README GitHub Actions coverage-gate example; vision.md command list updated.
- Full suite at 573 passed / 2 skipped under `pytest -m "not live"`.

### 2026-09-22 — Consistent CLI output between `run-tests` and `code-coverage`

- **Unify CLI presentation** — See [tasks/archive/2026-09-22-consistent-cli-output.md](tasks/archive/2026-09-22-consistent-cli-output.md)
  - `run-tests` and `code-coverage` had drifted into two different presentation styles (banner + bordered color table + connection diagnostic vs. plain indented text with no connection line) because presentation logic lived as ad hoc closures inside `cli.py` next to each command's business logic, with no shared module and no written contract.
  - Extracted [python/pql_test/runner/cli_format.py](python/pql_test/runner/cli_format.py) (`banner`, `pad`, `truncate`, `table_top`/`table_mid`/`table_bottom`/`table_row`, `STATUS_COLORS`) and retrofitted `run-tests`' `_print_results` onto it — behavior-preserving refactor, existing tests unchanged.
  - `code-coverage`'s `collect_coverage()` now threads its resolved `ResolvedXmlaConnection` onto `CoverageReport`; the CLI prints the same `Local XMLA connection: ... / catalog: ...` line and a `coverage session starts` banner `run-tests` shows, and its "By category" section renders as a bordered table colored green/red/yellow (full/none/partial coverage) using the same `STATUS_COLORS` vocabulary as PASS/FAIL/SKIP.
  - Documented the convention in [CONTRIBUTING.md](CONTRIBUTING.md#cli-output-conventions) and pointed [aidd-custom/AGENTS.md](aidd-custom/AGENTS.md) at it so a future command reuses `cli_format.py` instead of reinventing a third style. Updated `README.md`'s `code-coverage` sample output to match.
  - 19 new/updated tests (14 in `test_cli_format.py`, 5 across `test_coverage_collector.py`/`test_code_coverage_cli.py`); full suite at 550 passed / 2 skipped under `pytest -m "not live"`.

### 2026-09-22 — Direct test-UDF semantic-model code coverage

- **Add `pql-test code-coverage`** — See [tasks/archive/2026-09-22-direct-udf-code-coverage.md](tasks/archive/2026-09-22-direct-udf-code-coverage.md)
  - Validated live against SampleModel, RLS_Model, and OLS_Model which object categories `INFO.CALCDEPENDENCY()` can directly evidence from a test UDF (tables, calculated columns, measures) versus which need indirect evidence (roles via `PQLAssert_RoleName`, relationships via DAX expression-text parsing) or have none at all (partitions) — recorded in [tasks/direct-udf-code-coverage-metadata-contract.md](tasks/direct-udf-code-coverage-metadata-contract.md).
  - Added [python/pql_test/runner/coverage.py](python/pql_test/runner/coverage.py) (evidence/exclusion/gap types + `classify_coverage()`), [python/pql_test/runner/coverage_collector.py](python/pql_test/runner/coverage_collector.py) (the live XMLA-backed collector, `collect_coverage()`), and [python/pql_test/runner/coverage_report.py](python/pql_test/runner/coverage_report.py) (summary/JSON presentation) — each independently unit-tested (25 tests) before being wired together.
  - Added the `pql-test code-coverage MODEL_PATH` CLI command: terse and `--verbose` text output, `--format json` with `--output`, and `--min-coverage` for CI gating. Malformed `--output`/`--format` combinations and out-of-range `--min-coverage` fail via Click validation before any XMLA query.
  - Added the `code-coverage` skill (source + packaged, byte-identical) and bumped the package version to `0.1.18` across `pyproject.toml` and all 5 skills, per the existing skill-versioning convention.
  - Added a live regression test ([python/tests/test_coverage_live.py](python/tests/test_coverage_live.py), `@pytest.mark.live`) pinning the exact evidence recorded in the metadata contract, and documented the command in [README.md](README.md) with an explicit dependency-coverage-vs-assertion-coverage caveat.
  - 44 new tests total; full suite at 532 passed / 2 skipped under `pytest -m "not live"`, coverage gate at 82.81% (new modules individually at 96-100%).

### 2026-09-04 — Fix `local/<model_name>` truncation for names containing " - "

- **Fix window-title suffix stripping** — See [tasks/archive/2026-09-04-local-model-name-hyphen-truncation.md](tasks/archive/2026-09-04-local-model-name-hyphen-truncation.md)
  - `get_pbi_files_opened()` in [python/pql_test/runner/local_pbi.py](python/pql_test/runner/local_pbi.py) used `title.rfind(" - ")` to strip the legacy `" - Power BI Desktop"` window-title suffix, unconditionally truncating at the *last* " - " in the title. On newer PBI Desktop builds (no app-name suffix), a model name that itself contains " - " (e.g. "Component 4 - Daily Results Dashboard") was silently truncated to "Component 4", breaking `local/<model_name>` lookups for the real name.
  - Now only strips the suffix via an explicit `str.endswith(" - Power BI Desktop")` check; otherwise the full title is used as the model name.
  - Added regression tests in [python/tests/test_pql_test_runner.py](python/tests/test_pql_test_runner.py): title with no suffix + internal " - " keeps full name; title with suffix + internal " - " strips only the suffix; `resolve_local_xmla_connection_by_name` matches a model name containing " - ".

### 2026-09-02 — Restore ≥ 80% test coverage after monolith removal

- **Coverage restoration** — See [tasks/archive/2026-09-02-coverage-restoration.md](tasks/archive/2026-09-02-coverage-restoration.md)
  - Total coverage jumped from 74.23% → **80.02%** (1,602 / 2,002 statements). The `fail_under=80` gate in [python/pyproject.toml](python/pyproject.toml) now passes cleanly.
  - Added 55 new unit tests across three files. Test count: 422 → 477 passed (14 skipped, all live-network).
  - New tests: [python/tests/auth/test_auth_cli_branches.py](python/tests/auth/test_auth_cli_branches.py) (`cmd_auth_login` flag routing + interactive menu + exception path, `cmd_auth_logout`, `cmd_auth_status`); [python/tests/test_pbi_rest.py](python/tests/test_pbi_rest.py) (workspace/dataset resolution, sovereign-cloud API prefix, dataset existence checks, every MSAL error branch of `_acquire_service_principal_token`); [python/tests/test_adomd_helpers.py](python/tests/test_adomd_helpers.py) (search-path discovery incl. NuGet priority and legacy package id, `.nupkg` download+extract with culture-subdir preservation, hermetic/opt-out env vars, module `__getattr__` bridge).
  - Per-file coverage lifts: `runner/pbi_rest.py` 31% → 95%, `runner/adomd.py` 33% → 91%, `runner/xmla.py` 55% → 92%, `runner/local_pbi.py` 76% → 81%, `cli.py` 59% → 65% (auth subcommands, previously untested).
  - No production logic modified. No `# pragma: no cover` added to real branches. No `fail_under` change.

### 2026-09-02 — Remove runner monolith and restore coverage signal

- **Remove `_runner_monolith.py`** — See [tasks/archive/2026-09-02-remove-runner-monolith.md](tasks/archive/2026-09-02-remove-runner-monolith.md)
  - Deleted [python/pql_test/_runner_monolith.py](python/pql_test/_runner_monolith.py) (781 statements, 0% covered, zero references anywhere in the repo). It was the pre-refactor copy left behind when `runner.py` was split into the `pql_test/runner/` package.
  - Also fixed test-mocking regressions introduced by the runner-refactor: `discovery.py`, `execution.py`, `resolver.py`, and `local_pbi.py` now route cross-module helper calls through `pql_test.runner.<name>` so tests can patch at the package level (matching the pattern already in place for `_execute_dax_query`). See failing tests fix commit.
  - Coverage jumped from **52.4% → 74.23%** — the dead file had been masking the real signal. Reaching the 80% gate is scoped into [tasks/coverage-restoration-epic.md](tasks/coverage-restoration-epic.md); the majority of the remaining gap is in `cli.py` (59%), `runner/adomd.py` (~33%), and `runner/pbi_rest.py` (~31%).
  - Also fixed CI Windows encoding crash in [.github/workflows/pytest.yml](.github/workflows/pytest.yml) — the "Display coverage percentage" step used emoji in `print()` which crashed under cp1252 on `windows-latest`; step now sets `PYTHONIOENCODING=utf-8` and reconfigures stdout/stderr to utf-8.
  - Switched [python/tests/test_skill_packaging.py](python/tests/test_skill_packaging.py) to prefer stdlib `tomllib` (Python 3.11+) with a `tomli` fallback for 3.9/3.10, so the CI test job (Python 3.12) no longer fails on `ModuleNotFoundError: No module named 'tomli'`.

### 2026-09-01 — Lazy-load ADOMD.NET at first XMLA use

- **Lazy-load ADOMD.NET** — See [tasks/archive/2026-09-01-lazy-load-adomd.md](tasks/archive/2026-09-01-lazy-load-adomd.md)
  - Moved the module-scope `import clr` + `clr.AddReference` + `from Microsoft.AnalysisServices.AdomdClient import AdomdConnection` block into a memoized `_ensure_adomd_loaded()` helper called by `has_pyadomd()` and `get_adomd_connection_class()`
  - Added a module-level `__getattr__` in [python/pql_test/runner/adomd.py](python/pql_test/runner/adomd.py) and [python/pql_test/runner/__init__.py](python/pql_test/runner/__init__.py) so `from pql_test.runner import HAS_PYADOMD` still works but only triggers the load when the name is actually bound
  - Migrated `cli._check_prereqs`, `runner/xmla.py`, and `runner/local_pbi.py` from reading `HAS_PYADOMD` at module-import time to calling `has_pyadomd()` at runtime so the reported / gate state reflects the current load outcome
  - Added subprocess regression guard tests in [python/tests/test_adomd_lazy_load.py](python/tests/test_adomd_lazy_load.py) that assert `clr` and `Microsoft.AnalysisServices.AdomdClient` are absent from `sys.modules` after `import pql_test.cli`
  - Cold-start `pql-test --help` dropped from ~5.8s → ~0.43s (13× faster); `check-prereqs` remains eager as its whole purpose is to verify ADOMD.NET loads

### 2026-09-01 — Speed up `local/<model_name>` detection

- **Speed up `local/<model_name>` resolution** — See [tasks/archive/2026-09-01-speed-up-local-pbi-detection.md](tasks/archive/2026-09-01-speed-up-local-pbi-detection.md)
  - Dropped the ADOMD/DAX connectivity probe (`_get_catalog_from_local_port`) from `get_pbi_files_opened` — enumeration no longer opens a MSOLAP session per detected instance
  - Threaded an optional `instances` parameter through `resolve_local_xmla_connection_by_name` and `_format_local_miss_diagnostic` so the CLI enumerates once and shares the result with the resolver, verbose printout, and miss diagnostic
  - Added `connection_pre_resolved` keyword to `run_tests_from_model` so it doesn't re-run `resolve_xmla_connection` when the CLI has already resolved (or attempted to)
  - Cold-start `pql-test run-tests local/<bogus>` dropped from ~5.8s → ~4.7s with no instances open; savings scale linearly with the number of running Power BI Desktop instances

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
- `README.md` and `LICENSE.txt` copied into `python/` so setuptools can find them at build time without restructuring the repo.  Both copies must stay byte-identical to the repo-root originals; [python/tests/test_readme_sync.py](python/tests/test_readme_sync.py) fails the build when they drift.

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
