---
name: run-tests
description: Execute all DAX test suites in a PBIP semantic model against the XMLA endpoint. Connects to a locally-open Power BI Desktop instance or to a remote Power BI Premium / Fabric workspace.
---

Run `pql-test run-tests MODEL_PATH` to execute all DAX test suites found in a Power BI Project (PBIP) semantic model and report results in a pytest-style format.

MODEL_PATH is the PBIP root directory containing the `.pbip` file and the `.SemanticModel` sub-folder, or the `.SemanticModel` directory itself.

The command auto-detects a locally-open Power BI Desktop instance via the Analysis Services port file, or connects to a remote Power BI Premium / Microsoft Fabric XMLA endpoint when `--tenant-id`, `--workspace-id`, and `--dataset-id` are supplied.

Options:
- `--test NAME` — Run only the named test suite.
- `--verbose` — Show per-assertion detail (message and duration) for every result.
- `--output FILE` — Write full JSON results to FILE in addition to the human-readable output.
- `--log-format github` — Emit GitHub Actions native log annotations (`::group::` / `::error::` / `::notice::`).
- `--log-format azuredevops` — Emit Azure Pipelines logging commands (`##[group]` / `##[error]` / `##vso[task.complete]`).
- `--local` — Detect and connect to a locally open Power BI Desktop instance (requires psutil).
- `--tenant-id ID` — Azure AD tenant ID (or set `PQL_TENANT_ID` env var).
- `--workspace-id ID` — Power BI workspace GUID (or set `PQL_WORKSPACE_ID` env var).
- `--dataset-id ID` — Dataset / semantic model GUID (or set `PQL_DATASET_ID` env var).
- `--client-id ID` — Service principal client ID (or set `PQL_CLIENT_ID` env var).
- `--client-secret SECRET` — Service principal client secret (or set `PQL_CLIENT_SECRET` env var).
- `--environment ENV` — Cloud environment: `Public` (default), `Germany`, `China`, `USGov`, `USGovHigh`, or `DOD` (or set `PQL_ENVIRONMENT` env var).

Exit codes: `0` = all tests passed, `1` = one or more tests failed.

Usage:
```
pql-test run-tests ../examples
pql-test run-tests ../examples/SampleModel.SemanticModel --local
pql-test run-tests ../examples/SampleModel.SemanticModel --output results.json
pql-test run-tests ../examples/SampleModel.SemanticModel --log-format github
pql-test run-tests ../examples/SampleModel.SemanticModel --log-format azuredevops
pql-test run-tests ../examples \
  --tenant-id $PQL_TENANT_ID \
  --workspace-id $PQL_WORKSPACE_ID \
  --dataset-id $PQL_DATASET_ID \
  --client-id $PQL_CLIENT_ID \
  --client-secret $PQL_CLIENT_SECRET
```
