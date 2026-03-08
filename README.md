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
  - [PBIP Model Layout](#pbip-model-layout)
  - [Writing Test Files](#writing-test-files)
    - [Standard test schema (4 columns)](#standard-test-schema-4-columns)
    - [Best-practices test schema (5 columns)](#best-practices-test-schema-5-columns)
    - [Naming convention](#naming-convention)
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

| Requirement | Minimum version | Notes |
|---|---|---|
| Python | 3.9+ | [python.org](https://www.python.org/downloads/) |
| pythonnet | 3.x | `pip install pythonnet` — needed to load the ADOMD.NET assembly |
| Power BI Desktop | any | Provides `Microsoft.PowerBI.AdomdClient.dll` used for local XMLA connections |
| msal | 1.24+ | `pip install msal` — required for service-principal auth against remote workspaces |
| psutil | any | `pip install psutil` — required for `--local` mode; optional otherwise |

Run the built-in check to verify your environment:

```powershell
pql-test check-prereqs
```

---

## Installation

`pql-test` is a Python package inside the `python/` directory of this
repository.

**1. Create and activate a virtual environment** (recommended):

```powershell
cd python
python -m venv .venv
.venv\Scripts\Activate.ps1
```

**2. Install the package and its dependencies:**

```powershell
pip install -e .
```

The `-e` flag installs in *editable* mode so source changes are reflected
immediately without reinstalling.

**3. Verify the CLI is on `PATH`:**

```powershell
pql-test --version
pql-test check-prereqs
```

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

The `DEV` / `ANY` segment is a convention indicating the environment scope;
`pql-test` treats all `*.Tests.dax` files equally.

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
pql-test retrieve-tests <modelPath> [--verbose]
```

**Arguments:**

| Argument | Required | Description |
|---|---|---|
| `<modelPath>` | ✅ | Path to the PBIP model root directory |
| `--verbose`, `-v` | ❌ | Also print file paths and connection info |

**Example:**

```bash
pql-test retrieve-tests ./examples/SampleModel
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
pql-test retrieve-tests ./examples/SampleModel --verbose
```

```
Found 4 DAX test suite(s):

  • BestPractices.ANY.Tests
    File: /examples/SampleModel/SampleModel.SemanticModel/DAXQueries/BestPractices.ANY.Tests.dax
  • Calculations.DEV.Tests
    DAX function: Calcs.DEV.Tests
    File: /examples/SampleModel/SampleModel.SemanticModel/DAXQueries/Calculations.DEV.Tests.dax
  ...

Connection: none detected — open the model in Power BI Desktop or supply
  --tenant-id, --workspace-id, --dataset-id to run tests.
```

**Filter to a single suite using `--test`:**

```bash
pql-test retrieve-tests ./examples/SampleModel --test "Calculations.DEV.Tests"
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
| `<modelPath>` | ✅ | Path to the PBIP model root directory |
| `<name>` | ✅ | Test suite name (file stem without `.dax`) |
| `--verbose`, `-v` | ❌ | Also print the full DAX source |

**Example:**

```bash
pql-test retrieve-test ./examples/SampleModel "DataQuality.DEV.Tests"
```

```
Found 1 DAX test suite(s):

  • DataQuality.DEV.Tests
```

**With `--verbose`** (shows the full DAX source):

```bash
pql-test retrieve-test ./examples/SampleModel "DataQuality.DEV.Tests" --verbose
```

---

### run-tests

Execute DAX test suites in a PBIP model via XMLA and report pass/fail results.

```bash
pql-test run-tests <modelPath> [--test <name>] [--verbose]
                               [--output <file>]
                               [--log-format {azuredevops,github}]
                               [--tenant-id <id>]
                               [--workspace-id <id>]
                               [--dataset-id <id>]
```

**Arguments:**

| Argument | Required | Description |
|---|---|---|
| `<modelPath>` | ✅ | Path to the PBIP model root directory |
| `--test <name>` | ❌ | Run only the named test suite |
| `--verbose`, `-v` | ❌ | Show message and duration for every result (not just failures) |
| `--output <file>` | ❌ | Write full JSON results to `<file>` in addition to stdout output |
| `--log-format <fmt>` | ❌ | Emit CI-native annotations: `azuredevops` or `github` |
| `--tenant-id <id>` | ❌ | Azure AD tenant ID (required for remote XMLA) |
| `--workspace-id <id>` | ❌ | Power BI workspace GUID (required for remote XMLA) |
| `--dataset-id <id>` | ❌ | Dataset / semantic model GUID (required for remote XMLA) |

**Run all suites against a locally-open Power BI Desktop model:**

```bash
pql-test run-tests ./examples/SampleModel
```

**Run all suites against a remote Power BI Premium / Fabric workspace:**

```bash
pql-test run-tests ./examples/SampleModel \
  --tenant-id  00000000-0000-0000-0000-000000000000 \
  --workspace-id 11111111-1111-1111-1111-111111111111 \
  --dataset-id   22222222-2222-2222-2222-222222222222
```

**Run a single named test suite:**

```bash
pql-test run-tests ./examples/SampleModel --test "Calculations.DEV.Tests"
```

**Save JSON results to a file while still printing to the console:**

```bash
pql-test run-tests ./examples/SampleModel --output results.json
```

The JSON file contains `passed`, `failed`, `skipped`, `total`, and a `results` array with per-assertion detail. Example structure:

```json
{
  "model_path": "/examples/SampleModel",
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
pql-test run-tests ./examples/SampleModel --log-format azuredevops
```

This emits `##[group]` / `##[endgroup]` / `##[error]` / `##[warning]` and a final `##vso[task.complete result=Failed|Succeeded;]` command, making failures visible directly in the Azure DevOps pipeline log.

**Emit GitHub Actions workflow annotations:**

```bash
pql-test run-tests ./examples/SampleModel --log-format github
```

This emits `::group::` / `::endgroup::` / `::error::` / `::warning::` / `::notice::` commands, surfacing failures as annotations on the GitHub Actions summary page.

**Combine `--log-format` with `--output` in CI pipelines:**

```powershell
pql-test run-tests ./examples/SampleModel `
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
model: /examples/SampleModel

......

===================== 6 passed, 0 failed, 6 total =======================
```

**Example output (with failures):**

```
XMLA connection: powerbi://api.powerbi.com/v1.0/myTenant/myWorkspace / catalog: 22222...

========================== test session starts ===========================
model: /examples/SampleModel

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
model: /examples/SampleModel

ssss

------------------------------ warnings summary --------------------------
  WARN No XMLA connection detected. Tests will be reported as skipped. ...

==================== 0 passed, 0 failed, 4 total, 4 warnings ===========
```

---

## Connection Options

`pql-test` resolves an XMLA connection using the following priority order:

### Local Power BI Desktop (auto-detected)

When a `.pbip` file exists in `<modelPath>` **and** a Power BI Desktop instance
is open with that model, `pql-test` automatically discovers the local Analysis
Services port from:

```
%LOCALAPPDATA%\Microsoft\Power BI Desktop\AnalysisServicesWorkspaces\
    AnalysisServicesWorkspace<port>\Data\msmdsrv.port.txt
```

No connection flags are required in this case — simply open the model in
Power BI Desktop before running:

```bash
# Open ./examples/SampleModel in Power BI Desktop first, then:
pql-test run-tests ./examples/SampleModel
```

> **Note:** Auto-detection only works on Windows where `%LOCALAPPDATA%` is
> set. On Linux/macOS CI agents, use the explicit remote connection flags.

### Remote Power BI Premium / Fabric Workspace

Provide all three connection flags (GUIDs) to connect to a published dataset.
`pql-test` resolves the workspace and dataset **display names** automatically
via the Power BI REST API — you do not need to look them up yourself.

```powershell
pql-test run-tests ./examples/SampleModel `
  --tenant-id    <azure-ad-tenant-guid> `
  --workspace-id <power-bi-workspace-guid> `
  --dataset-id   <dataset-guid> `
  --client-id    <service-principal-app-id> `
  --client-secret <service-principal-secret>
```

All flags can be supplied via environment variables instead (useful for CI/CD):

| Flag | Environment variable |
|---|---|
| `--tenant-id` | `PQL_TENANT_ID` |
| `--workspace-id` | `PQL_WORKSPACE_ID` |
| `--dataset-id` | `PQL_DATASET_ID` |
| `--client-id` | `PQL_CLIENT_ID` |
| `--client-secret` | `PQL_CLIENT_SECRET` |
| `--environment` | `PQL_ENVIRONMENT` |

Place these in a `python/tests/.env` file (git-ignored) for local development
— copy `python/tests/.env.example` to get started.

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

Pass `--environment` (or set `PQL_ENVIRONMENT`) to target a non-commercial cloud:

| Value | Cloud |
|---|---|
| `Public` | Commercial (default) |
| `Germany` | Azure Germany |
| `China` | Azure China (21Vianet) |
| `USGov` | US Government GCC |
| `USGovHigh` | US Government GCC High |
| `USGovDoD` | US Government DoD |

```powershell
pql-test run-tests ./examples/SampleModel `
  --environment USGovHigh `
  --tenant-id $env:PQL_TENANT_ID `
  --workspace-id $env:PQL_WORKSPACE_ID `
  --dataset-id $env:PQL_DATASET_ID `
  --client-id $env:PQL_CLIENT_ID `
  --client-secret $env:PQL_CLIENT_SECRET
```

---

## Example Test Suites

All examples below are based on the `SampleModel` in `examples/SampleModel/`.

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
| `0` | All tests passed (or no tests were found) |
| `1` | One or more tests failed, a prerequisite is missing, or an error occurred |

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

```bash
# Correct
pql-test run-tests ./examples/SampleModel

# Incorrect — do not point at the SemanticModel subfolder
pql-test run-tests ./examples/SampleModel/SampleModel.SemanticModel
```

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
