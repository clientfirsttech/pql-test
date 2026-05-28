# Contributing to pql-test

This guide gets a contributor from a clean Windows machine to a passing local
smoke test in about 15 minutes.

> **Why Windows?** pql-test executes DAX via XMLA through `pyadomd`, which
> requires the Microsoft `ADOMD.NET` client. That assembly is a Windows/.NET
> component. CI uses `windows-latest` runners for the same reason.

---

## Repository layout

```
pql-test/
├── python/                     ← the Python package (canonical source)
│   ├── pql_test/               ← CLI implementation
│   │   ├── cli.py              ← entry point (`pql-test` command)
│   │   ├── runner.py           ← XMLA + test discovery + execution
│   │   └── auth/               ← persistent Fabric-CLI-style auth
│   ├── tests/                  ← pytest suite (mocked + live integration)
│   ├── pyproject.toml          ← single source of truth for version & deps
│   └── .env.example            ← copy to .env for service-mode credentials
├── examples/                   ← three example PBIP models (see "Examples")
├── ai/                         ← aidd skills, commands, scaffolds (not shipped)
├── tasks/                      ← epic/task documents (historical context)
├── .github/workflows/          ← CI: validate-plugin → promptfoo-eval → run-tests-remote
├── plan.md                     ← active work + completed milestones
└── README.md                   ← user-facing documentation
```

There is **no** package source outside `python/`. The CI workflow installs from
`./python` (`pip install ./python`); local installs do the same with `-e`.

---

## Prerequisites

| Requirement | Why | How to install |
|---|---|---|
| Python 3.9+ | Runs the CLI | `winget install Python.Python.3.12` (or [python.org](https://www.python.org/downloads/)) |
| ADOMD.NET client DLL | `pyadomd` loads this at import time | See **ADOMD.NET install** below — required even if you have Power BI Desktop |
| Power BI Desktop | Needed for the local-mode smoke test only | Microsoft Store or [powerbi.microsoft.com](https://powerbi.microsoft.com/desktop/) |
| Service credentials | Needed for service-mode smoke test only | Service principal with `Dataset.Read.All` + Contributor on the workspace |

### ADOMD.NET install (required)

`pip install` brings in the `pyadomd` Python wrapper but **not** the underlying
.NET assembly. Two paths get the DLL onto your machine:

**Option A — NuGet (recommended, mirrors CI):**

```powershell
# Download nuget.exe once
$nugetDir = "$env:USERPROFILE\.nuget"
New-Item -ItemType Directory -Path $nugetDir -Force | Out-Null
Invoke-WebRequest `
  -Uri "https://dist.nuget.org/win-x86-commandline/latest/nuget.exe" `
  -OutFile "$nugetDir\nuget.exe"

# Install the ADOMD.NET client into ~/.nuget/packages/
& "$nugetDir\nuget.exe" install Microsoft.AnalysisServices.AdomdClient.retail.amd64 `
  -OutputDirectory "$nugetDir\packages" -NonInteractive
```

The runner auto-discovers DLLs under `~/.nuget/packages/microsoft.analysisservices.adomdclient.retail.amd64/*/lib/net45/`.

**Option B — Installer-version Power BI Desktop:**

If you install Power BI Desktop from `powerbi.microsoft.com/desktop/` (not the
Microsoft Store), the installer ships `Microsoft.PowerBI.AdomdClient.dll` into
`C:\Program Files\Microsoft Power BI Desktop\bin\` and the runner finds it there.

> **The Microsoft Store version of Power BI Desktop does not satisfy this
> prerequisite.** Its DLLs live inside the ACL-protected
> `C:\Program Files\WindowsApps\` sandbox and are not loadable from Python. If
> you have the Store version, use Option A.

---

## Setup

```powershell
cd python
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pql-test check-prereqs
```

Expected output:

```
Prerequisites check:
  ✅ Python >= 3.9 — Current: 3.12.x
  ✅ pyadomd (ADOMD.NET XMLA client) — pyadomd available
  ✅ msal (Azure AD / service-principal auth) — msal available
  ✅ psutil (local Power BI Desktop detection) — psutil available

All prerequisites met.
```

If `pyadomd` shows ❌, the ADOMD.NET install above did not complete.

---

## Running the test suite

```powershell
# Fast: everything except live integration tests
.\.venv\Scripts\pytest -m "not live"

# Slow: include live tests (needs python/tests/.env)
.\.venv\Scripts\pytest
```

The `live` marker is **deselected by default** via `pyproject.toml`, so a plain
`pytest` invocation runs only the mocked suite.

### Environment-sensitive tests

A handful of CLI tests (under `TestRetrieveTests`, `TestModelIdentifierFormats`,
`TestRlsModel`) call `retrieve-tests` against a temp directory without mocking
out `resolve_xmla_connection`. If Power BI Desktop is running on your machine
with PQL.Assert installed, the auto-detector latches onto it and live discovery
returns a different model's tests — causing those tests to fail. Close Power BI
Desktop before running the suite, or skip them with
`-k "not TestRetrieveTests and not TestModelIdentifierFormats and not TestRlsModel"`.

---

## Local smoke test (Power BI Desktop)

1. Enable the DAX user-defined-functions preview feature **before** opening any
   PBIP model:
   - PBI Desktop → **File → Options and settings → Options**
   - **Preview features** (left panel)
   - Check **User-defined functions** (or **DAX user defined functions** —
     Microsoft has renamed this across versions)
   - **OK**, then **restart Power BI Desktop**

   The example test suites use `DEFINE FUNCTION ... EVALUATE` syntax. Without
   this preview feature enabled, every test fails server-side with:
   `The user-defined functions feature is not supported.`

2. Open `examples/SampleModel.pbip` in PBI Desktop and wait for the report
   canvas to render.

3. Run the smoke test:

   ```powershell
   pql-test run-tests .\examples\SampleModel.SemanticModel --verbose
   ```

   You should see `47 passed, 15 failed, 62 total` (the 15 failures are real
   data-quality issues in `SampleModel`, not pql-test bugs — exit code 1 is
   correct).

---

## Service smoke test (Power BI Premium / Fabric)

1. Copy `python/.env.example` to `python/tests/.env` and fill in:
   ```
   PQL_TENANT_ID=...
   PQL_WORKSPACE_ID=...
   PQL_DATASET_ID=...
   PQL_CLIENT_ID=...
   PQL_CLIENT_SECRET=...
   ```

2. Service principal requirements:
   - **Dataset.Read.All** (or **Dataset.ReadWrite.All**) on Azure AD
   - At least **Contributor** access to the workspace
   - Workspace must be on **Premium capacity or Fabric F-SKU** for XMLA
     read/write access

3. Run:

   ```powershell
   pql-test run-tests "WorkspaceName.SampleModel"
   ```

   Or with explicit GUIDs:

   ```powershell
   pql-test run-tests .\examples\SampleModel.SemanticModel `
     --tenant-id    $env:PQL_TENANT_ID `
     --workspace-id $env:PQL_WORKSPACE_ID `
     --dataset-id   $env:PQL_DATASET_ID `
     --client-id    $env:PQL_CLIENT_ID `
     --client-secret $env:PQL_CLIENT_SECRET
   ```

---

## The `examples/` directory

This repo's `examples/` is a **flat** layout — three PBIP models live
side-by-side rather than each in its own root folder:

```
examples/
├── SampleModel.pbip
├── SampleModel.Report/
├── SampleModel.SemanticModel/
├── RLS_Model.pbip
├── RLS_Model.Report/
├── RLS_Model.SemanticModel/
├── OLS_Model.pbip
├── OLS_Model.Report/
└── OLS_Model.SemanticModel/
```

Pass the specific `.SemanticModel` directory to the CLI — `./examples/` as a
root would be ambiguous between three models and currently returns no tests.

| Model | Purpose | Connection mode |
|---|---|---|
| `SampleModel.SemanticModel` | General-purpose, used by local smoke test | Local or service |
| `RLS_Model.SemanticModel` | Tests Row-Level Security role filters | Service only (local bypasses RLS) |
| `OLS_Model.SemanticModel` | Tests Object-Level Security role permissions | Service only (local bypasses OLS) |

---

## CI pipeline

Three sequential workflows in `.github/workflows/`:

1. **[validate-plugin.yml](.github/workflows/validate-plugin.yml)** — schema
   validation for `plugin.json` + skill directory layout
2. **[promptfoo-eval.yml](.github/workflows/promptfoo-eval.yml)** — evaluates
   each skill's instructions against GitHub Models (gpt-4o-mini)
3. **[run-tests-remote.yml](.github/workflows/run-tests-remote.yml)** — discovers
   every `*.SemanticModel` under `examples/` and runs all `*.Tests.dax` suites
   against the configured Power BI Premium / Fabric workspace

The remote workflow uses these repo secrets: `PQL_TENANT_ID`,
`PQL_WORKSPACE_ID`, `PQL_DATASET_ID`, `PQL_CLIENT_ID`, `PQL_CLIENT_SECRET`,
and the optional `PQL_ENVIRONMENT`.

---

## Pull request checklist

Before opening a PR:

1. `pql-test check-prereqs` — all four prereqs green
2. `pytest -m "not live"` — 252+ tests passing (the 2 known empty-model
   failures are the only acceptable regressions)
3. If you touched `runner.py` — open `examples/SampleModel.pbip` in PBI
   Desktop and run `pql-test run-tests .\examples\SampleModel.SemanticModel`
4. If you touched `cli.py` output — verify it works in a default PowerShell
   session (the CLI forces UTF-8 stdout to avoid `cp1252` `UnicodeEncodeError`
   on emoji output; don't undo that without a replacement)
5. Bump `version` in [python/pyproject.toml](python/pyproject.toml) if shipping
   user-visible changes

---

## Releasing a new version to PyPI

Releases are tag-driven and published via PyPI's trusted-publishing OIDC flow
in [release.yml](.github/workflows/release.yml) — no API tokens are stored
anywhere in the repo.

**One-time setup (already done for the initial release):**
- A "trusted publisher" is registered at
  https://pypi.org/manage/account/publishing/ with this repo
  (`clientfirsttech/pql-test`), workflow name `release.yml`, and environment
  name `pypi`.  An equivalent publisher exists for `testpypi`.
- The GitHub repository has two environments (`pypi`, `testpypi`) configured
  in Settings → Environments.

**Per-release checklist:**

1. Bump `version` in [python/pyproject.toml](python/pyproject.toml) per
   [PEP 440](https://peps.python.org/pep-0440/) / semver.
2. Update the README's "What's New" / a `CHANGELOG.md` if you keep one.
3. Optional rehearsal against TestPyPI before tagging:
   - GitHub → Actions → Publish to PyPI → Run workflow → target `testpypi`
   - Verify install:
     `pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ pql-test==X.Y.Z`
4. Commit + tag + push (the tag must match the pyproject version):
   ```
   git commit -am "release vX.Y.Z"
   git tag vX.Y.Z
   git push && git push --tags
   ```
5. The `release.yml` workflow builds the sdist + wheel, validates them with
   `twine check --strict`, and publishes to PyPI.  Watch the run at
   https://github.com/clientfirsttech/pql-test/actions/workflows/release.yml
6. Smoke-test the published package in a fresh venv:
   ```powershell
   python -m venv $env:TEMP\pql-release-check
   & $env:TEMP\pql-release-check\Scripts\pip install --upgrade pql-test==X.Y.Z
   & $env:TEMP\pql-release-check\Scripts\pql-test --version
   ```

**The tag-vs-pyproject version guard** in `release.yml` will fail the build
if you tag `v0.2.0` while pyproject still says `0.1.5`.  Bump the version in
the same commit as the tag (or as the commit immediately before).

---

## Where to ask

- Linear / GitHub Issues for bug reports
- See [plan.md](plan.md) for current priorities and recently-completed work
- See [tasks/](tasks/) for epic-sized initiatives with full requirements
