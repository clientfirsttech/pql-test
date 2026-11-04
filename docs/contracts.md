# ODCS data contracts: `pql-test contract`

Generate [PQL.Assert](https://github.com/clientfirsttech/PQL.Assert) DAX test suites from [ODCS](https://bitol-io.github.io/open-data-contract-standard/) v3.0, v3.1, and v3.2 data contracts, run them, and trace every result back to its contract rule. Every contract rule is reported as **mapped**, **approximated**, or **skipped**, so nothing is dropped silently.

The commands come with pql-test (`pip install pql-test`). `lint`, `coverage`, `generate`, and `trace` only read and write files, so they also run on Linux, for example in a CI pipeline. `run`, and `doctor`'s live checks, need XMLA, which is Windows-only.

## Quick start

```bash
pql-test contract init ./SalesModel -o orders.odcs.yaml                 # start the contract from the model
pql-test contract doctor ./SalesModel                                   # which PQL.Assert? which --pql-assert?
pql-test contract coverage orders.odcs.yaml                             # which rules can be enforced?
pql-test contract lint orders.odcs.yaml ./SalesModel                    # contract valid, names resolve?
pql-test contract generate orders.odcs.yaml ./SalesModel --env DEV      # write *.Tests.dax suites
pql-test contract run orders.odcs.yaml ./SalesModel --env DEV --output results.json  # generate in memory, run, trace
pql-test contract trace orders.odcs.yaml results.json                   # failures by contract rule id
```

`pql-test contract run` never changes the PBIP project or the model: it builds the suites in memory and runs them as read-only queries. Writing suites into `DAXQueries/` (and so into git and Fabric Git integration) is always a separate act: `generate`, or `run --write`. `pql-test run-tests` runs the suites registered in the deployed model, so it sees generated suites only after the model is published.

[`examples/contracts/`](../examples/contracts/) has three runnable contracts against [`examples/SampleModel`](../examples/SampleModel.SemanticModel): a starter from `init`, one with scenario tests and direct PQL.Assert calls, and one with `latency` and `frequency`. Each one passes every mapped rule (checked live by `python/tests/test_contract_live.py`), so `pql-test contract run examples/contracts/starter.odcs.yaml local/SampleModel --env DEV` works as written if you have SampleModel open.

## Start a contract from the model

```bash
pql-test contract init ./SalesModel --output sales.odcs.yaml
pql-test contract init local/SalesModel --table Sales --table Customer -o sales.odcs.yaml
```

`init` reads the model's TMDL and writes a starter ODCS v3.1.0 contract (`status: draft`): one schema object per table and one property per column, with each column's `logicalType` (see [Column types](#column-types); `decimal` columns also get `pbiDataType: Currency`). It leaves out measure tables (only measures, or only hidden placeholder columns) and Power BI's automatic date tables, and gives a column with no ODCS type (a calculated table or column, or `binary`) a `description` saying why. It only reads the model, and prints to stdout unless `--output FILE` is given (`--force` overwrites that file). `--table NAME` (repeatable) picks tables, and `--id ID` sets the contract id.

The starter states what the model already is, so `lint` and `run` pass on it as is. (A column name containing a comma makes the table's columns check skipped, because PQL.Assert splits its column list on commas.) `--output` refuses a path inside the model folder. Add the quality rules the data must meet, then loop: `lint CONTRACT MODEL` → `coverage CONTRACT` → `run CONTRACT MODEL --env DEV`. [`examples/contracts/starter.odcs.yaml`](../examples/contracts/starter.odcs.yaml) is `init`'s own output against SampleModel, unedited except for a comment.

## Commands

| Command | What it does |
|---|---|
| `init MODEL_PATH [--output FILE]` | Writes a starter contract from the model's TMDL: tables, columns, and types (see [above](#start-a-contract-from-the-model)) |
| `generate CONTRACT MODEL_PATH --env ENV` | Writes `<Prefix>.<Suite>.<ENV>.Tests.dax` into the PBIP model's `DAXQueries/` folder |
| `coverage CONTRACT [--format text\|json]` | Lists every rule with its status, generated function(s), and skip reason |
| `lint CONTRACT [MODEL_PATH]` | Validates against the bundled ODCS JSON schema, then checks that names resolve, that every [`engine: pql-test` DAX rule](#dax-rules-in-the-contract-engine-pql-test) can be generated, and (with a MODEL_PATH) that every table, column, and relationship exists in the model's TMDL |
| `run CONTRACT MODEL_PATH --env ENV` | Generates the suites in memory, runs them over XMLA, and traces the results to rule ids, without writing any file (`--output`, `--log-format azuredevops\|github`, and the `run-tests` connection options). `--write` also saves the suites into `DAXQueries/`, like `generate` |
| `trace CONTRACT RESULTS_JSON` | Joins pql-test `--output` JSON to rule ids: passed, failed, error, not executed, or skipped |
| `doctor [MODEL_PATH] [--format text\|json]` | Checks Python, the dependencies, and the bundled schemas and catalogs. With a PBIP model, reads its PQL.Assert library from `definition/functions.tmdl`, recommends the `--pql-assert` value whose every function the model defines, and checks the deployed or open model's library |

**MODEL_PATH** is the same in every command: the PBIP root containing the `.pbip` file, the `*.SemanticModel` folder, the `.pbip` file itself, or `local/<name>`, which means the one `<name>.SemanticModel` folder in this repository (searched from the git root). With `local/<name>`, `run` and `doctor` connect only to that model open in Power BI Desktop, even when `PQL_*` service credentials are set; pass `--model-dir` when the repository holds several copies. The `<workspace>.Workspace/<model>.SemanticModel` form of `run-tests` is not accepted yet.

**Shared flags**:
- `--closed-schema` also forbids columns the contract does not list.
- `--fail-on-skipped` exits 1 if any rule is skipped (`generate`, `coverage`).
- `--pql-assert 0.7|0.8|0.9` picks the PQL.Assert version to generate for (`generate`, `coverage`, `trace`; default `0.7`). `generate` also takes `auto`, which reads the model folder the way `doctor` does, and `run` defaults to `auto`, which asks the model. See [PQL.Assert 0.8](#pqlassert-08) and [PQL.Assert 0.9](#pqlassert-09).
- `--suite-prefix NAME` overrides the suite prefix (`generate`, `run`, `trace`).
- `--dry-run` prints the DAX instead of writing files (`generate`).
- `--force` overwrites suite files that pql-test did not generate (`generate`, and `run --write`).

**Exit codes**:
- 0 means success.
- 1 means the contract is invalid, `lint` found problems, a `doctor` check failed, `--fail-on-skipped` was triggered, or (`run`) a blocking suite failed or nothing ran.
- 2 means a usage error: a bad `--env` token, a MODEL_PATH that is not a PBIP model, a file pql-test would refuse to overwrite, or an unreadable results file.

## Generated suites

- **Names**: `<Prefix>.<Suite>.<ENV>.Tests`. `Suite` is `Schema` (tables, columns, and relationships), `DataQuality` (the rules pql-test translates), `ContractDax` (DAX the contract wrote, with `engine: pql-test`), or `RefreshAge` (`frequency` SLAs, which read model metadata). A suite runs as one query, so one error fails every rule in it: the last two suites keep a mistake in hand-written DAX, or a permission error, from failing the translated rules. The prefix is a PascalCase form of the contract's `dataProduct`, then its `name`, then its `id`. pql-test matches `ENV` as the second-to-last dotted token, so `pql-test run-tests --env DEV` picks the suites up.
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
| Visible in Power BI Desktop's DAX query view | No (only after a local `generate`) | Yes |
| Published with the model (Fabric git integration) | No | Yes, as files in `DAXQueries/` |
| Counted by `pql-test code-coverage` | No | No: files in `DAXQueries/` are not model functions. A persistent deploy is planned. |
| Review | Review the contract | Review the contract and the DAX diff |

**Regenerate in CI.**
In CI, run one step, which generates the suites in memory, runs them, and traces the results. It writes no files, so nothing needs ignoring:
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
| `logicalTypeOptions` `minimum` and `maximum` on an `integer` or `number` | `Col.ShouldBeInRange`, or `Col.MinShouldBeAtLeast` / `Col.MaxShouldBeAtMost` for one bound | mapped |
| `exclusiveMinimum: 0` | `Col.ShouldBePositive` | mapped |
| `exclusiveMinimum` / `exclusiveMaximum` on an `integer` | the inclusive bound one step inward (`> 3` is `>= 4`) | mapped |
| `minLength` / `maxLength` on a `string` | `Col.TextLengthShouldBeInRange` | mapped |
| v3.2 `enum`, and `invalidValues` with `arguments.validValues` and a zero ceiling | `Col.ValuesShouldBeInSet` (null rows are skipped) | mapped; **approximated** for text with letters (DAX compares text without regard to case) |
| `invalidValues` with `validValues` and a count or percent ceiling | `Tbl.RowCountShouldBeAtMost` / `Tbl.RowRateShouldBeAtMost` over the non-null rows outside the list | as above |
| `missingValues` (default: null, and `""` on text; or `arguments.missingValues`) | `Tbl.RowCountShouldBeAtMost` / `Tbl.RowRateShouldBeAtMost` over the missing rows | as above |
| v3.1 `relationships` (`foreignKey`, `table.property` ends) | `Relationship.ShouldExist`, from the foreign key to the key | mapped |
| `slaProperties` `latency` in days or hours, with `table.column` element(s) | `Col.MaxDateShouldBeWithinDays` / `Col.MaxDateShouldBeWithinHours`, one per element | **approximated**: data age, see [Freshness](#freshness-latency-vs-frequency) |
| `slaProperties` `frequency` in days or hours, with table element(s) | `ShouldBeLessOrEqual` on the hours since `INFO.PARTITIONS()[RefreshedTime]`, in the `RefreshAge` suite | **approximated**: refresh recency, see [Freshness](#freshness-latency-vs-frequency) |
| `type: custom`, `engine: pql-test` | the contract's DAX, see [DAX rules](#dax-rules-in-the-contract-engine-pql-test) | mapped |

Like most PQL.Assert 0.8 column checks, these fail with `NO VALUES` on a column with no non-null value. Any other regex, ceiling, or SLA stays **skipped** with its reason. Column types map the same way on both catalogs.

Upgrading note: suites generated with `--pql-assert 0.8` change when you regenerate. Rules that were skipped now produce checks, and a `latency` in hours now calls `Col.MaxDateShouldBeWithinHours` instead of a fractional-day `Col.MaxDateShouldBeWithinDays`. `--pql-assert 0.7` output is unchanged.

### PQL.Assert 0.9

PQL.Assert 0.9.0 gave ODCS `frequency` a native function; every other 0.8 mapping is unchanged. Pass `--pql-assert 0.9` to `generate`, `coverage`, and `trace`; the default stays `0.7`.

| ODCS rule | PQL.Assert 0.9 call | Status |
|---|---|---|
| `slaProperties` `frequency` in days or hours, with table element(s) | `Tbl.LastRefreshShouldBeWithinHours(testName, tableName, maxAgeHours)`, in the `RefreshAge` suite | **approximated**: refresh recency, see [Freshness](#freshness-latency-vs-frequency); clearer `Actual` text than 0.8's inline expression (`TABLE NOT FOUND`, `NEVER REFRESHED`, or the age in hours) |

Upgrading note: regenerating with `--pql-assert 0.9` changes only the `frequency` rows' rendered DAX (the native call instead of 0.8's inline `INFO.PARTITIONS()` expression); their status stays **approximated**. It also raises the version an [`engine: pql-test` direct call](#dax-rules-in-the-contract-engine-pql-test) needs: pql-test validates a direct call's function name and argument count against the newest vendored PQL.Assert signatures, so that form now needs `--pql-assert 0.9` instead of 0.8 — a contract with a direct call that generated fine under `--pql-assert 0.8` reports it **skipped** until you move to `0.9`. `--pql-assert 0.7` and `0.8` output is otherwise unchanged.

These rules are reported as **skipped**, with the plan for each:

| ODCS rule | Planned |
|---|---|
| `physicalType` alone (the source system's type) | not planned: add a `logicalType` or a `pbiDataType` |
| With `--pql-assert 0.7`: everything in the 0.8 table above | use `--pql-assert 0.8` |
| Regular expressions beyond `^literal`, `literal$`, and a bare literal | later |
| Date and time bounds; a `number`'s `exclusiveMaximum`, or `exclusiveMinimum` other than 0; `multipleOf`; `format` | no PQL.Assert check |
| Value lists on date and time columns | not planned: the model compares them as locale-formatted text |
| Composite (multi-column) relationships; fully qualified (`id`-based) relationship references | later |
| `slaProperties` `latency` on a table with no column | not planned: refresh time is not source latency (use `frequency`) |
| `slaProperties` `timeOfAvailability`, `retention`, and other SLA properties | not planned (`retention` could use `Partitions.ShouldExist` later) |
| Nested (object / array) and v3.2 `map` / `vector` properties | no model column |
| `type: sql` | later (optional, review-marked DAX stub) |
| `type: custom` with any engine but `pql-test`, `type: text` | not planned |

ODCS v3.0 contracts that use `rule:` instead of `metric:` are understood: `nullCheck` is read as `nullValues`, `duplicateCount` as `duplicateValues`, and `validValues` as `invalidValues`.

## Freshness: latency vs frequency

"Is the data fresh?" is two questions, and a semantic model can pass one and fail the other. ODCS has an SLA property for each, and pql-test checks each one differently:

| | `latency` | `frequency` |
|---|---|---|
| ODCS meaning | The delay between the source and the destination | How often the data is updated |
| Question | How old is the newest data in the model? | Did the model refresh on schedule? |
| `element` | `table.column`: a timestamp column | `table` |
| Check | The newest value in the column, against `UTCNOW()` (`Col.MaxDateShouldBeWithinDays` / `…Hours`) | The newest `RefreshedTime` of the table's partitions (`INFO.PARTITIONS()`) |
| Catches | A refresh that succeeded against stale source data | A refresh that failed or stopped running |
| Misses | A stopped refresh, while the newest row is still within the limit | Stale source data that refreshed successfully |

```yaml
slaProperties:
  - property: latency        # source data reaches the model within 3 hours
    value: 3
    unit: h
    element: orders.loaded_at
  - property: frequency      # the model refreshes at least daily (allowing 2 hours' slack)
    value: 26
    unit: h
    element: orders
```

- **Point `latency` at a load or ingestion timestamp**, not a business date. An order date can lag for legitimate reasons, such as no sales on a weekend, and gives false failures. The check measures the source delay plus the refresh delay, which is what the model's users see.
- **Use both.** Only `latency` catches stale source data that refreshed successfully. `frequency` notices a refresh that stopped before the newest row ages past its limit.
- **A `latency` whose `element` is a table** is skipped: a table's refresh time is not source latency.
- **One `latency` per source** for a model fed by several sources: if one source loads and another does not, the newest row overall can still look fresh.
- **Permissions:** `frequency` reads `INFO.PARTITIONS()`, which may need more than read access to the model. Its rules run in their own `<Prefix>.RefreshAge.<ENV>.Tests` suite, so a permission error there leaves the other suites running.
- Both are **approximated**: they compare with the time the test runs.

PQL.Assert 0.8 has no refresh function, so `--pql-assert 0.8`'s `frequency` check uses `ShouldBeLessOrEqual` on an inline `INFO.PARTITIONS()` expression. PQL.Assert 0.9.0 added the dedicated `Tbl.LastRefreshShouldBeWithinHours` ([request](pql-assert-freshness-request.md), fulfilled); `--pql-assert 0.9` calls it directly, with the same approximated semantics but clearer `Actual` text (`TABLE NOT FOUND`, `NEVER REFRESHED`, or the age in hours).

[`examples/contracts/freshness.odcs.yaml`](../examples/contracts/freshness.odcs.yaml) runs both against SampleModel (it has to point `latency` at a business date, with a comment explaining why: SampleModel has no load-timestamp column).

## DAX rules in the contract (`engine: pql-test`)

Some tests are scenarios, not column rules: a measure's value in a given filter context, or any PQL.Assert check ODCS has no metric for. Write them as ODCS `type: custom` rules with `engine: pql-test`. Other tools skip an engine they do not run, so the contract stays usable for them. (`type: sql` is not used for DAX: ODCS ties a SQL rule to no server, so a tool reading the contract would try to run the DAX as SQL.)

```yaml
schema:
  - name: Sales
    quality:
      - id: no-data-year-is-zero
        type: custom
        engine: pql-test
        description: Number of Characters is 0, not blank, for a year with no data
        implementation:
          expression: CALCULATE([Number of Characters], FILTER(ALL('DateDim'), 'DateDim'[Year] = -1))
          mustBe: 0
      - id: appearances-mean
        type: custom
        engine: pql-test
        severity: warning
        implementation:
          function: PQL.Assert.Col.MeanShouldBeInRange
          args: ["'MarvelFact'[Appearances]", 0, 50]
```

**Expression and comparator.** `implementation.expression` is one scalar DAX expression, and the comparison is one ODCS comparator inside `implementation` (ODCS allows no comparator at the top level of a `custom` rule):

| Comparator | PQL.Assert call |
|---|---|
| `mustBe` (number or true/false) | `ShouldEqual` (types must match, so BLANK is not 0, on both catalogs) |
| `mustBe` (text) | `ShouldEqualExactly` (DAX `=` ignores case; the contract's value does not) |
| `mustNotBe` | `ShouldNotEqual` (approximated for text with letters: it ignores case) |
| `mustBeGreaterThan`, `mustBeGreaterOrEqualTo`, `mustBeLessThan`, `mustBeLessOrEqualTo` | `ShouldBeGreaterThan`, `ShouldBeGreaterOrEqual`, `ShouldBeLessThan`, `ShouldBeLessOrEqual` |
| `mustBeBetween`, `mustNotBeBetween` | `ShouldBeBetween`, `ShouldNotBeBetween` (0.8 or later) |

With `--pql-assert 0.7`, a BLANK result passes the text `mustBe` and the number comparisons, because PQL.Assert 0.7 compared BLANK as an empty string or as 0. Those rules are **approximated** on 0.7; PQL.Assert 0.8 fails a BLANK.

**Direct call.** `implementation.function` names any PQL.Assert assertion, and `implementation.args` lists its arguments after `testName`, which pql-test supplies. A text argument is DAX source, so a DAX string needs its own quotes (`'"AB"'`); numbers and true/false become DAX literals. pql-test checks the function name and argument count against the newest vendored PQL.Assert release (currently 0.9.0), so this form needs `--pql-assert 0.9` (it needed `0.8` before PQL.Assert 0.9.0 shipped, and will need the next release's value once pql-test vendors it). The model best-practice checks (`BP.*`) and the discovery helpers cannot be called this way.

**Rules for the DAX.** It is pasted into a generated suite's `UNION`, so it must be one expression. pql-test skips a rule, and `lint` reports it, when its DAX has `EVALUATE` or `DEFINE`, unbalanced brackets or quotes, an unterminated comment, a comma outside brackets, or a control character other than a line feed or tab (a carriage return could end a comment early). A final `//` comment is fine. Numbers must be finite.

**Reporting.** These rules run in their own `<Prefix>.ContractDax.<ENV>.Tests` suite, so a wrong measure or column name in hand-written DAX cannot fail the translated rules. They keep status `mapped` (or `approximated`), with `"source": "contract-dax"` in the `coverage --format json` output and "(contract DAX)" in the text output, so a reviewer can tell DAX written in the contract from rules pql-test translated. `severity: warning` sends them to the `ContractDax.<ENV>WARN` suite.

**What reaches each PQL.Assert function.** [`pql_assert_functions.yaml`](../python/pql_test/odcs/catalog/pql_assert_functions.yaml) lists every PQL.Assert 0.9.0 function as `mapped` (an ODCS rule generates it), `dax` (only a DAX rule calls it, such as `ShouldEqual`), or `none` (best-practice checks and discovery helpers). A test fails when a new PQL.Assert release adds a function nobody has classified.

[`examples/contracts/scenario-tests.odcs.yaml`](../examples/contracts/scenario-tests.odcs.yaml) runs both forms against SampleModel: an expression over `[Number of Characters]`, a boolean expression compared with `mustBe: true`, and two direct calls (`ShouldStartWith` on a measure, which has no column to attach a `pattern` rule to; `Col.MeanShouldBeInRange`, a statistic ODCS has no metric for).

## How we keep this mapping complete

Two tests fail before a gap reaches a user: [`test_odcs_rule_matrix.py`](../python/tests/odcs/test_odcs_rule_matrix.py) classifies every value in ODCS's closed vocabularies (quality metrics, quality types, `logicalType`, relationship types, `logicalTypeOptions` keys) the way [`test_function_matrix.py`](../python/tests/odcs/test_function_matrix.py) already classifies every PQL.Assert function, and [`test_docs_contracts_agreement.py`](../python/tests/odcs/test_docs_contracts_agreement.py) checks this page's mapping tables against the catalogs. A new ODCS or PQL.Assert release, or a mapping change that forgets to update this page, fails one of them. `aidd-custom/skills/pql-test-contract-gap-check/SKILL.md` runs both as part of an AIDD review and before every release.

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
