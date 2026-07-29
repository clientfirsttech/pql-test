---
name: retrieve-tests
description: List all DAX test suites (*.Tests.dax files) found in a PBIP semantic model's DAXQueries/ folder. Returns a JSON array by default.
---

Run `pql-test retrieve-tests MODEL_PATH` to discover all DAX test suites stored in a Power BI Project (PBIP) semantic model.

MODEL_PATH accepts three formats:
- **Filesystem path** — the PBIP root directory containing the `.pbip` file and `.SemanticModel` sub-folder (or the `.SemanticModel` directory / `.pbip` file directly).
- **`local/<model_name>`** — connect to a locally-open Power BI Desktop instance by model name, without requiring a local file path.
- **`<workspace>.Workspace/<semantic_model>.SemanticModel`** — canonical Fabric service path (matches Fabric's own filesystem layout). Connect to a remote workspace by display names (requires `--tenant-id`, `--client-id`, `--client-secret`, or a stored interactive login via `pql-test auth login`).

Options:
- `--test NAME` — Show only the named test suite.
- `--human` — Output in human-readable formatted text instead of JSON.
- `--verbose` — With `--human`: also show file paths and the resolved XMLA connection.
- `--tenant-id ID` — Azure AD tenant ID (or set `PQL_TENANT_ID` env var).
- `--workspace-id ID` — Power BI workspace GUID (or set `PQL_WORKSPACE_ID` env var).
- `--dataset-id ID` — Dataset / semantic model GUID (or set `PQL_DATASET_ID` env var).
- `--client-id ID` — Service principal client ID (or set `PQL_CLIENT_ID` env var).
- `--client-secret SECRET` — Service principal client secret (or set `PQL_CLIENT_SECRET` env var).
- `--env ENV` — List only test suites for this environment (e.g. `DEV`, `PROD`, `ANY`, `BKUP`), matching the `<Suite>.<ENV>.Tests` naming convention (or set `PQL_TEST_ENV` env var).

The Power BI cloud environment (`Public`, `USGov`, `China`, …) is not a flag: it comes from the credential stored by `pql-test auth login --environment`, or from the `PQL_ENVIRONMENT` env var when explicit service-principal credentials are supplied. Default: `Public`.

Usage:
```
# Retrieve tests from SampleModel
pql-test retrieve-tests ../examples/SampleModel
pql-test retrieve-tests local/SampleModel
pql-test retrieve-tests "MyWorkspace.MyModel" --tenant-id ... --client-id ... --client-secret ...
pql-test retrieve-tests ../examples/SampleModel.SemanticModel --human
pql-test retrieve-tests ../examples --test "Calcs.DEV.Tests" --human --verbose

# Retrieve tests from RLS_Model (Row-Level Security)
pql-test retrieve-tests ../examples/RLS_Model.SemanticModel \
  --human \
  --tenant-id $PQL_TENANT_ID \
  --workspace-id $PQL_WORKSPACE_ID \
  --dataset-id $PQL_DATASET_ID_RLS \
  --client-id $PQL_CLIENT_ID \
  --client-secret $PQL_CLIENT_SECRET

# Retrieve tests from OLS_Model (Object-Level Security)
pql-test retrieve-tests ../examples/OLS_Model.SemanticModel \
  --human --verbose \
  --tenant-id $PQL_TENANT_ID \
  --workspace-id $PQL_WORKSPACE_ID \
  --dataset-id $PQL_DATASET_ID_OLS \
  --client-id $PQL_CLIENT_ID \
  --client-secret $PQL_CLIENT_SECRET
```
