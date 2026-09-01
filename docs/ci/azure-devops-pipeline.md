# Azure DevOps Pipeline for pql-test

Run [pql-test](https://github.com/clientfirsttech/pql-test) DAX unit tests
against a Microsoft Fabric / Power BI Premium workspace from an Azure DevOps
pipeline.

The pipeline YAML lives beside this doc:
[azure-devops-pipeline.yml](azure-devops-pipeline.yml). It is a single
self-contained file — no template references, task groups, or script files.

---

## Prerequisites

1. **Fabric / Power BI Premium capacity** with the **XMLA endpoint set to
   Read/Write** in the workspace settings.
2. **Azure AD service principal** with:
   - a client secret you can retrieve
   - **Member** (or higher) access to the target workspace
   - the tenant setting *"Allow service principals to use Power BI APIs"* enabled
3. **Windows self-hosted agent** or the Microsoft-hosted `windows-latest`
   pool. ADOMD.NET / pyadomd is Windows/.NET only — a Linux or macOS agent
   will not work.
4. **DAX test files** named `<Name>.<TAG>.Tests.dax` in the semantic model's
   `DAXQueries/` folder (e.g. `Calcs.DEV.Tests.dax`,
   `BestPractices.ANY.Tests.dax`). Test discovery filters on the tag.

---

## 1. Create a variable group

Pipelines → **Library** → **+ Variable group** → name it `pql-test-spn`, then
add:

| Variable | Value | Secret? |
| --- | --- | --- |
| `PQL_TENANT_ID` | Azure AD tenant GUID | No |
| `PQL_CLIENT_ID` | Service principal app (client) ID | No |
| `PQL_CLIENT_SECRET` | Service principal secret | **Yes** |
| `PQL_ENVIRONMENT` | `Public`, `USGov`, `USGovHigh`, `DOD`, `Germany`, `China` (optional; defaults to `Public`) | No |

**Key Vault variant (recommended for production):** on the same variable
group, toggle *"Link secrets from an Azure key vault as variables"*, connect
your Key Vault, and add the four names above. The pipeline works unchanged.

If you rename the variable group, update the `variables: - group: pql-test-spn`
line in [azure-devops-pipeline.yml](azure-devops-pipeline.yml).

---

## 2. Grant the service principal workspace access

In the Fabric portal, open the target workspace → **Manage access** → add the
service principal by name → assign **Member** (minimum) or **Admin**. Repeat
for every workspace this pipeline should be able to reach.

---

## 3. Add the pipeline YAML to your repo

Download or copy [azure-devops-pipeline.yml](azure-devops-pipeline.yml) into
your repo (any path, any name — `azure-pipelines.yml` at the repo root is the
Azure DevOps convention). Then in Azure DevOps:

**Pipelines** → **New pipeline** → point at that file → **Save**.

Nothing else in the file references paths outside itself, so you can rename
or relocate it freely.

---

## 4. Run the pipeline

Pipelines → select the pipeline → **Run pipeline** → fill in:

| Parameter | Example |
| --- | --- |
| `Fabric workspace name` | `Finance Reporting` |
| `Semantic model name` | *(blank)* to test every model, or `Sales Star` |
| `Test-tag environment` | *(blank)* for `ANY` + `PROD`, or `DEV` / `UAT` |

Results appear as:

- **Job log** — grouped output per `(model, env)` pair with ADO logging
  commands (`##[group]`, `##[section]`, `##vso[task.logissue]`) emitted by
  the pipeline itself and by `pql-test --log-format azuredevops`.
- **Run summary tab** — a markdown table listing every `(model, env)`
  combination with pass / fail / total / exit-code columns, uploaded via
  `##vso[task.uploadsummary]`.
- **Artifact** `dax-results` — the raw JSON output files from every
  `pql-test run-tests` invocation.

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

## Logging conventions used

| Situation | Command emitted |
| --- | --- |
| Validation error, dataset-not-found, failing test aggregate | `##vso[task.logissue type=error]…` |
| No tests executed anywhere | `##vso[task.logissue type=warning]…` |
| Per-model run grouping | `##[group]` / `##[endgroup]` |
| Section headers | `##[section]…` |
| Markdown summary | `##vso[task.uploadsummary]<path>` |
| Per-test pass/fail annotations | emitted by `pql-test --log-format azuredevops` |

---

## Troubleshooting

- **`fab auth login` fails with `AADSTS...`** — the service principal secret is
  expired or the SPN is not permitted to sign in. Rotate the secret in Azure
  AD and update `PQL_CLIENT_SECRET` in the variable group.
- **`Service principal cannot see workspace 'X'`** — add the SPN to the
  workspace with **Member** or higher, and confirm the tenant setting
  *"Allow service principals to use Power BI APIs"* is on for a security
  group the SPN belongs to.
- **`Semantic model 'X' not found in workspace 'Y'`** — the model must exist
  in the workspace as a Fabric `SemanticModel` item. Deployed reports without
  a semantic model do not count.
- **`ADOMD.NET NuGet install failed`** — usually a transient nuget.org
  outage; re-run the pipeline. If persistent, install ADOMD.NET into your
  self-hosted agent image and remove that step.
- **All results show `0 total`** — a warning annotation will fire. The usual
  cause is a `--env` tag no test file uses. Rename a file to
  `<Name>.ANY.Tests.dax` if you want it to run under every tag.

---

## Notes

- The pipeline pins nothing except the ADOMD.NET NuGet version (`19.114.0`) —
  `pql-test` and `ms-fabric-cli` install as **latest** on each run. Add
  `==<version>` in the `pip install` line to pin.
- Dataset GUIDs are not required and are never stored. `pql-test` resolves
  the dataset by display name via the Power BI REST API at run time.
