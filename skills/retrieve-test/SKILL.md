---
name: retrieve-test
description: Show details for a single DAX test suite by name. Returns a JSON object by default; use --human for formatted text and --verbose to include the full DAX source.
---

Run `pql-test retrieve-test MODEL_PATH NAME` to fetch the definition of a specific DAX test suite from a Power BI Project (PBIP) semantic model.

MODEL_PATH is the PBIP root directory containing the `.pbip` file and the `.SemanticModel` sub-folder, or the `.SemanticModel` directory itself.

NAME is the exact name of the DAX test suite to retrieve (e.g. `Calcs.DEV.Tests`).

Options:
- `--human` — Output in human-readable formatted text instead of JSON.
- `--verbose` — With `--human`: also print the full DAX source of the test suite. With JSON output: adds a `"source"` field to the returned object.

Usage:
```
pql-test retrieve-test ../examples "Calcs.DEV.Tests"
pql-test retrieve-test ../examples "Calcs.DEV.Tests" --human
pql-test retrieve-test ../examples "Calcs.DEV.Tests" --human --verbose
```
