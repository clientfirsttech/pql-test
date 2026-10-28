# ODCS data contracts: `pql-test contract`

Generate [PQL.Assert](https://github.com/clientfirsttech/PQL.Assert) DAX test suites from [ODCS](https://bitol-io.github.io/open-data-contract-standard/) v3.0, v3.1, and v3.2 data contracts, run them, and trace every result back to its contract rule. Every contract rule is reported as **mapped**, **approximated**, or **skipped**, so nothing is dropped silently.

The commands come with pql-test (`pip install pql-test`). `lint`, `coverage`, `generate`, and `trace` only read and write files, so they also run on Linux, for example in a CI pipeline. `run`, and `doctor`'s live checks, need XMLA, which is Windows-only.

## Quick start

```bash
pql-test contract doctor ./SalesModel                                   # which PQL.Assert? which --pql-assert?
pql-test contract coverage orders.odcs.yaml                             # which rules can be enforced?
pql-test contract lint orders.odcs.yaml ./SalesModel                    # contract valid, names resolve?
pql-test contract generate orders.odcs.yaml ./SalesModel --env DEV      # write *.Tests.dax suites
pql-test contract run orders.odcs.yaml ./SalesModel --env DEV --output results.json  # generate, run, trace
pql-test contract trace orders.odcs.yaml results.json                   # failures by contract rule id
```

`pql-test contract run` runs the generated suites from their files. `pql-test run-tests` runs the suites registered in the deployed model, so it sees generated suites only after the model is published.

## Commands

| Command | What it does |
|---|---|
| `generate CONTRACT MODEL_PATH --env ENV` | Writes `<Prefix>.<Suite>.<ENV>.Tests.dax` into the PBIP model's `DAXQueries/` folder |
| `coverage CONTRACT [--format text\|json]` | Lists every rule with its status, generated function(s), and skip reason |
| `lint CONTRACT [MODEL_PATH]` | Validates against the bundled ODCS JSON schema, then checks that names resolve and (with a MODEL_PATH) that every table and column exists in the model's TMDL |
| `run CONTRACT MODEL_PATH --env ENV` | Generates the suites, runs them over XMLA, and traces the results to rule ids (`--output`, `--log-format azuredevops\|github`, and the `run-tests` connection options) |
| `trace CONTRACT RESULTS_JSON` | Joins pql-test `--output` JSON to rule ids: passed, failed, error, not executed, or skipped |
| `doctor [MODEL_PATH] [--format text\|json]` | Checks Python, the dependencies, and the bundled schemas and catalogs. With a PBIP model, reads its PQL.Assert library from `definition/functions.tmdl`, recommends the `--pql-assert` value whose every function the model defines, and checks the deployed or open model's library |

**MODEL_PATH** is the same in every command: the PBIP root containing the `.pbip` file, the `*.SemanticModel` folder, the `.pbip` file itself, or `local/<name>`, which means the one `<name>.SemanticModel` folder in this repository (searched from the git root). With `local/<name>`, `run` and `doctor` connect only to that model open in Power BI Desktop, even when `PQL_*` service credentials are set; pass `--model-dir` when the repository holds several copies. The `<workspace>.Workspace/<model>.SemanticModel` form of `run-tests` is not accepted yet.

**Shared flags**:
- `--closed-schema` also forbids columns the contract does not list.
- `--fail-on-skipped` exits 1 if any rule is skipped (`generate`, `coverage`).
- `--pql-assert 0.7|0.8` picks the PQL.Assert version to generate for (`generate`, `coverage`, `trace`; default `0.7`). `generate` also takes `auto`, which reads the model folder the way `doctor` does, and `run` defaults to `auto`, which asks the model. See [PQL.Assert 0.8](#pql-assert-08).
- `--suite-prefix NAME` overrides the suite prefix (`generate`, `run`, `trace`).
- `--dry-run` prints the DAX instead of writing files (`generate`).
- `--force` overwrites suite files that pql-test did not generate (`generate`, `run`).

**Exit codes**:
- 0 means success.
- 1 means the contract is invalid, `lint` found problems, a `doctor` check failed, `--fail-on-skipped` was triggered, or (`run`) a blocking suite failed or nothing ran.
- 2 means a usage error: a bad `--env` token, a MODEL_PATH that is not a PBIP model, a file pql-test would refuse to overwrite, or an unreadable results file.

## Generated suites

- **Names**: `<Prefix>.<Suite>.<ENV>.Tests`. `Suite` is `Schema` (tables and columns) or `DataQuality` (everything else). The prefix is a PascalCase form of the contract's `dataProduct`, then its `name`, then its `id`. pql-test matches `ENV` as the second-to-last dotted token, so `pql-test run-tests --env DEV` picks the suites up.
- **Warning rules**: rules with `severity: warning` or `info` go into separate `<Prefix>.<Suite>.<ENV>WARN.Tests` suites. CI can run these without failing the build, and `pql-test contract run` never fails on them.
- **Test names**: `ODCS <contractId> <ruleId>: <description>`. The rule id is the ODCS `id` when it is unique in the contract; otherwise it is a stable path such as `orders.customer_id.quality[0]`. Descriptions use the contract's own names.
- **Header**: every file starts with `// Generated by pql-test <version> from <contract> — do not edit`, followed by a line naming the contract id. `generate` refuses to overwrite a hand-written file, or a suite generated from a **different contract** that has the same prefix, unless you pass `--force`. It deletes a suite only when this contract generated it in an earlier run and it no longer has any rules. Give two contracts that share a `dataProduct` distinct `--suite-prefix` values.
- **Line endings**: output is deterministic, with LF line endings, so the files can be committed and diffed.

The generated DAX calls PQL.Assert, which must be installed in the model, version 0.7.1 or later (DAX Lib). `--pql-assert 0.8` needs 0.8.0 or later.

## Commit the suites, or regenerate them in CI?

Both workflows are supported. Pick one per model repository.

| | Regenerate in CI | Commit to the PBIP repo |
|---|---|---|
| Source of truth | The contract alone | The contract, plus the generated files |
| Drift | Impossible: suites are rebuilt on every run | Possible, so CI must check for it (below) |
| Visible in Power BI Desktop's DAX query view | Only after a local `generate` | Yes |
| Published with the model (Fabric git integration) | No | Yes, as files in `DAXQueries/` |
| Counted by `pql-test code-coverage` | No | No: files in `DAXQueries/` are not model functions. A persistent deploy is planned. |
| Review | Review the contract | Review the contract and the DAX diff |

**Regenerate in CI.**
1. Don't commit the generated files. Ignore them by prefix, for example in `.gitignore`: `**/DAXQueries/Marvel.*.Tests.dax`.
2. In CI, run one step, which generates, runs and traces:
   ```bash
   pql-test contract run orders.odcs.yaml ./SalesModel --env DEV --output results.json --log-format github
   ```

**Commit to the PBIP repo.**
1. Run `pql-test contract generate … --env DEV` whenever the contract changes, and commit the output.
2. Add a CI step that fails when the committed suites are stale:
   ```bash
   pql-test contract generate orders.odcs.yaml ./SalesModel --env DEV
   git diff --exit-code -- '*/DAXQueries/*.Tests.dax'
   ```

Generated files carry the pql-test version in their header, so upgrading pql-test also shows up as a diff. Regenerate and commit after an upgrade. This check only reads and writes files, so it can run on a Linux runner.

Both workflows are safe to mix with hand-written suites in the same `DAXQueries/` folder. `generate` never overwrites a file it did not generate, or a suite generated from another contract.

## Name resolution

Each ODCS schema object maps to a semantic model table, and each property to a column. The model names live in the contract itself, using ODCS's own extension mechanism, `customProperties`. That keeps them valid on ODCS 3.0, 3.1 and 3.2, and keeps them with the contract wherever it goes:

```yaml
schema:
  - name: fact_marvel
    customProperties:
      - property: pbiTable          # semantic model table
        value: MarvelFact
    properties:
      - name: eye_id
        customProperties:
          - property: pbiColumn     # semantic model column
            value: EyeID
```

When `pbiTable` or `pbiColumn` is absent, the ODCS logical `name` is used unchanged. `lint CONTRACT MODEL_PATH` checks that every resolved table and column exists in the model's TMDL, and that each column's data type is one the contract accepts.

## Column types

Each property's `logicalType` becomes a `Tbl.ColumnDataTypeShouldBe` check in the Schema suite. It compares with the type the model reports in `INFO.VIEW.COLUMNS()`:

| ODCS `logicalType` | Model type (TMDL `dataType`) | Status |
|---|---|---|
| `string` | `Text` (`string`) | mapped |
| `integer` | `Integer` (`int64`) | mapped |
| `number` | `Number` (`double`) or `Currency` (`decimal`); an `Integer` (`int64`) column fails, so use `integer` or `pbiDataType` for whole numbers | mapped |
| `boolean` | `True/False` (`boolean`) | mapped |
| `date`, `timestamp`, `time` | `Date` (`dateTime`) | **approximated**: the model has one date/time type, so the check cannot tell a date column from a date/time one |

To check one exact model type, add a `pbiDataType` custom property to the property. Its value is one of `Text`, `Integer`, `Number`, `Currency`, `Date`, `True/False`, or `Binary`, in any case. The TMDL names (`string`, `int64`, `double`, `dateTime`, `boolean`, `binary`) work too, except `decimal`, which reads like Decimal Number but is `Currency`. `Binary` is the documented name but has not been seen in a model yet. `lint` reports a value that is not a model type, because the check would otherwise be skipped:

```yaml
      - name: amount
        logicalType: number
        customProperties:
          - property: pbiDataType   # only Currency (fixed decimal) passes
            value: Currency
```

`physicalType` (for example `DECIMAL(10,2)`) describes the source system, so it is not checked. A property with only a `physicalType` is reported as skipped until it gets a `logicalType` or a `pbiDataType`.

A `number` check accepts either type and still reports both when it fails, for example `expected Number, actual Text`.

## Rule mapping (`--pql-assert 0.7`, the default)

| ODCS rule | PQL.Assert 0.7.1 call | Status |
|---|---|---|
| Schema object present | `Tbl.ShouldExist` | mapped |
| Properties present | `Tbl.ShouldHaveColumns` (one call per table) | mapped |
| Closed schema (`--closed-schema`) | `Tbl.ShouldNotHaveExtraColumns` | mapped |
| `logicalType` (or `pbiDataType`) | `Tbl.ColumnDataTypeShouldBe` (see [Column types](#column-types)) | mapped; **approximated** for `date`, `timestamp`, and `time` |
| `required: true`, `nullValues mustBe 0` | `Col.NullRateShouldBeAtMost(…, 0)` | mapped; **approximated** on `string` columns (DAX treats empty strings as BLANK, so they count as nulls) |
| `primaryKey`, `unique`, property `duplicateValues mustBe 0` | `Col.ShouldBeDistinct` (one call per column, shared by every rule that asks for it) | **approximated**: it compares `DISTINCTCOUNT` (counts BLANK) with `COUNTA` (ignores blanks). A blank fails an otherwise distinct column, and one blank plus one duplicate still passes. See [PQL.Assert gap plan](https://github.com/clientfirsttech/pql-test/blob/main/docs/pql-assert-gap-plan.md) C4. |
| `rowCount mustBeGreaterThan 0` | `Tbl.ShouldHaveRows` | mapped |
| `rowCount mustBe n` | `Tbl.ShouldHaveRowCount` | mapped |
| `rowCount mustBeGreaterThan n` | `Tbl.ShouldHaveMoreRowsThan` | mapped |
| `rowCount` `mustNotBe`, `mustBeGreaterOrEqualTo`, `mustBeLessThan`, `mustBeLessOrEqualTo`, `mustBeBetween` | `ShouldNotEqual`, `ShouldBeGreaterOrEqual`, `ShouldBeLessThan`, `ShouldBeLessOrEqual`, `ShouldBeBetween` on `COUNTROWS` | mapped |

`Col.ShouldNotBeNull` is not used for `required`. In PQL.Assert 0.7.1 it passes when any value is non-null.

### PQL.Assert 0.8

PQL.Assert 0.8.0 added the functions behind the gaps in the table above ([gap plan](https://github.com/clientfirsttech/pql-test/blob/main/docs/pql-assert-gap-plan.md)). Pass `--pql-assert 0.8` to `generate`, `coverage`, and `trace` to use them; the default stays `0.7`, so existing suites and golden files do not change. `pql-test contract run` defaults to `auto`: it asks the model with `PQL.Assert.LibraryVersion()` and uses 0.7 when that call fails. Use the same value for `generate` and `trace` that you used when the suites were generated.

| ODCS rule | PQL.Assert 0.8 call | Status |
|---|---|---|
| `required: true`, `nullValues mustBe 0` | `Col.NullCountShouldBeAtMost(…, 0)` (true nulls only; an empty string is not a null) | mapped |
| `nullValues` with a ceiling (`mustBeLessOrEqualTo`, `mustBeLessThan`) | `Col.NullCountShouldBeAtMost`, or `Col.NullRateShouldBeAtMostV2` with `unit: percent` | mapped |
| `primaryKey` (one column) | `Col.ShouldBePrimaryKey` | mapped |
| `unique`, property `duplicateValues mustBe 0` | `Col.NonNullValuesShouldBeDistinct` (nulls are ignored; an empty string is a value) | mapped |
| Composite `primaryKey`, schema-level `duplicateValues mustBe 0` over 2+ properties | `Tbl.RowsShouldBeDistinct` over `SELECTCOLUMNS` of the key columns | mapped |
| Property `duplicateValues` with a ceiling | `Col.DuplicateCountShouldBeAtMost` | mapped |
| `rowCount mustNotBeBetween` | `ShouldNotBeBetween` on `COUNTROWS` | mapped |
| `^literal`, `literal$`, or a bare-literal pattern (`invalidValues` with `mustBe 0`, or `logicalTypeOptions` pattern) | `Col.ShouldStartWith` / `ShouldEndWith` / `ShouldContainString` with `matchCase` `"Y"` (case-sensitive, like the regex; null rows are skipped) | mapped |
| `slaProperties` `latency` in days or hours, with a `table.column` element | `Col.MaxDateShouldBeWithinDays` | **approximated** (the age of the newest value, in UTC days; depends on when the test runs) |

Like most PQL.Assert 0.8 column checks, these fail with `NO VALUES` on a column with no non-null value. Any other regex, ceiling, or SLA stays **skipped** with its reason. `missingValues`, `invalidValues` with a value list, ranges, and relationships are unchanged and still skipped. Column types map the same way on both catalogs.

These rules are reported as **skipped**, with the plan for each:

| ODCS rule | Planned |
|---|---|
| `physicalType` alone (the source system's type) | not planned: add a `logicalType` or a `pbiDataType` |
| `logicalTypeOptions` minimum/maximum, minLength/maxLength | planned |
| `logicalTypeOptions` pattern, `invalidValues` with a pattern | later |
| v3.1 `relationships` | planned (`Relationship.ShouldExist`) |
| v3.2 `enum` (allowed values) | planned (`Col.ValuesShouldBeInSet`) |
| `nullValues` percent or absolute thresholds | planned |
| `missingValues`, `invalidValues` | planned |
| Composite primary keys, 2- and 3+-column `duplicateValues` | planned |
| `rowCount mustNotBeBetween` | planned |
| Non-zero `duplicateValues` thresholds | later |
| Nested (object / array) and v3.2 `map` / `vector` properties | no model column |
| `type: sql` | later (optional, review-marked DAX stub) |
| `type: custom`, `type: text`, `slaProperties` | not planned |

ODCS v3.0 contracts that use `rule:` instead of `metric:` are understood: `nullCheck` is read as `nullValues`, `duplicateCount` as `duplicateValues`, and `validValues` as `invalidValues`.

## Python API

```python
from pql_test.odcs.api import plan_contract, render, generate
from pql_test.odcs.coverage import build_report
from pql_test.odcs.results import trace

plan = plan_contract("orders.odcs.yaml", pql_assert="0.8")  # or an already-parsed dict; default "0.7"
files = render(plan, env="DEV")  # list of SuiteFile(function_name, content, blocking)
report = build_report(plan.contract, plan.outcomes, catalog=plan.catalog)
```

## License

Part of pql-test, licensed under AGPL-3.0-only. The bundled ODCS JSON schemas are Apache-2.0 (Bitol); see [NOTICE](../NOTICE) and [LICENSES.md](../LICENSES.md).
