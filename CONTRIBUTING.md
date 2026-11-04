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
├── pyproject.toml              ← uv workspace root only (member: python)
├── LICENSE.txt, NOTICE         ← AGPL-3.0-only, and third-party attributions
├── LICENSES.md                 ← the license, and the files that carry their own
├── python/                     ← pql-test
│   ├── pql_test/               ← CLI implementation
│   │   ├── cli.py              ← entry point (`pql-test` command)
│   │   ├── runner/             ← XMLA + test discovery + execution
│   │   ├── auth/               ← persistent Fabric-CLI-style auth
│   │   ├── odcs/               ← ODCS contracts → PQL.Assert suites (`pql-test contract`)
│   │   └── contract_run.py     ← `pql-test contract run` and `doctor` (the connected commands)
│   ├── tests/                  ← pytest suite (mocked + live integration); tests/odcs/ for contracts
│   ├── pyproject.toml          ← single source of truth for version & deps
│   └── .env.example            ← copy to .env for service-mode credentials
├── examples/                   ← three example PBIP models (see "Examples")
├── ai/                         ← aidd skills, commands, scaffolds (not shipped)
├── tasks/                      ← epic/task documents (historical context)
├── .github/workflows/          ← CI: validate-plugin → promptfoo-eval → run-tests-remote
├── plan.md                     ← active work + completed milestones
└── README.md                   ← user-facing documentation
```

pql-test's source lives only in `python/`. The CI workflow installs from
`./python` (`pip install ./python`); local installs do the same with `-e`.

---

## License and sign-off

pql-test is licensed under AGPL-3.0-only ([LICENSES.md](LICENSES.md)).

- **Start every `.py` file with an SPDX header**: `# SPDX-License-Identifier: AGPL-3.0-only`
  (after the shebang line, when there is one).
- **Sign off every commit** with the [Developer Certificate of Origin](https://developercertificate.org/):
  `git commit -s`. The sign-off certifies that you have the right to submit the change under AGPL-3.0-only.
- **Sign the [Contributor License Agreement](CLA.md) once** (outside contributors; a bot comments on your first pull request and you reply with the sentence it gives). It is the Apache Individual CLA adapted to Client First Technologies: you keep your copyright and license your contributions to the Company, which lets it also offer pql-test under other licenses. The DCO sign-off above is still required.
- **Keep runtime dependencies AGPL-compatible**: MIT, BSD, Apache-2.0, LGPL, or GPL-3.0 licensed packages.
- **Keep the contract file commands free of XMLA.** `pql-test contract lint|coverage|generate|trace`
  only read and write files, so they run on Linux CI. Import ADOMD.NET-dependent code lazily, inside
  `run` and `doctor` only.

---

## Secrets and security checks

This repository is public, so a committed secret is a leaked secret, even when a later commit removes it.

- **Credentials live only in `.env` files** (`python/.env`, `python/tests/.env`), copied from `.env.example`. `.gitignore` covers `.env` files, certificates (`*.pem`, `*.p12`, `*.pfx`), and keys.
- **Install the hooks once per clone:**

  ```bash
  pip install pre-commit      # or: uv tool install pre-commit
  pre-commit install
  pre-commit run --all-files  # optional: check everything now
  ```

  Before every commit, [`.pre-commit-config.yaml`](.pre-commit-config.yaml) runs:
  - gitleaks on the staged changes;
  - a private-key check;
  - a large-file check;
  - bandit on `python/pql_test` (medium severity and up).

  Never bypass them with `--no-verify`. The gitleaks hook scans what you stage. To scan the
  working tree too, run `gitleaks dir .`; it also reports your ignored `.env` files, which is
  expected.
- **CI repeats them** in [`security.yml`](.github/workflows/security.yml) (Stage 0 of `ci.yml`), with gitleaks on the full history, pip-audit on the runtime dependencies, and the offline dead-link check.
- **When gitleaks finds something:**
  - **A real secret:** don't commit it. If it was already committed, treat it as leaked: rotate it first, then remove it from the change.
  - **Not a secret** (for example a public client ID): allowlist that exact finding in [`.gitleaksignore`](.gitleaksignore) by its fingerprint, with a comment saying why.
- **When bandit finds something:**
  - fix it;
  - or, for a reviewed false positive, add `# nosec <id>` on the flagged line, with the reason in a comment above it.
  - Never skip a test for the whole project.
- **Downloads that run code** are pinned and verified. For example, the ADOMD.NET auto-install checks the NuGet package against a pinned SHA-512, and the CI gitleaks binary is checked against its release checksum.
- **Workflow inputs** reach shell scripts through `env:`, never as `${{ }}` inside `run:` text.
- **Reporting a vulnerability:** see [SECURITY.md](SECURITY.md).

---

## CLI Output Conventions

Every `pql-test` command that prints a human-readable report to a terminal
follows one shared style, defined in
[`python/pql_test/runner/cli_format.py`](python/pql_test/runner/cli_format.py):

- **Shared presentation module.** Session banners (`banner()`), bordered
  tables (`table_top`/`table_mid`/`table_bottom`/`table_row`), and cell
  padding/truncation (`pad()`/`truncate()`) live in `cli_format.py`, not as
  per-command closures inside `cli.py`. If you're adding a new command that
  prints a status table or a session header, import from there instead of
  writing a new implementation — see `_print_results` (`run-tests`) and
  `_print_coverage_report` (`code-coverage`) for the calling pattern.
- **Connection diagnostic + session banner.** Any command that resolves an
  XMLA connection and prints text output opens with a `Local XMLA
  connection: <server> / catalog: <catalog>` (or `XMLA connection: ...` for
  non-local connections) line, followed by a `===== <command> session starts
  =====` banner and a `model: <path>` line, before any report content. This
  mirrors pytest's own session banner and gives every command the same
  "what did I connect to, what am I running" opening.
- **One status-color vocabulary.** `STATUS_COLORS` in `cli_format.py` is the
  only status-color mapping in the CLI: PASS/fully-covered = green,
  FAIL/uncovered = red, SKIP/partially-covered = yellow. Don't introduce a
  new color meaning for a new command — reuse this vocabulary, e.g. a new
  category or threshold should map onto green/yellow/red rather than a
  fourth color.
  `code-coverage` grades percentages with `coverage_status()` in
  `coverage_report.py`: default 50/80 watermarks (red/yellow/green, as
  Istanbul/Jest do), or binary red/green against `--min-coverage` when set.
- **JSON output stays presentation-free.** None of the above applies to
  `--format json` output — the JSON payload is the stable, machine-readable
  shape and must not gain banner/table text.

This convention exists because `run-tests` and `code-coverage` drifted apart
once already — `run-tests` grew a pytest-style banner, bordered table, and
color coding, while `code-coverage` was implemented separately with plain
indented text and no connection diagnostic. See
[`tasks/archive/2026-09-22-consistent-cli-output.md`](tasks/archive/2026-09-22-consistent-cli-output.md)
(archived once complete) for the fix.

---

## CLI Argument Conventions

The same option means the same thing on every command. The shared options live in
[`python/pql_test/cli_options.py`](python/pql_test/cli_options.py); use them instead of
declaring your own, and [`tests/test_cli_conventions.py`](python/tests/test_cli_conventions.py)
fails when a command drifts.

- **`-v/--verbose` and `-q/--quiet`** (`verbosity_options`) on every command that prints a
  report. Quiet prints only the summary line, which the command marks with
  `record_summary()`; the rest of the report (including a warnings section on stdout) is
  hidden, messages written to stderr still appear, and the exit code never changes. A
  result printed on stdout (JSON, CI annotations from `--log-format`, a contract, DAX) is
  never suppressed. Passing both flags is a usage error. `--verbose` takes the command's own
  help text through `verbosity_options(verbose_help=...)`.
- **`--format text|json`** (`format_option`) is the one way to ask for machine-readable
  output. With `--format json`, stdout carries only the JSON, printed with `emit_result()`;
  every other line goes to stderr automatically. `retrieve-tests` and `retrieve-test` default
  to `json` because tools and agents parse them; everything else defaults to `text`.
- **`--output FILE` / `-o FILE`** (`output_option`) writes the command's result to FILE, as
  well as the report on screen.
- **Names:**
  - `--env` is the test environment;
  - `--cloud` is the Azure cloud;
  - credentials are `--tenant-id`, `--client-id`, and `--client-secret`;
  - `--test NAME` selects one test suite.
- **Renaming an option:** keep the old spelling working with `deprecated_alias()`, placed
  above the option it aliases. The alias is hidden from `--help`, warns once on stderr, and
  behaves exactly as before. When both spellings are given with different values, it is a
  usage error; an explicit value equal to the default cannot be told apart from no value, so
  the alias wins then. Today's aliases:
  - `--human` for `--format text`;
  - `-u`/`--user` for `--client-id`;
  - `-p`/`--password` for `--client-secret`;
  - `--tenant` for `--tenant-id`;
  - `--environment` for `--cloud`.

---

## Prerequisites

| Requirement | Why | How to install |
|---|---|---|
| Python 3.10+ | Runs the CLI | `winget install Python.Python.3.12` (or [python.org](https://www.python.org/downloads/)) |
| ADOMD.NET client DLL | `pyadomd` loads this at import time | See **ADOMD.NET install** below — required even if you have Power BI Desktop |
| Power BI Desktop | Needed for the local-mode smoke test only | Microsoft Store or [powerbi.microsoft.com](https://www.microsoft.com/power-platform/products/power-bi/desktop) |
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
  ✅ Python >= 3.10 — Current: 3.12.x
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

# Slow: include live tests (needs python/.env)
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

## Service Principal Setup (Least-Privilege)

**Security Note**: Service principals with broad permissions (e.g., `Workspace.ReadWrite.All`, tenant-wide admin roles) create security risks if credentials are compromised. Follow least-privilege principles to minimize exposure.

### Recommended Permissions

For DAX test execution, a service principal needs:

#### 1. Azure AD API Permissions (Azure Portal)
- **Power BI Service → `Dataset.Read.All`** (delegated or application)
- **NOT required**: `Workspace.ReadWrite.All`, `Tenant.Read.All`, or admin roles

#### 2. Workspace Access (Power BI Service)
- **Minimum**: **Viewer** role (read-only access to datasets)
- **Recommended**: **Contributor** role (can refresh datasets, useful for CI/CD)
- **NOT recommended**: Admin or Member roles (unnecessary elevation)

#### 3. Dataset RLS/OLS Roles (Optional)
- If testing RLS: Add SPN to dataset roles via `ImpersonateRole:` annotation
- If testing with `EffectiveUserName`: SPN must be workspace Admin (not recommended)

### Step-by-Step SPN Creation

#### A. Register Application in Azure AD

1. Open [Azure Portal](https://portal.azure.com) → **Azure Active Directory** → **App registrations** → **New registration**
2. **Name**: `pql-test-ci-<workspace-name>` (descriptive, scoped to purpose)
3. **Supported account types**: "Accounts in this organizational directory only"
4. **Redirect URI**: Leave blank (not needed for service principal auth)
5. Click **Register**
6. **Copy these values** (you'll need them later):
   - **Application (client) ID**
   - **Directory (tenant) ID**

#### B. Create Client Secret

1. In the app registration → **Certificates & secrets** → **Client secrets** → **New client secret**
2. **Description**: `pql-test-ci-secret` (or descriptive name)
3. **Expires**: **90 days** (recommended for security)
   - ⚠️ **Important**: Set a calendar reminder to rotate before expiry
   - Shorter expiry = better security, but requires more frequent rotation
4. Click **Add** and **immediately copy the secret value** (shown only once)

**Secret Rotation Policy**:
- Rotate secrets every 90 days (best practice)
- Never reuse old secrets
- Update CI/CD secrets immediately after rotation
- Revoke old secret only after confirming new secret works

#### C. Grant Power BI API Permissions

1. In the app registration → **API permissions** → **Add a permission**
2. Select **Power BI Service**
3. **Delegated permissions** → Check **Dataset.Read.All**
4. Click **Add permissions**
5. Click **Grant admin consent for [tenant]** (requires Azure AD admin)

#### D. Add SPN to Power BI Workspace

1. Open [Power BI Service](https://app.powerbi.com)
2. Navigate to your workspace (must be Premium or Fabric F-SKU)
3. **Workspace settings** → **Access**
4. **Add** → Search for your SPN by **Application (client) ID** or **App name**
5. Select **Contributor** role (allows read + refresh)
6. Click **Add**

**Role Guidance**:
| Role | Can read datasets | Can run tests | Can refresh | Can modify | Recommended? |
|------|-------------------|---------------|-------------|------------|--------------|
| Viewer | ✅ | ✅ | ❌ | ❌ | ✅ Yes (minimal) |
| Contributor | ✅ | ✅ | ✅ | ❌ | ✅ Yes (CI/CD) |
| Member | ✅ | ✅ | ✅ | ✅ | ⚠️ No (too broad) |
| Admin | ✅ | ✅ | ✅ | ✅ | ❌ No (excessive) |

#### E. Enable XMLA Endpoint (Premium/Fabric Only)

1. **Power BI Admin Portal** → **Tenant settings** → **Integration settings**
2. **XMLA endpoint** → Set to **Read Only** or **Read Write**
3. Click **Apply**

**Note**: XMLA endpoints require Premium or Fabric capacity. Standard workspaces do not support XMLA connections.

### Certificate-Based Authentication (Advanced)

For production environments, certificates are more secure than secrets:

#### A. Generate Self-Signed Certificate (Development)

```powershell
# Generate certificate (valid 2 years)
$cert = New-SelfSignedCertificate `
  -Subject "CN=pql-test-ci" `
  -CertStoreLocation "Cert:\CurrentUser\My" `
  -KeyExportPolicy Exportable `
  -KeySpec Signature `
  -KeyLength 2048 `
  -KeyAlgorithm RSA `
  -HashAlgorithm SHA256 `
  -NotAfter (Get-Date).AddYears(2)

# Export certificate (.cer for Azure AD upload)
$certPath = "C:\temp\pql-test-ci.cer"
Export-Certificate -Cert $cert -FilePath $certPath

# Export private key (.pfx for pql-test auth)
$pfxPath = "C:\temp\pql-test-ci.pfx"
$password = ConvertTo-SecureString -String "your-strong-password" -Force -AsPlainText
Export-PfxCertificate -Cert $cert -FilePath $pfxPath -Password $password
```

#### B. Upload Certificate to Azure AD

1. App registration → **Certificates & secrets** → **Certificates** → **Upload certificate**
2. Select the `.cer` file → **Add**
3. Certificate is now trusted for authentication

#### C. Use Certificate with pql-test

```powershell
pql-test auth login `
  --certificate "C:\temp\pql-test-ci.pfx" `
  --client-id <app-id> `
  --tenant-id <tenant-id>
```

**Certificate Protection**:
- **File permissions**: Set to `600` (owner read/write only)
  ```powershell
  icacls "C:\secure\pql-test-ci.pfx" /inheritance:r /grant:r "$env:USERNAME:(R,W)"
  ```
- **Production**: Use Azure Key Vault or HSM (Hardware Security Module)
- **Rotation**: Renew certificates before expiry (2-year max recommended)

### Security Best Practices Summary

✅ **DO**:
- Use separate SPNs for dev/staging/prod environments
- Rotate secrets every 90 days
- Grant minimum required permissions (Viewer or Contributor)
- Store secrets in Azure Key Vault or CI/CD secret stores
- Use certificate-based auth for production
- Set file permissions on certificate files (`600` on Linux/macOS)
- Monitor SPN usage in Azure AD sign-in logs

❌ **DON'T**:
- Grant `Workspace.ReadWrite.All` or tenant admin roles
- Use the same SPN across multiple environments
- Store secrets in code or version control
- Share SPN credentials between teams
- Use secrets longer than 90 days without rotation
- Grant workspace Admin role (only needed for `EffectiveUserName`)

### Federated credentials (workload identity)

A federated credential lets a CI job exchange its own short-lived OIDC token for an Entra token, so no client secret is stored anywhere. `pql-test auth login --client-id <id> --tenant-id <tenant>` reads that token from the `PQL_FEDERATED_TOKEN` environment variable (or `--federated-token`, which puts it on the command line where other processes can see it, so prefer the variable).

Create the federated credential on the app registration (**Certificates & secrets** → **Federated credentials**) with the narrowest subject that still works:

| Subject | Verdict |
|---------|---------|
| `repo:<owner>/<repo>:environment:<environment>` | Good: only jobs that run in that GitHub Environment (add required reviewers to it) |
| `repo:<owner>/<repo>:ref:refs/heads/main` | Acceptable: only that branch |
| `repo:<owner>/<repo>:pull_request` | Avoid: any pull request in the repository can sign in, including a branch an attacker with write access creates |
| `repo:<owner>/*` | Never: every repository in the organization |

Keep the audience at the default `api://AzureADTokenExchange`, and give each environment (dev, staging, prod) its own app registration.

In GitHub Actions the job needs `permissions: id-token: write`. Request the token inside the job, mask it, and pass it through the environment rather than writing it to a file:

```yaml
permissions:
  id-token: write
  contents: read
steps:
  - name: Get OIDC token
    uses: actions/github-script@<pinned commit SHA>
    with:
      script: |
        const token = await core.getIDToken('api://AzureADTokenExchange');
        core.setSecret(token);
        core.exportVariable('PQL_FEDERATED_TOKEN', token);
  - name: Sign in and test
    shell: pwsh
    run: |
      pql-test auth login --client-id ${{ vars.PQL_CLIENT_ID }} --tenant-id ${{ vars.PQL_TENANT_ID }}
      pql-test run-tests "<workspace>.Workspace/<model>.SemanticModel"
```

[`federated-smoke.yml`](.github/workflows/federated-smoke.yml) runs this flow end to end on demand (`workflow_dispatch`), without any secret; its header lists the one-time Entra and GitHub Environment setup. It has not been run yet, because that setup is a maintainer step. The OIDC token expires within minutes, so sign in in the same job that runs the tests.

### Managed identity

Managed identity needs no stored credential, so the risk is what the identity can do and who can reach it.

- Give the identity only what `run-tests` needs: add it (or a security group holding it) to the Fabric/Power BI workspace as **Viewer**, or **Contributor** if the job also refreshes. Do not make it a workspace Admin or give it tenant-wide roles.
- Prefer a user-assigned identity per pipeline over a shared system-assigned one: it can be revoked on its own, and `--client-id` selects it.
- Anything running on the same VM, container, or agent can request that identity's token from the metadata endpoint. Do not run untrusted code (pull request builds from forks) on an agent whose identity can read production models, and restrict outbound access to the metadata endpoint where the platform allows it.
- Use Azure Activity Log and Entra sign-in logs to see what the identity did.

---

## Service smoke test (Power BI Premium / Fabric)

1. Copy `python/.env.example` to `python/.env` (or `python/tests/.env`, which overrides it for the tests only) and fill in:
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

## Skill Update Workflow

Skills live in both **source** (`skills/`) and **packaged** (`python/pql_test/skills/`) locations. The CI pipeline validates that they stay in sync.

### Directory Structure

```
pql-test/
├── skills/                          ← source skills (maintained by contributors)
│   ├── check-prereqs/SKILL.md
│   ├── code-coverage/SKILL.md
│   ├── retrieve-test/SKILL.md
│   ├── retrieve-tests/SKILL.md
│   └── run-tests/SKILL.md
└── python/pql_test/skills/          ← packaged skills (distributed in wheel)
    ├── check-prereqs/SKILL.md
    ├── code-coverage/SKILL.md
    ├── retrieve-test/SKILL.md
    ├── retrieve-tests/SKILL.md
    └── run-tests/SKILL.md
```

### Required YAML Frontmatter

Every `SKILL.md` file must begin with YAML frontmatter:

```markdown
---
name: skill-name
description: One-line description of what the skill does
version: 0.1.13
---

# Skill content here...
```

**Required fields**:
- `name` — Skill identifier (lowercase-kebab-case)
- `description` — Brief summary for skill listing
- `version` — Must match package version in `pyproject.toml`

### Updating a Skill

1. **Edit the source** file in `skills/<skill-name>/SKILL.md`
2. **Copy to packaged location**: `python/pql_test/skills/<skill-name>/SKILL.md`
3. **Ensure version matches** `pyproject.toml`
4. **Run tests** to validate:
   ```powershell
   pytest tests/test_skill_packaging.py -v
   ```
5. **Commit both files together** — CI validates they match byte-for-byte

### CI Validation

`test_skill_packaging.py` enforces:
- ✅ Source and packaged skills are identical
- ✅ All skills have required frontmatter (name, description, version)
- ✅ Version fields match `pyproject.toml`
- ✅ `run-tests` skill has SudoLang contracts (Interface, Constraints)
- ✅ All source skills are packaged
- ✅ `pyproject.toml` includes `skills/**/*.md` in package-data

`test_skill_content.py` enforces skill-to-CLI parity:
- ✅ Every long-form Click flag on each command appears in the matching `SKILL.md`
- ✅ All MODEL_PATH formats (filesystem, `local/<name>`, `<workspace>.Workspace/<model>.SemanticModel`) are documented
- ✅ SudoLang `Interface` and `Constraints` blocks contain required fields
- ✅ Exit codes, env vars, and log-format values are documented
- ✅ No skill references removed flags (e.g. `--local`) or non-existent commands

**When you add a CLI flag**, `test_skill_content.py` will fail until the corresponding `SKILL.md` mentions the new flag. Update the skill and re-run:

```bash
cd python
pytest tests/test_skill_content.py -v
```

### LLM-Graded Skill Evaluation (Mode B)

`tests/promptfoo/` contains realistic LLM tests that feed each `SKILL.md` to Claude Sonnet 4 via GitHub Models and assert the model produces correct `pql-test` commands. This catches skills that are technically complete but ambiguous enough to mislead the LLM.

**Run locally** (requires `GITHUB_TOKEN` with `models: read`):

```powershell
cd tests/promptfoo
$env:GITHUB_TOKEN = "ghp_..."
python run_eval.py
```

**Dry-run** (validate test structure, no API calls):

```powershell
python run_eval.py --dry-run
```

**Without `GITHUB_TOKEN`**: the runner warns and exits 0 — never blocks local dev.

**CI**: `.github/workflows/promptfoo-eval.yml` runs on every push touching `skills/**` or `tests/promptfoo/**`. Results are uploaded as the `eval-results` artifact.

See [tests/promptfoo/README.md](tests/promptfoo/README.md) for how to add new test cases.

### SudoLang Behavioral Contracts

Complex skills like `run-tests` use SudoLang syntax for behavioral contracts:

```markdown
## Interface RunTests {
  exit_code: 0 | 1,
  output_format: "pytest-style" | "json",
  log_annotations: null | "github" | "azuredevops"
}

## Constraints {
  - MODEL_PATH resolution order: local/<name> → filesystem path → <workspace>/<model>
  - Credentials: interactive > service principal > error
  - Environment filtering: Match PQL_ENVIRONMENT or "default" suffix
}
```

### Skill Componentization

**Threshold**: Skills under 300 lines should remain single-file. Only componentize if a skill exceeds this limit.

**Rationale**: Small skills are easier to install and maintain. Componentization adds complexity without benefit for short files.

### Installing Skills to Harnesses

Skills can be installed to any AI assistant harness:

```bash
pql-test skill --install claude       # .claude/skills/pql-test/
pql-test skill --install copilot      # .github/copilot-instructions.md
pql-test skill --install cursor       # .cursor/skills/pql-test/
pql-test skill --install windsurf     # .windsurf/skills/pql-test/
pql-test skill --all                  # Install to all harnesses
pql-test skill --show                 # Show install status
pql-test skill --uninstall            # Remove from all harnesses
```

Each install adds a version marker comment for tracking:
```markdown
<!-- pql-test skills v0.1.13 installed by pql-test CLI -->
```

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
5. Bump the version if shipping user-visible changes — follow
   [aidd-custom/skills/pql-test-version-bump/SKILL.md](aidd-custom/skills/pql-test-version-bump/SKILL.md)
   (`pyproject.toml`, `plugin.json`, and every SKILL.md move together)

---

## Releasing a new version to PyPI

Releases are tag-driven and published via PyPI's trusted-publishing OIDC flow
in [release.yml](.github/workflows/release.yml) — no API tokens are stored
anywhere in the repo.

**One-time setup (already done for the initial release):**
- A "trusted publisher" is registered at
  https://pypi.org/manage/account/publishing/ with this repo
  (`clientfirsttech/pql-test`), workflow name `release.yml`, and the
  Environment-name field left **blank**.  An equivalent publisher exists on
  TestPyPI.
- No GitHub Environments are required.  (They need a paid plan on private
  repos; trusted publishing works without them.  If you later want a
  manual-approval gate on production releases, add a `pypi` environment and
  wire it into `release.yml` + the PyPI publisher config — see the NOTE in
  that workflow file.)

**Per-release checklist:**

1. Bump the version per [PEP 440](https://peps.python.org/pep-0440/) / semver
   in [python/pyproject.toml](python/pyproject.toml), [plugin.json](plugin.json),
   and every source + packaged SKILL.md — see
   [aidd-custom/skills/pql-test-version-bump/SKILL.md](aidd-custom/skills/pql-test-version-bump/SKILL.md).
   `tests/test_version_alignment.py` and the validate-plugin workflow fail on drift.
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
