---
name: pql-odcs
description: Turn an ODCS (Open Data Contract Standard) v3.0–v3.2 data contract into PQL.Assert DAX test suites for a Power BI / Fabric PBIP semantic model with the standalone `pql-odcs` CLI. Use when a user wants to enforce a data contract's quality rules in a semantic model, check which contract rules can be enforced, check a model's PQL.Assert readiness, or map test results back to contract rule ids.
version: 0.1.0
---

# pql-odcs

`pql-odcs` reads an ODCS data contract and writes PQL.Assert `*.Tests.dax` suites into a PBIP model's `DAXQueries/` folder. Every contract rule is reported as **mapped** (checked exactly), **approximated** (checked, with a stated difference), or **skipped** (with the reason and the release that will add it). No rule is dropped silently. It runs on Windows, macOS, and Linux, and never connects to a model. To run the suites, use `pql-test contract run` from pql-test (`pip install pql-test[contracts]`, Windows only).

## Behavioral Contract

```sudolang
PqlOdcs {
  Constraints {
    Run `pql-odcs doctor MODEL_PATH` before the first generate for a model, and use the --pql-assert value it recommends.
    Never hand-edit generated suites: change the contract and regenerate. Generated files carry a pql-odcs header.
    Only pass --force when the user confirms that the named suite files may be overwritten.
    Report skipped and approximated rules to the user with their reasons; never present them as enforced.
    Model table and column names come only from the contract's customProperties: pbiTable on a schema object, pbiColumn on a property. Without them the ODCS name is used.
  }
}
```

## Workflow

1. Check readiness: `pql-odcs doctor ./MyModel`. It reports the PQL.Assert version in the model's `definition/functions.tmdl` and recommends `--pql-assert 0.7` or `0.8`. A model without PQL.Assert needs it installed from DAX Lib first.
2. Validate the contract against the model: `pql-odcs lint orders.odcs.yaml --model ./MyModel`. This catches schema errors and names that do not exist in the model.
3. See what will be enforced: `pql-odcs coverage orders.odcs.yaml --pql-assert 0.8`. Add `--format json` for tooling, or `--fail-on-skipped` for strict CI.
4. Write the suites: `pql-odcs generate orders.odcs.yaml ./MyModel --env DEV --pql-assert 0.8`. Use `--dry-run` to print the DAX instead, or `--pql-assert auto` to take the version from the model folder.
5. Run them with pql-test (`pql-test contract run orders.odcs.yaml ./MyModel --env DEV`), or with any runner that writes pql-test's `--output` JSON.
6. Map results back to rule ids: `pql-odcs trace orders.odcs.yaml results.json --pql-assert 0.8`. Use the same `--pql-assert` and `--suite-prefix` as at generate time.

## Commands

| Command | Purpose |
|---|---|
| `doctor [MODEL_PATH]` | Environment checks; with a model, its PQL.Assert library and the recommended `--pql-assert`. Exits 1 when a check fails. |
| `lint CONTRACT [--model MODEL_PATH]` | Schema-validate the contract and check its names resolve (in the model, when given). |
| `coverage CONTRACT` | List every rule as mapped, approximated, or skipped. |
| `generate CONTRACT MODEL_PATH --env ENV` | Write `<Prefix>.Schema.<ENV>.Tests.dax` and `<Prefix>.DataQuality.<ENV>.Tests.dax`. Warning-severity rules go to `<ENV>WARN` suites, which report but do not fail a run. |
| `trace CONTRACT RESULTS_JSON` | Join a pql-test results file back to contract rule ids. |
| `skill` | Print, install, or remove this skill for an AI coding agent. |

`MODEL_PATH` is a PBIP root, a `*.SemanticModel` folder, or a `.pbip` file. `--closed-schema` also fails a table that has columns the contract does not list.

## PQL.Assert versions

- `--pql-assert 0.7` (the default) works with PQL.Assert 0.7.x and later. Some rules are approximated, for example `required` on a text column also counts empty strings as missing.
- `--pql-assert 0.8` needs PQL.Assert 0.8.0 or later in the model. Null, key, duplicate, `rowCount mustNotBeBetween`, and simple pattern rules (`^literal`, `literal$`, or a bare literal, matched case-sensitively) then map exactly, and a `latency` SLA becomes an approximated freshness check. Suites generated for 0.8 fail on a model that still has 0.7.
- Column types, value ranges, value lists, `missingValues`, and relationships are skipped in this release.

## Exit codes

`0` success; `1` invalid contract, lint problems, a failed doctor check, or `--fail-on-skipped` triggered; `2` usage error, such as a bad option, a MODEL_PATH that is not PBIP, or a suite file pql-odcs did not generate.
