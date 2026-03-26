---
name: retrieve-tests
description: List all DAX test suites (*.Tests.dax files) found in a PBIP semantic model's DAXQueries/ folder. Returns a JSON array by default.
---

Run `pql-test retrieve-tests MODEL_PATH` to discover all DAX test suites stored in a Power BI Project (PBIP) semantic model.

MODEL_PATH is the PBIP root directory — the folder that contains the `.pbip` file and the `.SemanticModel` sub-folder. You may also pass the `.SemanticModel` directory or the `.pbip` file directly.

Options:
- `--test NAME` — Show only the named test suite.
- `--human` — Output in human-readable formatted text instead of JSON.
- `--verbose` — With `--human`: also show file paths and the resolved XMLA connection.
- `--tenant-id ID` — Azure AD tenant ID (or set `PQL_TENANT_ID` env var).
- `--workspace-id ID` — Power BI workspace GUID (or set `PQL_WORKSPACE_ID` env var).
- `--dataset-id ID` — Dataset / semantic model GUID (or set `PQL_DATASET_ID` env var).
- `--client-id ID` — Service principal client ID (or set `PQL_CLIENT_ID` env var).
- `--client-secret SECRET` — Service principal client secret (or set `PQL_CLIENT_SECRET` env var).
- `--environment ENV` — Cloud environment: `Public` (default), `Germany`, `China`, `USGov`, `USGovHigh`, or `DOD` (or set `PQL_ENVIRONMENT` env var).

Usage:
```
pql-test retrieve-tests ../examples
pql-test retrieve-tests ../examples/SampleModel.SemanticModel --human
pql-test retrieve-tests ../examples --test "Calcs.DEV.Tests" --human --verbose
```
