---
name: run-tests
description: Execute all DAX test suites in a PBIP semantic model against the XMLA endpoint. Connects to a locally-open Power BI Desktop instance or to a remote Power BI Premium / Fabric workspace.
version: 0.1.14
---

Run `pql-test run-tests MODEL_PATH` to execute all DAX test suites found in a Power BI Project (PBIP) semantic model and report results in a pytest-style format.

## Behavioral Contract

```sudolang
Interface RunTests {
  exit_code: 0 | 1
    // 0 = all tests passed
    // 1 = one or more tests failed
  
  output_format: "pytest-style" | "json"
    // pytest-style: human-readable console output (default)
    // json: structured output when --output specified
  
  log_annotations: null | "github" | "azuredevops"
    // github: ::group::, ::error::, ::notice::
    // azuredevops: ##[group], ##[error], ##vso[task.complete]
}

Constraints {
  // MODEL_PATH resolution order
  local/<name> => connect to running Power BI Desktop instance
  <workspace>.Workspace/<model>.SemanticModel => remote Fabric path
  <filesystem_path> => local PBIP directory
  
  // Credential precedence
  CLI flags (--tenant-id, --client-id, --client-secret) >
  PQL_* environment variables >
  Stored auth login credentials (keyring)
  
  // Environment filtering
  When --env specified: only run *.{ENV}.Tests suites
  PQL_TEST_ENV environment variable also supported
}
```

## MODEL_PATH Formats

## MODEL_PATH Formats

MODEL_PATH accepts three formats:
- **Filesystem path** — the PBIP root directory containing the `.pbip` file and `.SemanticModel` sub-folder (or the `.SemanticModel` directory itself).
- **`local/<model_name>`** — connect to a locally-open Power BI Desktop instance by model name, without requiring a local file path. Useful when test files are defined in the model's `functions.tmdl` and may not exist locally.
- **`<workspace>.Workspace/<semantic_model>.SemanticModel`** — canonical Fabric service path (matches Fabric's own filesystem layout). Connect to a remote workspace by display names (requires `--tenant-id`, `--client-id`, `--client-secret`, or a stored interactive login via `pql-test auth login`).

The command auto-detects a locally-open Power BI Desktop instance via the Analysis Services port file, or connects to a remote Power BI Premium / Microsoft Fabric XMLA endpoint when `--tenant-id`, `--workspace-id`, and `--dataset-id` are supplied.

Options:
- `--test NAME` — Run only the named test suite.
- `--verbose` — Show per-assertion detail (message and duration) for every result.
- `--output FILE` — Write full JSON results to FILE in addition to the human-readable output.
- `--log-format github` — Emit GitHub Actions native log annotations (`::group::` / `::error::` / `::notice::`).
- `--log-format azuredevops` — Emit Azure Pipelines logging commands (`##[group]` / `##[error]` / `##vso[task.complete]`).
- `--tenant-id ID` — Azure AD tenant ID (or set `PQL_TENANT_ID` env var).
- `--workspace-id ID` — Power BI workspace GUID (or set `PQL_WORKSPACE_ID` env var).
- `--dataset-id ID` — Dataset / semantic model GUID (or set `PQL_DATASET_ID` env var).
- `--client-id ID` — Service principal client ID (or set `PQL_CLIENT_ID` env var).
- `--client-secret SECRET` — Service principal client secret (or set `PQL_CLIENT_SECRET` env var).
- `--env ENV` — Run only test suites for this environment (e.g. `DEV`, `PROD`, `ANY`, `BKUP`), matching the `<Suite>.<ENV>.Tests` naming convention (or set `PQL_TEST_ENV` env var).

The Power BI cloud environment (`Public`, `USGov`, `China`, …) is not a flag: it comes from the credential stored by `pql-test auth login --environment`, or from the `PQL_ENVIRONMENT` env var when explicit service-principal credentials are supplied. Default: `Public`.

Exit codes: `0` = all tests passed, `1` = one or more tests failed.

Usage:
```
# Run tests against SampleModel (general testing)
pql-test run-tests ../examples/SampleModel
pql-test run-tests local/SampleModel
pql-test run-tests "MyWorkspace.MyModel" --tenant-id ... --client-id ... --client-secret ...
pql-test run-tests ../examples/SampleModel.SemanticModel --output results.json
pql-test run-tests ../examples/SampleModel.SemanticModel --log-format github
pql-test run-tests ../examples/SampleModel.SemanticModel --log-format azuredevops

# Run tests against RLS_Model (Row-Level Security testing)
pql-test run-tests ../examples/RLS_Model.SemanticModel \
  --tenant-id $PQL_TENANT_ID \
  --workspace-id $PQL_WORKSPACE_ID \
  --dataset-id $PQL_DATASET_ID_RLS \
  --client-id $PQL_CLIENT_ID \
  --client-secret $PQL_CLIENT_SECRET

# Run tests against OLS_Model (Object-Level Security testing)  
pql-test run-tests ../examples/OLS_Model.SemanticModel \
  --tenant-id $PQL_TENANT_ID \
  --workspace-id $PQL_WORKSPACE_ID \
  --dataset-id $PQL_DATASET_ID_OLS \
  --client-id $PQL_CLIENT_ID \
  --client-secret $PQL_CLIENT_SECRET

# General remote connection example
pql-test run-tests ../examples \
  --tenant-id $PQL_TENANT_ID \
  --workspace-id $PQL_WORKSPACE_ID \
  --dataset-id $PQL_DATASET_ID \
  --client-id $PQL_CLIENT_ID \
  --client-secret $PQL_CLIENT_SECRET
```
