---
name: retrieve-test
description: Show details for a single DAX test suite by name. Returns a JSON object by default; use --human for formatted text and --verbose to include the full DAX source.
version: 0.1.17
---

Run `pql-test retrieve-test MODEL_PATH NAME` to fetch the definition of a specific DAX test suite from a Power BI Project (PBIP) semantic model.

MODEL_PATH accepts three formats:
- **Filesystem path** — the PBIP root directory containing the `.pbip` file and `.SemanticModel` sub-folder (or the `.SemanticModel` directory itself).
- **`local/<model_name>`** — connect to a locally-open Power BI Desktop instance by model name.
- **`<workspace>.Workspace/<semantic_model>.SemanticModel`** — canonical Fabric service path (matches Fabric's own filesystem layout). Requires `--tenant-id`, `--client-id`, `--client-secret`, or a stored interactive login via `pql-test auth login`.

NAME is the exact name of the DAX test suite to retrieve (e.g. `Calcs.DEV.Tests`).

Options:
- `--human` — Output in human-readable formatted text instead of JSON.
- `--verbose` — With `--human`: also print the full DAX source of the test suite. With JSON output: adds a `"source"` field to the returned object.
- `--tenant-id ID` — Azure AD tenant ID (or set `PQL_TENANT_ID` env var).
- `--workspace-id ID` — Power BI workspace GUID (or set `PQL_WORKSPACE_ID` env var).
- `--dataset-id ID` — Dataset / semantic model GUID (or set `PQL_DATASET_ID` env var).
- `--client-id ID` — Service principal client ID (or set `PQL_CLIENT_ID` env var).
- `--client-secret SECRET` — Service principal client secret (or set `PQL_CLIENT_SECRET` env var).

The Power BI cloud environment (`Public`, `USGov`, `China`, …) is not a flag: it comes from the credential stored by `pql-test auth login --environment`, or from the `PQL_ENVIRONMENT` env var when explicit service-principal credentials are supplied. Default: `Public`.

Usage:
```
pql-test retrieve-test ../examples "Calcs.DEV.Tests"
pql-test retrieve-test local/SampleModel "Calcs.DEV.Tests"
pql-test retrieve-test "MyWorkspace.MyModel" "Calcs.DEV.Tests" --tenant-id ... --client-id ... --client-secret ...
pql-test retrieve-test ../examples "Calcs.DEV.Tests" --human
pql-test retrieve-test ../examples "Calcs.DEV.Tests" --human --verbose
```
