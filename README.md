# pql-test — DAX Test Runner for PBIP Models

![Coverage](https://img.shields.io/badge/coverage-77%25-yellow)
[![License](https://img.shields.io/badge/License-BSL--1.1-blue.svg)](LICENSE.txt)

## Run Your Semantic Model Tests from the Command Line

`pql-test` is a command-line tool that discovers and executes the DAX tests
stored inside your Power BI Project (PBIP) semantic models, connecting to
Analysis Services over XMLA. Tests live as `.dax` files alongside your model
and are written with the [PQL.Assert](https://www.pqlint.com/pql-assert)
function family.

Where PQL.Assert gives you the assertions that live inside the model,
`pql-test` is the automation half: it runs those assertions against a local
Power BI Desktop session or a deployed Power BI Premium or Microsoft Fabric
workspace, and reports the results in a form your terminal and your pipeline
can both read.

---

## Table of Contents

- [pql-test — DAX Test Runner for PBIP Models](#pql-test--dax-test-runner-for-pbip-models)
  - [Table of Contents](#table-of-contents)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
  - [Distribution](#distribution)
    - [1. Install the build tool](#1-install-the-build-tool)
    - [2. Build the wheel](#2-build-the-wheel)
    - [3. Install the wheel on another machine](#3-install-the-wheel-on-another-machine)
    - [4. Distribution options](#4-distribution-options)
    - [Updating the version](#updating-the-version)
  - [Model Path Formats](#model-path-formats)
    - [Filesystem path (default)](#filesystem-path-default)
    - [Local model name (`local/<model_name>`)](#local-model-name-localmodel_name)
    - [Fabric service path (`<workspace>.Workspace/<model>.SemanticModel`)](#fabric-service-path-workspaceworkspacemodelsemanticmodel)
  - [Example Models](#example-models)
    - [SampleModel](#samplemodel)
    - [RLS\_Model (Row-Level Security)](#rls_model-row-level-security)
    - [OLS\_Model (Object-Level Security)](#ols_model-object-level-security)
  - [PBIP Model Layout](#pbip-model-layout)
  - [Writing Test Files](#writing-test-files)
    - [Standard test schema (4 columns)](#standard-test-schema-4-columns)
    - [Best-practices test schema (5 columns)](#best-practices-test-schema-5-columns)
    - [Naming convention](#naming-convention)
  - [Authentication](#authentication)
    - [Quick Start](#quick-start)
    - [Authentication Methods](#authentication-methods)
      - [Interactive User Authentication](#interactive-user-authentication)
      - [Service Principal with Secret](#service-principal-with-secret)
      - [Service Principal with Certificate](#service-principal-with-certificate)
      - [Managed Identity (Azure VM/Container)](#managed-identity-azure-vmcontainer)
    - [Credential Priority](#credential-priority)
    - [Secure Storage](#secure-storage)
  - [Commands](#commands)
    - [check-prereqs](#check-prereqs)
    - [retrieve-tests](#retrieve-tests)
    - [retrieve-test](#retrieve-test)
    - [run-tests](#run-tests)
    - [code-coverage](#code-coverage)
  - [Testing against ODCS data contracts](#testing-against-odcs-data-contracts)
  - [Connection Options](#connection-options)
    - [Local Power BI Desktop (auto-detected)](#local-power-bi-desktop-auto-detected)
    - [Remote Power BI Premium / Fabric Workspace](#remote-power-bi-premium--fabric-workspace)
    - [Sovereign / government clouds](#sovereign--government-clouds)
  - [Example Test Suites](#example-test-suites)
    - [Calculations](#calculations)
    - [Data Quality](#data-quality)
    - [Schema](#schema)
    - [Best Practices](#best-practices)
  - [Exit Codes](#exit-codes)
  - [Troubleshooting](#troubleshooting)
    - [`pql-test` is not recognised](#pql-test-is-not-recognised)
    - [`Error: Model path not found`](#error-model-path-not-found)
    - [`No tests found`](#no-tests-found)
    - [`No XMLA connection detected`](#no-xmla-connection-detected)
    - [`msal not installed` / `pythonnet not installed`](#msal-not-installed--pythonnet-not-installed)
    - [`Failed to acquire access token`](#failed-to-acquire-access-token)
    - [Query returned no rows](#query-returned-no-rows)
    - [`Cannot connect to XMLA endpoint`](#cannot-connect-to-xmla-endpoint)

---

## Prerequisites

The only thing you install manually is **Python 3.9+** ([python.org](https://www.python.org/downloads/) — check "Add python.exe to PATH" on Windows). Everything else is handled automatically:

| Requirement | How it's installed |
|---|---|
| Python 3.9+ | **Manual** — install from python.org and ensure it's on PATH |
| pythonnet, msal, azure-identity, keyring, click, python-dotenv, psutil | **Automatic via pip** — pulled in as Python dependencies when you `pip install pql-test` |
| ADOMD.NET assemblies (the .NET XMLA client) | **Automatic on first use** — when no ADOMD.NET install is detected, pql-test downloads the official `Microsoft.AnalysisServices.AdomdClient` NuGet package (~5 MB) from `nuget.org` to `%USERPROFILE%\.pql-test\adomd\` and uses it for every subsequent run. No admin rights, no manual MSI. Set `PQL_TEST_NO_AUTO_INSTALL_ADOMD=1` if you'd rather provide ADOMD yourself. |
| Power BI Desktop *(optional)* | Only needed for `local/<model_name>` mode against a locally-open model. Skip if you only target the service. |

Run the built-in check to verify your environment (this is also when the one-time ADOMD download will fire, if needed):

```powershell
pql-test check-prereqs
```

---

## Installation

### From PyPI (recommended)

Requires Python 3.9+ on Windows (the XMLA driver is ADOMD.NET, a
Windows/.NET component):

```powershell
pip install pql-test
```

Then verify:

```powershell
pql-test --version
pql-test check-prereqs
```

> **Tip:** install into a virtual environment to keep dependencies isolated:
> ```powershell
> python -m venv .venv
> .venv\Scripts\Activate.ps1
> pip install pql-test
> ```

### From source (development)

`pql-test` lives in the `python/` directory of this repository:

```powershell
cd python
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
```

The `-e` flag installs in *editable* mode so source changes are reflected
immediately without reinstalling.

> If you skip activating the venv, use the full path instead:
> `.venv\Scripts\pql-test check-prereqs`

---

## Distribution

Use this process to package `pql-test` as a wheel file and deploy it to other
machines or pipelines without needing a copy of this repository.

### 1. Install the build tool

```powershell
pip install build
```

### 2. Build the wheel

Run from the `python/` directory:

```powershell
cd python
python -m build
```

This produces two artefacts in `python/dist/`:

```
dist/
  pql_test-0.1.0-py3-none-any.whl   ← installable wheel
  pql_test-0.1.0.tar.gz             ← source distribution
```

The wheel file name encodes the version from `pyproject.toml`.
Update `version` there before building a new release.

### 3. Install the wheel on another machine

Copy the `.whl` file to the target machine, then:

```powershell
pip install pql_test-0.1.0-py3-none-any.whl
```

The `pql-test` command is then available on `PATH` (within whichever Python
environment the wheel was installed into):

```powershell
pql-test --version
pql-test check-prereqs
```

> **Tip:** Install into a dedicated virtual environment on the target machine
> to keep dependencies isolated:
> ```powershell
> python -m venv .venv
> .venv\Scripts\Activate.ps1
> pip install pql_test-0.1.0-py3-none-any.whl
> ```

### 4. Distribution options

| Method | How |
|---|---|
| **PyPI** (primary) | Published by the release workflow when a `vX.Y.Z` tag is pushed; consumers just `pip install pql-test` |
| **Direct file share** | Copy the `.whl` to the target machine and `pip install` it |
| **GitHub Release** | Attach the `.whl` as a release asset; install with `pip install <asset-url>` |
| **Private PyPI feed** (e.g. Azure Artifacts) | `pip install twine` then `twine upload --repository-url <feed-url> dist/*`; consumers install with `pip install pql-test --index-url <feed-url>` |

### Updating the version

[`python/pyproject.toml`](python/pyproject.toml) is the **single source of truth** for the version.
The CLI reads it at runtime via `importlib.metadata`, so there is no other file to update.

Bump `version` in `pyproject.toml` before each new build:

```toml
[project]
name = "pql-test"
version = "0.2.0"   # ← increment here
```

Then reinstall in your local venv (so `pql-test --version` reflects the change) and rebuild the wheel:

```powershell
pip install -e .          # refresh local install
python -m build           # produce new dist/pql_test-0.2.0-py3-none-any.whl
```

---

## Model Path Formats

The `MODEL_PATH` argument accepted by `retrieve-tests`, `retrieve-test`, and
`run-tests` supports these formats:

| Format | Mode | Description |
|---|---|---|
| `<workspace>.Workspace/<model>.SemanticModel` | Service | **Canonical Fabric service path** — connect to a remote workspace by display names. Matches Fabric's own filesystem layout. |
| `local/<model_name>` | Local | Connect to a locally-open Power BI Desktop instance by model name |
| `<filesystem_path>` | File / local | Traditional PBIP root directory (default) |

> **Quoting:** if the workspace or model name contains spaces or other shell
> metacharacters (e.g. parentheses), wrap the **entire** `MODEL_PATH` argument
> in double quotes so your shell passes it as one argument:
>
> ```bash
> pql-test retrieve-tests "local/OLS_Model (1)"
> pql-test run-tests "My Workspace.Workspace/Sales Model.SemanticModel"
> ```
>
> Without quotes the shell splits `local/OLS_Model (1)` into two arguments and
> the CLI never sees the full name.

### Filesystem path (default)

Pass the PBIP root directory, the `.SemanticModel` sub-folder, or the `.pbip`
file directly. Tests are discovered by scanning `DAXQueries/` for `*.Tests.dax`
files. When a live connection is available (`local/<model_name>` or
`--tenant-id`), tests are also queried from the model via
`PQL.Assert.RetrieveTestsV2()`.

```bash
pql-test run-tests ./examples/SampleModel.SemanticModel
```

> Note: this repo's `examples/` directory holds three flat PBIP layouts side-by-side
> (`SampleModel.SemanticModel/`, `RLS_Model.SemanticModel/`, `OLS_Model.SemanticModel/`
> with their respective `.pbip` files). Pass the specific `.SemanticModel` directory
> rather than `./examples/` as the root.

### Local model name (`local/<model_name>`)

Use `local/<model_name>` to connect to a locally-open Power BI Desktop
instance **by model name** without providing a local file path. This is
useful when the test `.dax` files may not exist locally yet (e.g. tests are
defined directly in the model's `functions.tmdl`). Test discovery uses
`PQL.Assert.RetrieveTestsV2()` via the live XMLA connection.

```bash
# Open SampleModel in Power BI Desktop first, then:
pql-test retrieve-tests local/SampleModel
pql-test run-tests local/SampleModel
```

### Fabric service path (`<workspace>.Workspace/<model>.SemanticModel`)

The canonical service-path syntax mirrors Fabric's own filesystem layout —
workspaces appear on disk as `.Workspace/` directories and semantic models as
`.SemanticModel/` directories, so the model identifier you'd type into a
shell matches the path you'd see if you exported the workspace.

```
MyWorkspace.Workspace/MyModel.SemanticModel
└─ workspace name ─┘ └── model name ──┘
```

This connects directly via XMLA using the workspace and model **display
names**, bypassing the GUID-based REST API lookup.

**With persistent authentication** (recommended):

```bash
# Log in once
pql-test auth login

# Then run commands without credential flags
pql-test retrieve-tests "MyWorkspace.Workspace/MySemanticModel.SemanticModel"
pql-test run-tests "MyWorkspace.Workspace/MySemanticModel.SemanticModel"
```

**Service principal** (credentials via flags or `PQL_*` env vars — for CI/CD):

```bash
pql-test run-tests "MyWorkspace.Workspace/MySemanticModel.SemanticModel" \
  --tenant-id  $PQL_TENANT_ID \
  --client-id  $PQL_CLIENT_ID \
  --client-secret $PQL_CLIENT_SECRET
```

> **Note:** When `MODEL_PATH` matches the `<workspace>.Workspace/<model>.SemanticModel`
> shape and does not exist as a real directory on the local filesystem, it
> is interpreted as a Fabric service path. A real on-disk directory at the
> same string takes precedence and is treated as a filesystem path.

---

## Example Models

This repository includes three example PBIP semantic models in the `examples/` directory for testing and demonstration purposes:

### SampleModel

**Path:** `examples/SampleModel.SemanticModel`  
**Purpose:** General-purpose test model demonstrating comprehensive test coverage  
**Dataset ID:** Set via `PQL_DATASET_ID` environment variable  

Contains test suites for:
- `BestPractices.ANY.Tests.dax` — PQL best-practice rule checks (5-column schema)
- `Calculations.DEV.Tests.dax` — Measure / calculation correctness tests
- `DataQuality.DEV.Tests.dax` — Row counts, null checks, uniqueness, referential integrity
- `Schema.DEV.Tests.dax` — Table / column / relationship existence

**Usage:**
```bash
pql-test run-tests ./examples/SampleModel.SemanticModel
pql-test run-tests local/SampleModel
```

### RLS_Model (Row-Level Security)

**Path:** `examples/RLS_Model.SemanticModel`  
**Purpose:** Demonstrates testing Row-Level Security (RLS) role filters  
**Dataset ID:** Set via `PQL_DATASET_ID_RLS` environment variable  

Contains test suites for:
- `RLS.ANY.Tests.dax` — Validates that RLS role filters restrict data access correctly

**Usage:**
```bash
pql-test run-tests ./examples/RLS_Model.SemanticModel \
  --tenant-id $PQL_TENANT_ID \
  --workspace-id $PQL_WORKSPACE_ID \
  --dataset-id $PQL_DATASET_ID_RLS \
  --client-id $PQL_CLIENT_ID \
  --client-secret $PQL_CLIENT_SECRET
```

### OLS_Model (Object-Level Security)

**Path:** `examples/OLS_Model.SemanticModel`  
**Purpose:** Demonstrates testing Object-Level Security (OLS) role permissions  
**Dataset ID:** Set via `PQL_DATASET_ID_OLS` environment variable  

Contains test suites for:
- `OLS Admin.dax` — Tests administrative role permissions (full access)
- `OLS_West.dax` — Tests restricted role permissions (regional data access)

**Usage:**
```bash
pql-test run-tests ./examples/OLS_Model.SemanticModel \
  --tenant-id $PQL_TENANT_ID \
  --workspace-id $PQL_WORKSPACE_ID \
  --dataset-id $PQL_DATASET_ID_OLS \
  --client-id $PQL_CLIENT_ID \
  --client-secret $PQL_CLIENT_SECRET
```

> **Note:** RLS and OLS models require remote Power BI Premium / Fabric workspace connections to test security roles effectively, as local Power BI Desktop sessions bypass security filters.

---

## PBIP Model Layout

`pql-test` expects a standard [PBIP](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-overview)
directory structure. Test files are placed in the `DAXQueries/` folder of the
`*.SemanticModel` directory:

```
MyModel/                               ← modelPath (passed to CLI)
├── MyModel.pbip                       ← triggers local PBI Desktop auto-detection
├── MyModel.SemanticModel/
│   ├── definition/
│   │   └── ...
│   └── DAXQueries/
│       ├── Calculations.DEV.Tests.dax ← picked up by retrieve-tests / run-tests
│       ├── DataQuality.DEV.Tests.dax
│       ├── Schema.DEV.Tests.dax
│       └── BestPractices.ANY.Tests.dax
└── MyModel.Report/
    └── ...
```

Any file whose name ends with `.Tests.dax` inside `DAXQueries/` is treated as
a test suite.

---

## Writing Test Files

Each test file defines a **DAX function** that returns a table of assertion
results, then immediately calls it with `EVALUATE`.

### Standard test schema (4 columns)

```dax
DEFINE
    FUNCTION Calculations.DEV.Tests = () =>
    UNION (
        PQL.Assert.ShouldEqual(
            "Calculations: Number of Characters equals COUNTROWS",
            [Number of Characters],
            COUNTROWS('MarvelFact')
        ),
        PQL.Assert.ShouldBeGreaterThan(
            "Calculations: Number of Characters is greater than zero",
            0,
            [Number of Characters]
        )
    )

EVALUATE Calculations.DEV.Tests()
```

The `EVALUATE` expression must return a table with exactly four columns:

| Column | Type | Description |
|---|---|---|
| `[TestName]` | Text | Name identifying the individual assertion |
| `[Expected]` | Any | The expected value |
| `[Actual]` | Any | The value returned by the model |
| `[Passed]` | Boolean / 0-1 | `TRUE` / `1` when the assertion passes |

### Best-practices test schema (5 columns)

Best-practices tests use the `PQL.Assert.BP.*` functions, which return an
extra `[RuleDescription]` column. **These must be kept in a separate file**
and must never be `UNION`-ed with standard 4-column tests.

```dax
// NOTE: PQL.Assert.BP functions return a 5-column schema
// (TestName, Expected, Actual, Passed, RuleDescription).
// This MUST be kept in a separate runner — never UNION with standard 4-column test results.

DEFINE
    FUNCTION BestPractices.ANY.Tests = () =>
    UNION (
        PQL.Assert.BP.CheckErrorPrevention(),
        PQL.Assert.BP.CheckFormatting(),
        PQL.Assert.BP.CheckDAXExpressions(),
        PQL.Assert.BP.CheckMaintenance(),
        PQL.Assert.BP.CheckPerformance()
    )

EVALUATE BestPractices.ANY.Tests()
```

### Naming convention

| File name pattern | Purpose |
|---|---|
| `Calculations.DEV.Tests.dax` | Measure / calculation correctness tests |
| `DataQuality.DEV.Tests.dax` | Row counts, null checks, uniqueness, referential integrity |
| `Schema.DEV.Tests.dax` | Table / column / relationship existence |
| `BestPractices.ANY.Tests.dax` | PQL best-practice rule checks (5-column schema) |

The `DEV` / `ANY` segment indicates the environment scope. By default
`pql-test` treats all `*.Tests.dax` files equally; pass `--env <ENV>` to
`run-tests` / `retrieve-tests` to restrict discovery and execution to one
environment's suites (see
[Environment-specific test discovery](#environment-specific-test-discovery---env)).

---

## Authentication

`pql-test` supports persistent authentication similar to Fabric CLI, eliminating the need to pass credentials on every command.

### Quick Start

```powershell
# Log in once - interactive browser prompt
pql-test auth login

# Or with service principal
pql-test auth login -u <client-id> -p <secret> --tenant <tenant-id>

# Now run tests without credential flags
pql-test run-tests "MyWorkspace.Workspace/MySemanticModel.SemanticModel"

# Or with GUID-based connection
pql-test run-tests ./examples/SampleModel.SemanticModel --workspace-id <id> --dataset-id <id>

# Check authentication status
pql-test auth status

# Log out when done
pql-test auth logout
```

### Authentication Methods

#### Interactive User Authentication

Browser-based Azure AD login (no tenant ID required):

```powershell
pql-test auth login
```

This opens a browser window for you to sign in with your Azure AD credentials. Azure Identity automatically discovers your tenant.

#### Service Principal with Secret

```powershell
pql-test auth login -u <client-id> -p <secret> --tenant <tenant-id>
```

#### Service Principal with Certificate

```powershell
# PEM certificate
pql-test auth login -u <client-id> --certificate cert.pem --tenant <tenant-id>

# P12/PFX with password
pql-test auth login -u <client-id> --certificate cert.p12 -p <cert-password> --tenant <tenant-id>
```

#### Managed Identity (Azure VM/Container)

```powershell
# System-assigned
pql-test auth login --identity

# User-assigned
pql-test auth login --identity -u <client-id>
```

### Credential Priority

When running commands like `run-tests`, credentials are resolved in this order:

1. **CLI flags** (`--tenant-id`, `--client-id`, `--client-secret`) — Highest priority
2. **Environment variables** (`PQL_TENANT_ID`, `PQL_CLIENT_ID`, `PQL_CLIENT_SECRET`)
3. **Stored credentials** (from `pql-test auth login`) — Lowest priority

This ensures backward compatibility with existing CI/CD pipelines while providing a better developer experience for interactive use.

### Secure Storage

Credentials are stored securely using the platform keyring:
- **Windows**: Windows Credential Manager
- **macOS**: Keychain
- **Linux**: Secret Service API (GNOME Keyring, KWallet)

---

## Security Considerations

### Service Principal Permissions

**⚠️ Security Warning**: Over-permissioned service principals create security risks. Follow least-privilege principles.

**Recommended minimum permissions**:
- **Azure AD API**: `Dataset.Read.All` (application permission)
- **Workspace Access**: **Viewer** (read-only) or **Contributor** (read + refresh)

❌ **Avoid**: `Workspace.ReadWrite.All`, tenant admin roles, or workspace Admin access unless specifically required.

See [CONTRIBUTING.md](CONTRIBUTING.md#service-principal-setup-least-privilege) for complete setup guide with security best practices.

### RLS/OLS Security Model

#### Row-Level Security (RLS) Testing

Tests can impersonate users to validate RLS rules using the `ImpersonateUser:` annotation:

```dax
// File: RLS.ANY.Tests.dax
// ImpersonateUser: user@example.com

DEFINE
  FUNCTION RLS.RegionFilter.Test() = ...
EVALUATE
  RLS.RegionFilter.Test()
```

**Security Implications**:
- **Local connections**: `EffectiveUserName` parameter is ignored (not supported by local Analysis Services)
- **Service connections**: XMLA connection string includes `EffectiveUserName=<email>`
- **⚠️ Warning**: The calling identity (your user or service principal) must have **workspace Admin** permissions to use `EffectiveUserName`
- **Risk**: Malicious test files can impersonate any user email—there is no validation that the email corresponds to a real Azure AD principal

**Recommended Practice**:
- Use `ImpersonateRole:` instead when possible (see OLS section)
- Restrict test file authoring to trusted developers
- Run tests in isolated environments (separate dev/test workspaces)
- Future enhancement: Configuration-based allowlist for approved impersonation emails

#### Object-Level Security (OLS) Testing

Tests can assume roles to validate OLS rules using the `ImpersonateRole:` annotation:

```dax
// File: OLS.ANY.Tests.dax
// ImpersonateRole: RegionalManager

DEFINE
  FUNCTION OLS.HiddenTables.Test() = ...
EVALUATE
  OLS.HiddenTables.Test()
```

**Security Implications**:
- **Preferred over `EffectiveUserName`**: Works for both local and service connections
- **Service principals**: Can be granted role membership (no Admin required)
- **Validation**: Analysis Services validates that the role exists in the model
- **⚠️ Risk**: Malicious test files can specify any role name—access is granted if role exists

**Recommended Practice**:
- Add service principals directly to model roles (no `EffectiveUserName` needed)
- Document which roles should be tested in your test plan
- Future enhancement: Configuration-based allowlist for approved role names

#### Security Best Practices for RLS/OLS Testing

✅ **DO**:
- Use `ImpersonateRole:` instead of `ImpersonateUser:` when possible
- Test RLS/OLS rules in non-production environments
- Grant service principals only the roles they need to test
- Review test files for unexpected impersonation annotations
- Use separate datasets for RLS/OLS testing (don't test against production)

❌ **DON'T**:
- Grant workspace Admin to service principals just for testing
- Use production datasets for RLS/OLS test execution
- Share RLS test credentials (each developer should use their own identity)
- Assume `EffectiveUserName` validates email addresses (it doesn't)

**Threat Model**: See [docs/security-threat-model.md](docs/security-threat-model.md) for complete security analysis, including STRIDE assessment of RLS/OLS impersonation controls.

### Secret Rotation

**Best Practice**: Rotate service principal secrets every 90 days.

```powershell
# When secret approaches expiry:
# 1. Create new secret in Azure Portal
# 2. Update stored credential
pql-test auth login -u <client-id> -p <new-secret> --tenant <tenant-id>

# 3. Verify new secret works
pql-test auth status

# 4. Revoke old secret in Azure Portal
```

Set calendar reminders 1 week before expiry to avoid CI/CD outages.

---

## Commands

All commands are run from within the `python/` directory with the virtual
environment active (or prefixed with `.venv\Scripts\`).

### check-prereqs

Verify that all prerequisites are installed and accessible on `PATH`.

```bash
pql-test check-prereqs
```

**Example output:**

```
Prerequisites check:
  ✅ Python >= 3.9 — Current: 3.12.6
  ✅ pyadomd (ADOMD.NET XMLA client) — pyadomd available
  ✅ msal (Azure AD / service-principal auth) — msal available
  ✅ psutil (local Power BI Desktop detection) — psutil available

All prerequisites met.
```

---

### retrieve-tests

List all DAX test suites discovered in a PBIP model.

```bash
pql-test retrieve-tests <modelPath> [--env <environment>] [--verbose]
```

**Arguments:**

| Argument | Required | Description |
|---|---|---|
| `<modelPath>` | ✅ | Model identifier — filesystem path, `local/<name>`, or `workspace.model` (see [Model Path Formats](#model-path-formats)) |
| `--env <environment>` | ❌ | Only list suites for this environment (e.g. `DEV`, `PROD`, `ANY`, `BKUP`; or set `PQL_TEST_ENV`) — see [Environment-specific test discovery](#environment-specific-test-discovery---env) |
| `--verbose`, `-v` | ❌ | Also print file paths and connection info |

**Example:**

```bash
pql-test retrieve-tests ./examples/SampleModel.SemanticModel
```

```
Found 4 DAX test suite(s):

  • BestPractices.ANY.Tests
  • Calculations.DEV.Tests
  • DataQuality.DEV.Tests
  • Schema.DEV.Tests
```

**With `--verbose`:**

```bash
pql-test retrieve-tests ./examples/SampleModel.SemanticModel --verbose
```

```
Found 4 DAX test suite(s):

  • BestPractices.ANY.Tests
    File: /examples/SampleModel.SemanticModel/DAXQueries/BestPractices.ANY.Tests.dax
  • Calculations.DEV.Tests
    DAX function: Calcs.DEV.Tests
    File: /examples/SampleModel.SemanticModel/DAXQueries/Calculations.DEV.Tests.dax
  ...

Connection: none detected — open the model in Power BI Desktop or supply
  --tenant-id, --workspace-id, --dataset-id to run tests.
```

**Filter to a single suite using `--test`:**

```bash
pql-test retrieve-tests ./examples/SampleModel.SemanticModel --test "Calculations.DEV.Tests"
```

**Filter to one environment's suites using `--env`:**

```bash
pql-test retrieve-tests ./examples/SampleModel.SemanticModel --env DEV
```

**Using `local/<model_name>` (no local file path needed):**

```bash
# Open SampleModel in Power BI Desktop first
pql-test retrieve-tests local/SampleModel
```

**Using the Fabric service path:**

```bash
pql-test retrieve-tests "MyWorkspace.Workspace/MySemanticModel.SemanticModel" \
  --tenant-id $PQL_TENANT_ID --client-id $PQL_CLIENT_ID --client-secret $PQL_CLIENT_SECRET
```

---

### retrieve-test

Show a specific test suite by name (case-insensitive).

```bash
pql-test retrieve-test <modelPath> <name> [--verbose]
```

**Arguments:**

| Argument | Required | Description |
|---|---|---|
| `<modelPath>` | ✅ | Model identifier — filesystem path, `local/<name>`, or `workspace.model` (see [Model Path Formats](#model-path-formats)) |
| `<name>` | ✅ | Test suite name (file stem without `.dax`) |
| `--verbose`, `-v` | ❌ | Also print the full DAX source |

**Example:**

```bash
pql-test retrieve-test ./examples/SampleModel.SemanticModel "DataQuality.DEV.Tests"
```

```
Found 1 DAX test suite(s):

  • DataQuality.DEV.Tests
```

**With `--verbose`** (shows the full DAX source):

```bash
pql-test retrieve-test ./examples/SampleModel.SemanticModel "DataQuality.DEV.Tests" --verbose
```

---

### run-tests

Execute DAX test suites in a PBIP model via XMLA and report pass/fail results.

```bash
pql-test run-tests <modelPath> [--test <name>] [--env <environment>] [--verbose]
                               [--output <file>]
                               [--log-format {azuredevops,github}]
                               [--tenant-id <id>]
                               [--workspace-id <id>]
                               [--dataset-id <id>]
```

**Arguments:**

| Argument | Required | Description |
|---|---|---|
| `<modelPath>` | ✅ | Model identifier — filesystem path, `local/<name>`, or `workspace.model` (see [Model Path Formats](#model-path-formats)) |
| `--test <name>` | ❌ | Run only the named test suite |
| `--env <environment>` | ❌ | Run only suites for this environment (e.g. `DEV`, `PROD`, `ANY`, `BKUP`; or set `PQL_TEST_ENV`) — see [Environment-specific test discovery](#environment-specific-test-discovery---env) |
| `--verbose`, `-v` | ❌ | Show message and duration for every result (not just failures) |
| `--output <file>` | ❌ | Write full JSON results to `<file>` in addition to stdout output |
| `--log-format <fmt>` | ❌ | Emit CI-native annotations: `azuredevops` or `github` |
| `--tenant-id <id>` | ❌ | Azure AD tenant ID (required for remote XMLA; or set `PQL_TENANT_ID`) |
| `--workspace-id <id>` | ❌ | Power BI workspace GUID (required for remote XMLA; or set `PQL_WORKSPACE_ID`) |
| `--dataset-id <id>` | ❌ | Dataset / semantic model GUID (or set `PQL_DATASET_ID`) |
| `--client-id <id>` | ❌ | Service-principal client ID (or set `PQL_CLIENT_ID`) |
| `--client-secret <secret>` | ❌ | Service-principal client secret (or set `PQL_CLIENT_SECRET`) |

**Run all suites against a locally-open Power BI Desktop model:**

```bash
pql-test run-tests ./examples/SampleModel.SemanticModel
```

**Run using `local/<model_name>` (no local file path needed):**

```bash
# Open SampleModel in Power BI Desktop first
pql-test run-tests local/SampleModel
```

**Run all suites against a remote Power BI Premium / Fabric workspace:**

```bash
pql-test run-tests ./examples/SampleModel.SemanticModel \
  --tenant-id  00000000-0000-0000-0000-000000000000 \
  --workspace-id 11111111-1111-1111-1111-111111111111 \
  --dataset-id   22222222-2222-2222-2222-222222222222
```

**Run using the Fabric service path (no local file path or GUIDs needed):**

```bash
pql-test run-tests "MyWorkspace.Workspace/MySemanticModel.SemanticModel" \
  --tenant-id  $PQL_TENANT_ID \
  --client-id  $PQL_CLIENT_ID \
  --client-secret $PQL_CLIENT_SECRET
```

**Run a single named test suite:**

```bash
pql-test run-tests ./examples/SampleModel.SemanticModel --test "Calculations.DEV.Tests"
```

#### Environment-specific test discovery (`--env`)

A semantic model stores *all* of its test suites, but not every suite is meant
to run against every workspace. Suites encode their target environment as the
second-to-last segment of the function name — `<Suite>.<ENV>.Tests`:

```
Calculations.DEV.Tests.dax    ← discovered with --env DEV
DataQuality.DEV.Tests.dax     ← discovered with --env DEV
Schema.DEV.Tests.dax          ← discovered with --env DEV
BestPractices.ANY.Tests.dax   ← discovered with --env ANY
ColumnTests.BKUP.Tests.dax    ← discovered with --env BKUP
```

`--env <ENV>` restricts discovery and execution to that environment's suites,
so you no longer have to retrieve all tests, parse out the ones you want, and
run them one at a time with `--test`:

```bash
pql-test run-tests ./examples/SampleModel.SemanticModel --env DEV
pql-test run-tests "MyWorkspace.Workspace/MySemanticModel.SemanticModel" --env PROD
pql-test run-tests "Backups.Workspace/MySemanticModel.SemanticModel" --env BKUP
```

How it filters:

- **Live discovery** (local Desktop, `local/<name>`, or service connection):
  the environment is passed straight to the model's UDF as
  `PQL.Assert.RetrieveTestsV2("<ENV>")`, so the model decides which suites
  match. If the installed `RetrieveTestsV2` doesn't accept an argument yet,
  the CLI falls back to parameterless discovery and filters client-side by the
  naming convention.
- **Offline file scan**: `DAXQueries/*.Tests.dax` files are matched against
  the `<Suite>.<ENV>.Tests` convention.

Matching is case-insensitive and **exact** — `ANY` is an ordinary environment
token, not a wildcard, so `--env DEV` does not include `*.ANY.Tests` suites
(run them with a separate `--env ANY` invocation). Suites without an
environment segment (e.g. `Calcs.Tests`) never match an `--env` filter.

> **Note:** the Power BI *cloud* (`Public`, `USGov`, `China`, …) is not a
> per-command flag. It comes from the credential stored by
> `pql-test auth login --environment <cloud>`, or from the `PQL_ENVIRONMENT`
> env var when explicit service-principal credentials are supplied.

**Save JSON results to a file while still printing to the console:**

```bash
pql-test run-tests ./examples/SampleModel.SemanticModel --output results.json
```

The JSON file contains `passed`, `failed`, `skipped`, `total`, and a `results` array with one row per assertion. Each row has:
- `test_name`: the assertion's `TestName`, or the suite name when the whole suite failed to run;
- `suite_name`: the test function, e.g. `Calculations.DEV.Tests`;
- `expected` and `actual`;
- `passed`, `skipped`, `error`, and `duration_ms`.

Example structure:

```json
{
  "model_path": "/examples/SampleModel.SemanticModel",
  "passed": 5,
  "failed": 1,
  "skipped": 0,
  "total": 6,
  "results": [
    { "test_name": "Calculations: X equals Y", "expected": "5", "actual": "7",
      "passed": false, "suite_name": "Calculations.DEV.Tests", "skipped": false,
      "error": null, "duration_ms": 12.3 }
  ]
}
```

**Emit Azure DevOps pipeline annotations:**

```bash
pql-test run-tests ./examples/SampleModel.SemanticModel --log-format azuredevops
```

This emits `##[group]` / `##[endgroup]` / `##[error]` / `##[warning]` and a final `##vso[task.complete result=Failed|Succeeded;]` command, making failures visible directly in the Azure DevOps pipeline log.

**Emit GitHub Actions workflow annotations:**

```bash
pql-test run-tests ./examples/SampleModel.SemanticModel --log-format github
```

This emits `::group::` / `::endgroup::` / `::error::` / `::warning::` / `::notice::` commands, surfacing failures as annotations on the GitHub Actions summary page.

**Combine `--log-format` with `--output` in CI pipelines:**

```powershell
pql-test run-tests ./examples/SampleModel.SemanticModel `
  --log-format azuredevops `
  --output pql-test-results.json `
  --tenant-id  $env:PQL_TENANT_ID `
  --workspace-id $env:PQL_WORKSPACE_ID `
  --dataset-id   $env:PQL_DATASET_ID `
  --client-id    $env:PQL_CLIENT_ID `
  --client-secret $env:PQL_CLIENT_SECRET
```

**Example output (all passing, default format):**

```
Local XMLA connection: localhost:50001 / catalog:

========================== test session starts ===========================
model: /examples/SampleModel.SemanticModel

......

===================== 6 passed, 0 failed, 6 total =======================
```

**Example output (with failures):**

```
XMLA connection: powerbi://api.powerbi.com/v1.0/myTenant/myWorkspace / catalog: 22222...

========================== test session starts ===========================
model: /examples/SampleModel.SemanticModel

..FF..

-------------------------------- FAILURES --------------------------------

  FAILED Calculations: Running Total of Character Appearances is non-negative
  Expected: 0 | Actual: -5

  FAILED Calculations: Number of Characters Title By Date starts with correct prefix
  Expected: Number of Characters that first appeared  | Actual: Characters first appeared

==================== 4 passed, 2 failed, 6 total ========================
```

**No XMLA connection detected:**

```
Warning: No XMLA connection detected. Tests will be reported as skipped.

========================== test session starts ===========================
model: /examples/SampleModel.SemanticModel

ssss

------------------------------ warnings summary --------------------------
  WARN No XMLA connection detected. Tests will be reported as skipped. ...

==================== 0 passed, 0 failed, 4 total, 4 warnings ===========
```

---

### code-coverage

Report which calculated columns, measures, tables, relationships, partitions, and roles have **direct test-UDF evidence** — a discovered DAX test that provably touches them — and which don't, with AI-ready hints for the gaps. See [docs/code-coverage-explained.md](docs/code-coverage-explained.md) for a one-page walkthrough with diagrams.

```bash
pql-test code-coverage <modelPath> [--verbose] [--format {text,json}] [--output <file>]
                                   [--min-coverage <percent>]
                                   [--tenant-id <id>] [--workspace-id <id>] [--dataset-id <id>]
```

**Arguments:**

| Argument | Required | Description |
|---|---|---|
| `<modelPath>` | ✅ | Model identifier — filesystem path, `local/<name>`, or `<workspace>.Workspace/<semantic_model>.SemanticModel` (see [Model Path Formats](#model-path-formats)) |
| `--verbose`, `-v` | ❌ | List covered objects with their direct test-UDF evidence and uncovered objects with AI-ready test targets |
| `--format <fmt>` | ❌ | `text` (default, human-readable) or `json` (stable report shape) |
| `--output <file>` | ❌ | Write the JSON report to `<file>`. Requires `--format json` — otherwise fails as a usage error before any XMLA query |
| `--min-coverage <percent>` | ❌ | Exit `1` when overall eligible coverage is below `<percent>` (0-100); prints `Required coverage of N% reached` when met (like pytest-cov's `--cov-fail-under`). Also switches the report colors to pass/fail against the threshold. A malformed or out-of-range value fails before any XMLA query |
| `--tenant-id <id>` | ❌ | Azure AD tenant ID (or set `PQL_TENANT_ID`) |
| `--workspace-id <id>` | ❌ | Power BI workspace GUID (or set `PQL_WORKSPACE_ID`) |
| `--dataset-id <id>` | ❌ | Dataset / semantic model GUID (or set `PQL_DATASET_ID`) |
| `--client-id <id>` | ❌ | Service-principal client ID (or set `PQL_CLIENT_ID`) |
| `--client-secret <secret>` | ❌ | Service-principal client secret (or set `PQL_CLIENT_SECRET`) |

**What "covered" means — and what it doesn't**

This is **dependency coverage**, not **assertion coverage**. An object counts as covered when a discovered test UDF has direct, verifiable evidence linking it to that object — never inferred from transitive dependencies, and never presented as covered just because *some* test happens to touch it indirectly through a PQL.Assert helper. But direct evidence only proves a test *references* the object, not that the test's assertion meaningfully validates its behavior: a test that checks a table has more than zero rows and a test that validates every business rule on that table both count as "covered" the same way. Treat a low score as "nothing here has been tested at all" and a high score as "these objects are at least referenced by a test" — not as a correctness guarantee. See [tasks/direct-udf-code-coverage-metadata-contract.md](tasks/direct-udf-code-coverage-metadata-contract.md) for the full verified evidence contract per category, including:

- **Tables, calculated columns, measures** — covered via a direct `INFO.CALCDEPENDENCY()` edge from a discovered test UDF. The strongest evidence category: the DAX engine itself reports the reference.
- **Relationships** — covered only when a test UDF's own DAX expression text contains a `PQL.Assert.Relationship.ShouldExist(...)` call matching a real relationship. `INFO.CALCDEPENDENCY()` can't see this at all, because the helper takes the relationship as string arguments, not a compiled reference — so this is parsed out of the expression text instead.
- **Roles** — covered only when a test UDF carries a `PQLAssert_RoleName` annotation matching a real role (the same annotation `PQL.Assert.RetrieveTestsV2()` already surfaces for RLS impersonation). Role application happens through the XMLA connection string, not a DAX dependency, so this is annotation-driven rather than edge-driven.
- **Partitions** — always excluded, never counted covered or uncovered. No `PQL.Assert` helper targets partitions at all, so there is no assertion surface to have evidence from.

**Terse report:**

```bash
pql-test code-coverage local/SampleModel
```

```
Local XMLA connection: localhost:56622 / catalog:

======================= coverage session starts ========================
model: local/SampleModel

Tests discovered: 4

Overall: 10/23 covered (43.48%)

By category:
┌──────────────┬─────────┬──────────┬──────────────┐
│ Category     │ Covered │ Eligible │            % │
├──────────────┼─────────┼──────────┼──────────────┤
│ CALC_COLUMN  │       0 │        6 │         0.0% │
│ MEASURE      │       3 │        6 │        50.0% │
│ PARTITION    │       - │        - │ excluded (8) │
│ RELATIONSHIP │       3 │        3 │       100.0% │
│ TABLE        │       4 │        8 │        50.0% │
└──────────────┴─────────┴──────────┴──────────────┘
```

The overall line and each category's percentage are colored with the same
PASS/FAIL/SKIP (green/red/yellow) vocabulary `run-tests` uses (see
[CLI Output Conventions](CONTRIBUTING.md#cli-output-conventions)):

| Mode | Green | Yellow | Red |
|---|---|---|---|
| No `--min-coverage` (default watermarks, same as Istanbul/nyc/Jest) | ≥ 80% | 50% – < 80% | < 50% |
| `--min-coverage N` | ≥ N | — | < N |

With a threshold the colors match the exit code: anything red is what's
holding the build below the gate.

**Verbose report** (adds per-object evidence and AI-ready gap hints):

```bash
pql-test code-coverage local/SampleModel --verbose
```

**JSON report for CI artifacts or an AI agent to read:**

```bash
pql-test code-coverage local/SampleModel --format json --output coverage.json
```

**Fail CI when overall eligible coverage drops below a threshold:**

```bash
pql-test code-coverage local/SampleModel --min-coverage 60
```

The threshold behaves like pytest-cov's `--cov-fail-under` / coverage.py's
`fail_under`: the report (text, or the JSON `--output` file) is always
written first, then the command exits `1` if the rounded overall percentage
is below the threshold. A percentage only rounds to 100% when every eligible
object is covered, so `--min-coverage 100` can't pass with a gap.

---

### skill

Manage AI assistant skill files packaged with pql-test.

```bash
pql-test skill [name] [--list] [--format {markdown,json}] [--version]
                      [--install <harness>] [--all] [--show] [--uninstall] [--dry-run] [--force]
```

**Arguments:**

| Argument | Required | Description |
|---|---|---|
| `name` | ❌ | Skill name to print (check-prereqs, code-coverage, retrieve-test, retrieve-tests, run-tests) |
| `--list`, `-l` | ❌ | List all available skills (names only) |
| `--format {markdown,json}` | ❌ | Output format (default: markdown) |
| `--version` | ❌ | Show installed skill version |
| `--install <harness>` | ❌ | Install skills to an AI harness: `claude`, `copilot`, `cursor`, `windsurf` |
| `--all` | ❌ | Install to all harnesses (claude, copilot, cursor, windsurf) |
| `--show` | ❌ | Show installation status and version for all harnesses |
| `--uninstall` | ❌ | Remove pql-test skills from all harnesses |
| `--dry-run` | ❌ | Preview changes without writing files (use with --install or --uninstall) |
| `--force` | ❌ | Overwrite locally-customized skill files during `--install` (skips preserve check) |

**List all available skills:**

```bash
pql-test skill --list
```

```
check-prereqs
code-coverage
retrieve-test
retrieve-tests
run-tests
```

**Print a specific skill:**

```bash
pql-test skill run-tests
```

This outputs the full skill documentation in markdown format, including:
- YAML frontmatter (name, description, version)
- Usage instructions
- CLI flag reference
- SudoLang behavioral contracts (Interface and Constraints blocks)

**Print skill in JSON format:**

```bash
pql-test skill run-tests --format json
```

```json
{
  "name": "run-tests",
  "description": "Execute DAX test suites via XMLA",
  "version": "0.1.13",
  "content": "---\nname: run-tests\n..."
}
```

**Show skill version:**

```bash
pql-test skill --version
```

```
pql-test skills version 0.1.13
```

**Install skills to AI assistant harnesses:**

```bash
# Install to GitHub Copilot (.github/copilot-instructions.md)
pql-test skill --install copilot

# Install to Anthropic Claude (.claude/skills/pql-test/)
pql-test skill --install claude

# Install to Cursor (.cursor/skills/pql-test/)
pql-test skill --install cursor

# Install to Windsurf (.windsurf/skills/pql-test/)
pql-test skill --install windsurf

# Install to all harnesses at once
pql-test skill --all
```

Each install adds a version marker for tracking:
```markdown
<!-- pql-test skills v0.1.13 installed by pql-test CLI -->
```

**Preview installation without writing files:**

```bash
pql-test skill --install copilot --dry-run
```

```
Would update (10 changes):
  • .github/copilot-instructions.md (CREATE)

Run without --dry-run to apply changes.
```

**Show installation status:**

```bash
pql-test skill --show
```

```
pql-test skill installation status:

  Copilot:  ✅ v0.1.13 (.github/copilot-instructions.md)
  Claude:   ✅ v0.1.16 (.claude/skills/pql-test/)
  Cursor:   ❌ Not installed
  Windsurf: ❌ Not installed

All installed harnesses are up to date.
```

If a harness has an outdated version, `--show` reports it:

```
  Copilot:  ⚠️  v0.1.12 (current: 0.1.13) — run pql-test skill --install copilot to update
```

**Uninstall skills from all harnesses:**

```bash
pql-test skill --uninstall
```

This removes all pql-test skill files with the version marker comment. Use `--dry-run` to preview changes first.

**Preserve local customizations (default behavior):**

When you re-run `--install`, pql-test refuses to overwrite a skill file if you've customized it locally. Two cases trigger preservation:

1. The installed marker version matches the current package version (`v0.1.17` marker + `v0.1.17` package) — assumed intentional user edit.
2. The file has no `<!-- Installed by pql-test skill v... -->` marker at all — treated as unmanaged.

Example output:

```
Preserved (customized, v0.1.17 marker present): .claude\skills\pql-test\run-tests\SKILL.md — use --force to overwrite
Preserved (no pql-test marker found): .claude\skills\pql-test\my-custom\SKILL.md — use --force to overwrite
```

**Force overwrite (discard local edits):**

```bash
pql-test skill --install claude --force
```

`--force` writes the packaged skill content regardless of the marker version or user edits. Combine with `--dry-run` to preview.

**Harness target paths:**

| Harness | Install Location |
|---|---|
| Copilot | `.github/copilot-instructions.md` |
| Claude | `.claude/skills/pql-test/` |
| Cursor | `.cursor/skills/pql-test/` |
| Windsurf | `.windsurf/skills/pql-test/` |

**Skill content:**

All skills are packaged in the wheel (`pql_test/skills/`) and installed from the package. Local overrides in `skills/` at the repository root take precedence during development.

---

## Testing against ODCS data contracts

If your team describes data with an [ODCS](https://bitol-io.github.io/open-data-contract-standard/) v3.0 or v3.1 data contract, `pql-test contract` can generate PQL.Assert test suites from the contract's quality rules. It needs the optional, MIT-licensed [pql-odcs](https://github.com/clientfirsttech/pql-test/blob/main/packages/pql-odcs/README.md) package:

```bash
pip install "pql-test[contracts]"
```

| Command | What it does |
|---|---|
| `pql-test contract coverage CONTRACT` | Lists every contract rule as **mapped**, **approximated**, or **skipped** (with a reason), so nothing is dropped silently |
| `pql-test contract lint CONTRACT [--model MODEL_PATH]` | Validates the contract against the ODCS JSON schema, and checks that every table and column resolves in the model |
| `pql-test contract generate CONTRACT MODEL_PATH --env ENV` | Writes `<Prefix>.<Suite>.<ENV>.Tests.dax` files into the PBIP model's `DAXQueries/` folder |
| `pql-test contract run CONTRACT MODEL_PATH --env ENV` | Generates the suites, runs them, and traces every failure back to its contract rule id |
| `pql-test contract trace CONTRACT RESULTS_JSON` | Joins an earlier `run-tests --output` file to the contract's rule ids |

```bash
pql-test contract coverage orders.odcs.yaml
pql-test contract run orders.odcs.yaml ./SalesModel --env DEV --output results.json
```

The generated files follow the rules below:
- Test names are `ODCS <contractId> <ruleId>: <description>`.
- Rules with `severity: warning` go into separate `<ENV>WARN` suites. `contract run` reports them but never fails on them.
- Generated files start with `// Generated by pql-odcs`. `generate` refuses to overwrite any other file unless you pass `--force`.

In v0.1, MODEL_PATH must be a PBIP folder. Query-scoped XMLA runs against `local/<name>` and service models arrive in v0.2.

The [pql-odcs README](https://github.com/clientfirsttech/pql-test/blob/main/packages/pql-odcs/README.md) documents the full rule mapping, name resolution (`pbiTable` / `pbiColumn` custom properties, or a `--mapping` sidecar file), and the standalone `pql-odcs` CLI.

---

## Connection Options

`pql-test` resolves an XMLA connection using the following priority order:

### Local Power BI Desktop (auto-detected)

When a Power BI Desktop instance is open with the requested model,
`pql-test` automatically discovers its local Analysis Services port — both
`run-tests` and `retrieve-tests` follow this same resolution path. Detection
uses two mechanisms, in order:

1. **Primary — process inspection via `psutil`.** The runner enumerates
   running `PBIDesktop.exe` windows (or, when window enumeration is blocked
   by UAC / the Microsoft Store packaging, scans process command lines for
   `.pbip` / `.pbix` arguments) and matches each one against its child
   `msmdsrv.exe` worker process to read the AS listen port. This is how a
   `local/<model_name>` identifier is resolved, and how a filesystem
   `<modelPath>` is resolved when the `.pbip` filename stem matches an open
   instance.
2. **Fallback — Power BI's workspace port file** at
   `%LOCALAPPDATA%\Microsoft\Power BI Desktop\AnalysisServicesWorkspaces\AnalysisServicesWorkspace<port>\Data\msmdsrv.port.txt`
   (and the equivalent Microsoft Store package path under
   `%LOCALAPPDATA%\Packages\Microsoft.MicrosoftPowerBIDesktop*\LocalState`).
   Used when `psutil` is not installed or process enumeration fails.

No connection flags are required in either case — simply open the model in
Power BI Desktop before running:

```bash
# Open ./examples/SampleModel.pbip in Power BI Desktop first, then:
pql-test run-tests ./examples/SampleModel.SemanticModel

# Equivalent — no filesystem path required:
pql-test run-tests local/SampleModel
```

> **Note:** Local auto-detection only works on Windows where Power BI
> Desktop runs natively. On Linux/macOS CI agents, use the explicit remote
> connection flags.

### Remote Power BI Premium / Fabric Workspace

Provide all three connection flags (GUIDs) to connect to a published dataset.
`pql-test` resolves the workspace and dataset **display names** automatically
via the Power BI REST API — you do not need to look them up yourself.

```powershell
pql-test run-tests ./examples/SampleModel.SemanticModel `
  --tenant-id    <azure-ad-tenant-guid> `
  --workspace-id <power-bi-workspace-guid> `
  --dataset-id   <dataset-guid> `
  --client-id    <service-principal-app-id> `
  --client-secret <service-principal-secret>
```

All flags can be supplied via environment variables instead (useful for CI/CD):

| Flag | Environment variable | Description |
|---|---|---|
| `--tenant-id` | `PQL_TENANT_ID` | Azure AD tenant ID |
| `--workspace-id` | `PQL_WORKSPACE_ID` | Power BI workspace GUID |
| `--dataset-id` | `PQL_DATASET_ID` | Dataset / semantic model GUID (SampleModel) |
|  | `PQL_DATASET_ID_RLS` | Dataset GUID for RLS_Model (optional) |
|  | `PQL_DATASET_ID_OLS` | Dataset GUID for OLS_Model (optional) |
| `--client-id` | `PQL_CLIENT_ID` | Service principal client ID |
| `--client-secret` | `PQL_CLIENT_SECRET` | Service principal client secret |
|  | `PQL_ENVIRONMENT` | Cloud environment (Public, USGov, etc.) — no flag; also stored by `pql-test auth login --environment` |

Place these in a `.env` file (git-ignored) at the directory where you invoke
the CLI — typically the repo root or `python/`. The CLI loads `.env`
automatically via `python-dotenv` by walking up from the current working
directory. Copy `python/.env.example` to get started.

> `python/tests/.env` is a separate file — it is **only** consumed by the
> live integration suite (`python/tests/test_live_service.py`), not by the
> CLI itself. Copy `python/tests/.env.example` to populate it when you want
> to run the `@pytest.mark.live` tests against your tenant.

> **Note:** The `PQL_DATASET_ID` variable defaults to the SampleModel dataset. Use `PQL_DATASET_ID_RLS` and `PQL_DATASET_ID_OLS` when running tests against RLS_Model or OLS_Model respectively by passing `--dataset-id $PQL_DATASET_ID_RLS` or `--dataset-id $PQL_DATASET_ID_OLS`.

The CLI uses a **service-principal OAuth2 client-credentials flow** (via MSAL)
to acquire a bearer token, then calls the Power BI REST API to resolve names,
and finally builds the XMLA connection string:

```
powerbi://api.powerbi.com/v1.0/myorg/<WorkspaceName>
```

with the dataset display name as the `Initial Catalog`.

> **Workspace must be on Premium capacity or Fabric F-SKU** for XMLA
> read/write access. The service principal must have at least
> **Contributor** access to the workspace.

### Sovereign / government clouds

Log in with `pql-test auth login --environment <cloud>` (or set
`PQL_ENVIRONMENT` when supplying explicit service-principal credentials) to
target a non-commercial cloud:

| Value | Cloud |
|---|---|
| `Public` | Commercial (default) |
| `Germany` | Azure Germany |
| `China` | Azure China (21Vianet) |
| `USGov` | US Government GCC |
| `USGovHigh` | US Government GCC High |
| `USGovDoD` | US Government DoD |

```powershell
$env:PQL_ENVIRONMENT = 'USGovHigh'
pql-test run-tests ./examples/SampleModel.SemanticModel `
  --tenant-id $env:PQL_TENANT_ID `
  --workspace-id $env:PQL_WORKSPACE_ID `
  --dataset-id $env:PQL_DATASET_ID `
  --client-id $env:PQL_CLIENT_ID `
  --client-secret $env:PQL_CLIENT_SECRET
```

---

## Example Test Suites

All examples below are based on the `SampleModel` in `examples/SampleModel.SemanticModel/`.

### Calculations

`Calculations.DEV.Tests.dax` — verify that DAX measures return the expected values.

```dax
DEFINE
    FUNCTION Calcs.DEV.Tests = () =>
    UNION (
        // [Number of Characters] = COUNTROWS('MarvelFact')
        PQL.Assert.ShouldEqual(
            "Calculations: Number of Characters equals COUNTROWS",
            [Number of Characters],
            COUNTROWS('MarvelFact')
        ),

        // [Number of Characters] must always be > 1000
        PQL.Assert.ShouldBeGreaterThan(
            "Calculations: Number of Characters is greater than 1000",
            1000,
            [Number of Characters]
        ),

        // [Running Total of Character Appearances] must be non-negative
        PQL.Assert.ShouldBeGreaterOrEqual(
            "Calculations: Running Total of Character Appearances is non-negative",
            0,
            [Running Total of Character Appearances]
        ),

        // [Running Total of Character Appearances] must not exceed total row count
        PQL.Assert.ShouldBeLessOrEqual(
            "Calculations: Running Total of Character Appearances does not exceed total row count",
            COUNTROWS('MarvelFact'),
            [Running Total of Character Appearances]
        ),

        // [Number of Characters Title By Date] must start with the expected prefix
        PQL.Assert.ShouldStartWith(
            "Calculations: Number of Characters Title By Date starts with correct prefix",
            "Number of Characters that first appeared ",
            [Number of Characters Title By Date]
        ),

        // [Number of Characters] must return 0 (not blank) when no data exists
        PQL.Assert.ShouldEqual(
            "Calculations: Number of Characters returns 0 not blank for a date with no data",
            0,
            CALCULATE([Number of Characters], FILTER(ALL('DateDim'), 'DateDim'[Year] = -1))
        )
    )

EVALUATE Calcs.DEV.Tests()
```

---

### Data Quality

`DataQuality.DEV.Tests.dax` — verify row counts, null/blank values, uniqueness, and referential integrity.

```dax
DEFINE
    FUNCTION DataQuality.DEV.Tests = () =>
    UNION (
        // Row counts - all tables must have data
        PQL.Assert.Tbl.ShouldHaveRows("Data Quality: MarvelFact has rows", 'MarvelFact'),
        PQL.Assert.Tbl.ShouldHaveRows("Data Quality: DateDim has rows", 'DateDim'),
        PQL.Assert.Tbl.ShouldHaveRows("Data Quality: AlignmentDim has rows", 'AlignmentDim'),
        PQL.Assert.Tbl.ShouldHaveRows("Data Quality: EyeColorDim has rows", 'EyeColorDim'),

        // Null checks - key columns must not be null
        PQL.Assert.Col.ShouldNotBeNull("Data Quality: MarvelFact[Name] is not null", 'MarvelFact'[Name]),
        PQL.Assert.Col.ShouldNotBeNull("Data Quality: MarvelFact[Appearances] is not null", 'MarvelFact'[Appearances]),
        PQL.Assert.Col.ShouldNotBeNull("Data Quality: MarvelFact[DateID] is not null", 'MarvelFact'[DateID]),

        // Range checks
        PQL.Assert.Col.ShouldBeNonNegative("Data Quality: Appearances is non-negative", 'MarvelFact'[Appearances]),

        // Text cleanliness
        PQL.Assert.Col.TextShouldBeTrimmed("Data Quality: MarvelFact[Name] has no leading/trailing spaces", 'MarvelFact'[Name]),

        // Uniqueness checks on dimension keys
        PQL.Assert.Col.ShouldBeDistinct("Data Quality: AlignmentDim[AlignmentID] is unique", 'AlignmentDim'[AlignmentID]),
        PQL.Assert.Col.ShouldBeDistinct("Data Quality: DateDim[DateID] is unique", 'DateDim'[DateID]),

        // No null/blank dimension labels
        PQL.Assert.Col.ShouldNotBeNullOrBlank("Data Quality: AlignmentDim[Alignment] has no blank values", 'AlignmentDim'[Alignment]),

        // Referential integrity checks
        PQL.Assert.ShouldEqual(
            "Data Quality: All MarvelFact.DateID values exist in DateDim",
            0,
            COUNTROWS(FILTER('MarvelFact', ISBLANK(RELATED('DateDim'[DateID]))))
        ),
        PQL.Assert.ShouldEqual(
            "Data Quality: All MarvelFact.AlignmentID values exist in AlignmentDim",
            0,
            COUNTROWS(FILTER('MarvelFact', ISBLANK(RELATED('AlignmentDim'[AlignmentID]))))
        )
    )

EVALUATE DataQuality.DEV.Tests()
```

---

### Schema

`Schema.DEV.Tests.dax` — verify that required tables, columns, and relationships exist.

```dax
DEFINE
    FUNCTION Schema.DEV.Tests = () =>
    UNION (
        // Table existence
        PQL.Assert.Tbl.ShouldExist("Schema: MarvelFact table exists", "MarvelFact"),
        PQL.Assert.Tbl.ShouldExist("Schema: DateDim table exists", "DateDim"),
        PQL.Assert.Tbl.ShouldExist("Schema: AlignmentDim table exists", "AlignmentDim"),
        PQL.Assert.Tbl.ShouldExist("Schema: EyeColorDim table exists", "EyeColorDim"),

        // Column existence - MarvelFact
        PQL.Assert.Col.ShouldExist("Schema: MarvelFact[ID] exists", "MarvelFact", "ID"),
        PQL.Assert.Col.ShouldExist("Schema: MarvelFact[Name] exists", "MarvelFact", "Name"),
        PQL.Assert.Col.ShouldExist("Schema: MarvelFact[Appearances] exists", "MarvelFact", "Appearances"),

        // Column existence - DateDim
        PQL.Assert.Col.ShouldExist("Schema: DateDim[DateID] exists", "DateDim", "DateID"),
        PQL.Assert.Col.ShouldExist("Schema: DateDim[Date] exists", "DateDim", "Date"),
        PQL.Assert.Col.ShouldExist("Schema: DateDim[Year] exists", "DateDim", "Year"),

        // Relationships
        PQL.Assert.Relationship.ShouldExist(
            "Schema: MarvelFact-DateDim relationship exists",
            "MarvelFact", "DateID", "DateDim", "DateID"
        ),
        PQL.Assert.Relationship.ShouldExist(
            "Schema: MarvelFact-AlignmentDim relationship exists",
            "MarvelFact", "AlignmentID", "AlignmentDim", "AlignmentID"
        )
    )

EVALUATE Schema.DEV.Tests()
```

---

### Best Practices

`BestPractices.ANY.Tests.dax` — run PQL's built-in best-practice rules against
the model. Returns a **5-column** result set; must be kept in its own file.

```dax
// NOTE: PQL.Assert.BP functions return a 5-column schema
// (TestName, Expected, Actual, Passed, RuleDescription).
// This MUST be kept in a separate runner — never UNION with standard 4-column test results.

DEFINE
    FUNCTION BestPractices.ANY.Tests = () =>
    UNION (
        PQL.Assert.BP.CheckErrorPrevention(),
        PQL.Assert.BP.CheckFormatting(),
        PQL.Assert.BP.CheckDAXExpressions(),
        PQL.Assert.BP.CheckMaintenance(),
        PQL.Assert.BP.CheckPerformance()
    )

EVALUATE BestPractices.ANY.Tests()
```

---

## Exit Codes

| Code | Meaning |
|---|---|
| `0` | All discovered tests passed, or no tests were discovered (an empty model is not a failure) |
| `1` | One or more tests failed, a prerequisite is missing, an error occurred, **or** tests were discovered but every result was skipped (no XMLA connection could be established — CI misconfiguration guard) |

The "all skipped → exit 1" rule catches CI matrix entries whose
`.SemanticModel` directory does not match any deployed dataset: without it,
the workflow would silently report green even though no tests actually ran
against the model.

`code-coverage` uses its own exit codes, since "no tests ran" and "coverage
is below your threshold" are different failure modes from `run-tests`:

| Code | Meaning |
|---|---|
| `0` | Report produced, and coverage is at/above `--min-coverage` (or no threshold was set) |
| `1` | No XMLA connection could be established, or coverage is below `--min-coverage` |
| `2` | Click usage error — malformed/out-of-range `--min-coverage`, or `--output` without `--format json`. Fails before any XMLA query is made |

CI pipelines can rely on these codes directly:

```powershell
pql-test run-tests ./MyModel `
  --tenant-id    $env:PQL_TENANT_ID `
  --workspace-id $env:PQL_WORKSPACE_ID `
  --dataset-id   $env:PQL_DATASET_ID `
  --client-id    $env:PQL_CLIENT_ID `
  --client-secret $env:PQL_CLIENT_SECRET

if ($LASTEXITCODE -ne 0) {
    Write-Error "DAX tests failed — blocking pipeline."
    exit 1
}
```

A coverage gate in GitHub Actions needs no extra scripting — the non-zero
exit fails the step, and `if: always()` still uploads the report:

```yaml
- name: Enforce DAX test coverage
  shell: pwsh
  run: |
    pql-test code-coverage "MyWorkspace.Workspace/MyModel.SemanticModel" `
      --format json --output coverage.json --min-coverage 60

- name: Upload coverage report
  if: always()
  uses: actions/upload-artifact@v4
  with:
    name: dax-coverage
    path: coverage.json
```

---

## Architecture

The `pql-test` runner is organized as a modular Python package under `python/pql_test/runner/` with focused, single-responsibility modules:

| Module | Lines | Purpose |
|--------|-------|---------|
| `__init__.py` | 224 | Public API re-exports for backward compatibility |
| `models.py` | 204 | Pure data classes and enums (Environment, PqlTest, TestResult, etc.) |
| `adomd.py` | 253 | ADOMD.NET assembly loading and NuGet auto-install |
| `auth.py` | 159 | Authentication credential resolution bridge |
| `pbi_rest.py` | 123 | Power BI REST API helpers (workspace/dataset resolution) |
| `local_pbi.py` | 362 | Local Power BI Desktop process detection via psutil |
| `model_path.py` | 216 | Model identifier parsing (filesystem, local/, Fabric paths) |
| `resolver.py` | 271 | XMLA connection resolution coordination |
| `xmla.py` | 117 | XMLA query execution via ADOMD.NET |
| `discovery.py` | 248 | Test discovery (live XMLA + filesystem) |
| `execution.py` | 195 | Test execution engine with RLS/OLS impersonation |
| `cli_format.py` | 82 | Shared CLI presentation primitives (banners, tables, PASS/FAIL/SKIP colors) |
| `coverage.py` | 149 | Direct test-UDF coverage evidence model (types + `classify_coverage`) |
| `coverage_collector.py` | 339 | XMLA-backed direct test-UDF coverage collection |
| `coverage_report.py` | 147 | Text/JSON presentation for coverage reports |

**Total**: ~2,980 lines across 15 modules

All modules follow a 400-line soft budget (800-line hard budget) to keep code maintainable. Each module has minimal coupling to others, making the codebase easier to understand, test, and modify.

The public API surface remains unchanged from the original monolithic design—all existing imports continue to work:

```python
from pql_test.runner import (
    Environment,
    PqlTest,
    TestResult,
    retrieve_tests,
    run_tests_from_model,
)
```

---

## Troubleshooting

### `pql-test` is not recognised

The package must be installed into your Python environment first:

```powershell
cd python
pip install -e .
```

If you haven't activated the virtual environment, use the full path:

```powershell
.venv\Scripts\pql-test --version
```

### `Error: Model path not found`

The `<modelPath>` argument must point to the PBIP model **root directory** (the
folder that contains the `.pbip` file and the `*.SemanticModel/` directory),
not to the `.SemanticModel` directory itself.

In this repo specifically, pass the `.SemanticModel` directory directly because the
`examples/` directory holds three flat PBIP layouts side-by-side:

```bash
# Correct — points directly at the SemanticModel directory
pql-test run-tests ./examples/SampleModel.SemanticModel

# Incorrect — examples/ contains three flat models; ./examples/SampleModel does not exist
pql-test run-tests ./examples/SampleModel
```

For a single-model layout where the PBIP root contains exactly one `.SemanticModel/`
and one `.pbip` file, either form (the root directory or the `.SemanticModel`
subfolder) works.

### `No tests found`

Verify that:

1. The `*.SemanticModel/DAXQueries/` folder exists inside `<modelPath>`.
2. Test files end with `.Tests.dax` (e.g. `Calculations.DEV.Tests.dax`).
3. Files named without `.Tests` (e.g. `Query 1.dax`) are ignored by design.

### `No XMLA connection detected`

When running locally, make sure:

1. The model folder contains a `.pbip` file.
2. Power BI Desktop is **open** with the model loaded (not just saved).
3. The environment variable `%LOCALAPPDATA%` is set (Windows only).

For CI/CD pipelines, always supply all five remote connection flags:
`--tenant-id`, `--workspace-id`, `--dataset-id`, `--client-id`, `--client-secret`.

### `msal not installed` / `pythonnet not installed`

Install missing dependencies:

```powershell
pip install msal pythonnet psutil
```

Or reinstall everything:

```powershell
pip install -e .
```

### `Failed to acquire access token`

Verify your service principal credentials and that the app has been granted
**Dataset.Read.All** (or **Dataset.ReadWrite.All**) in the Power BI service,
and has at least **Contributor** access to the workspace.

### Query returned no rows

Ensure the final line of the `.dax` file is an `EVALUATE` statement that calls
the test function, for example:

```dax
EVALUATE Calculations.DEV.Tests()
```

### `Cannot connect to XMLA endpoint`

- Confirm the workspace is on **Premium capacity or Fabric F-SKU**.
- Confirm the signed-in account has at least **Contributor** access to the workspace.
- Check that the `--workspace-id` is the workspace GUID (not its display name).
- Check that `--dataset-id` is the semantic model GUID (visible in the dataset URL in the Power BI service).
