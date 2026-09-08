# GitHub Actions Pipeline for pql-test

Run [pql-test](https://github.com/clientfirsttech/pql-test) DAX unit tests
against a Microsoft Fabric / Power BI Premium workspace from GitHub Actions.

The workflow file is fully self-contained — no composite actions, no
reusable-workflow references, no shell scripts on disk. Copy it into
`.github/workflows/`, add three secrets, and dispatch it.

---

## Prerequisites

1. **Fabric / Power BI Premium capacity** with the **XMLA endpoint set to
   Read/Write** in the workspace settings.
2. **Azure AD service principal** with:
   - a client secret you can retrieve
   - **Member** (or higher) access to the target workspace
   - the tenant setting *"Allow service principals to use Power BI APIs"* enabled
3. **GitHub-hosted `windows-latest` runner** (or a self-hosted Windows
   runner). ADOMD.NET / pyadomd is Windows/.NET only — a Linux or macOS
   runner will not work.
4. **DAX test files** named `<Name>.<TAG>.Tests.dax` in the semantic model's
   `DAXQueries/` folder (e.g. `Calcs.DEV.Tests.dax`,
   `BestPractices.ANY.Tests.dax`). Test discovery filters on the tag.

---

## 1. Add secrets

Repository → **Settings** → **Secrets and variables** → **Actions** →
**New repository secret**:

| Secret | Value |
| --- | --- |
| `PQL_TENANT_ID` | Azure AD tenant GUID |
| `PQL_CLIENT_ID` | Service principal application (client) ID |
| `PQL_CLIENT_SECRET` | Service principal secret |
| `PQL_ENVIRONMENT` *(optional)* | `Public`, `USGov`, `USGovHigh`, `DOD`, `Germany`, or `China`. Defaults to `Public`. |

**Environment-scoped variant:** if you already use GitHub Environments (e.g.
`prod`, `uat`), create the secrets under each environment and add
`environment:` to the `run:` job in the workflow.

---

## 2. Grant the service principal workspace access

In the Fabric portal, open the target workspace → **Manage access** → add the
service principal by name → assign **Member** (minimum) or **Admin**. Repeat
for every workspace this workflow should be able to reach.

---

## 3. Copy the workflow

The workflow file lives at
[.github/workflows/pql-test-remote.yml](../../.github/workflows/pql-test-remote.yml)
in this repo. To adopt it in your own repo, copy that single file into your
own `.github/workflows/` directory — nothing else is required.

---

## 4. Run the workflow

Actions → **pql-test (remote workspace)** → **Run workflow** → fill in:

| Input | Example |
| --- | --- |
| `workspace_name` (required) | `Finance Reporting` |
| `dataset_name` (optional) | *(blank)* to test every semantic model in the workspace, or `Sales Star` |
| `environment` (optional) | *(blank)* for `ANY` + `PROD`, or `DEV` / `UAT` |

Results appear as:

- **Job log** annotations (`::error::`, `::warning::`, `::notice::`, and
  grouped output per `(model, env)` pair) — emitted both by the workflow
  itself and by `pql-test --log-format github`.
- **Step summary** — a markdown table on the run's summary page listing
  each `(model, env)` combo with pass / fail / total / exit-code columns.
- **Artifact** `dax-results` — the raw JSON output files from every
  `pql-test run-tests` invocation.

---

## Calling the workflow from another workflow

Because the workflow is defined with `workflow_call`, you can invoke it from
another workflow (e.g. after a Fabric deployment step succeeds):

```yaml
jobs:
  deploy:
    # ... your deploy steps ...

  test:
    needs: deploy
    uses: ./.github/workflows/pql-test-remote.yml
    with:
      workspace_name: Finance Reporting
      dataset_name:   Sales Star     # optional
      environment:    UAT            # optional
    secrets:
      PQL_TENANT_ID:     ${{ secrets.PQL_TENANT_ID }}
      PQL_CLIENT_ID:     ${{ secrets.PQL_CLIENT_ID }}
      PQL_CLIENT_SECRET: ${{ secrets.PQL_CLIENT_SECRET }}
      PQL_ENVIRONMENT:   ${{ secrets.PQL_ENVIRONMENT }}
```

---

## Logging conventions used

| Situation | Command emitted |
| --- | --- |
| Validation error, dataset-not-found, failing test aggregate | `::error title=…::…` |
| No tests executed anywhere | `::warning title=…::…` |
| Workspace / dataset validated | `::notice title=…::…` |
| Per-model run grouping | `::group::…` / `::endgroup::` |
| Per-test pass/fail annotations | emitted by `pql-test --log-format github` |
| Run-level summary | markdown written to `$GITHUB_STEP_SUMMARY` |

---

## Behavior at a glance

- **Two runs per model, always** — one `--env ANY`, one `--env <PROD|value>`.
  If the same tag is supplied twice (e.g. `environment: ANY`) the duplicate
  is dropped so the model runs once.
- **Missing tests for a specific tag** — silent. A model with no
  `*.ANY.Tests.dax` will simply run its other tag; no warning is raised.
- **Zero tests executed across every combination** — a single warning
  annotation is emitted at the end. This catches a common misconfiguration
  where all filenames use a tag you didn't request.
- **Case-insensitive workspace + dataset match** — Fabric enforces
  case-insensitive uniqueness for item names, so `sales` and `Sales` cannot
  coexist in one workspace.

---

## Troubleshooting

- **`Fabric CLI login failed`** — the service principal secret is expired or
  the SPN is not permitted to sign in. Rotate the secret in Azure AD and
  update `PQL_CLIENT_SECRET`.
- **`Service principal cannot see workspace 'X'`** — add the SPN to the
  workspace with **Member** or higher, and confirm the tenant setting
  *"Allow service principals to use Power BI APIs"* is on for a security
  group the SPN belongs to.
- **`Semantic model 'X' not found in workspace 'Y'`** — the item must exist
  in the workspace as a Fabric `SemanticModel`. Deployed reports without a
  semantic model do not count.
- **`ADOMD.NET NuGet install failed`** — usually a transient nuget.org
  outage; re-run the workflow. If persistent, bake ADOMD.NET into a custom
  runner image and drop that step.
- **All results show `0 total`** — a warning annotation will fire. The
  usual cause is a `--env` tag no test file uses. Rename a file to
  `<Name>.ANY.Tests.dax` if you want it to run under every tag.
