# pql-test — DAX Test Runner for PBIP Models

`pql-test` is a command-line tool bundled with the Power Query Lint VS Code
extension. It discovers and executes DAX unit-test suites stored inside a
**Power BI Project (PBIP)** semantic model, mirroring the
[`Invoke-DQVTesting`](https://github.com/kerski/fabric-dataops-patterns)
execution pattern.

Tests are plain `.dax` files that use the `PQL.Assert` family of functions.
The runner connects to Analysis Services via XMLA — either a locally-open
Power BI Desktop instance (auto-detected) or a remote Power BI Premium /
Microsoft Fabric workspace endpoint.

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

`pql-test` lives in the `python/` directory of the
[GitHub repository](https://github.com/clientfirsttech/pql-test). Clone it,
then:

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

The JSON file contains `passed`, `failed`, `skipped`, `total`, and a `results` array with per-assertion detail. Example structure:

```json
{
  "model_path": "/examples/SampleModel.SemanticModel",
  "passed": 5,
  "failed": 1,
  "skipped": 0,
  "total": 6,
  "results": [
    { "test_name": "Calculations: X equals Y", "passed": false, "skipped": false,
      "message": "Expected: 5 | Actual: 7", "error": null, "duration_ms": 12.3 }
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
