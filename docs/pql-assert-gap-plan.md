# PQL.Assert Gap Plan (0.7.1 → 0.8.0)

**Audience:** PQL.Assert maintainers and contributors.
**Status:** proposed, 2026-10-25. PQL.Assert 0.8.0 released; pql-odcs adopts it with `--pql-assert 0.8` (2026-10-27, see [the adoption epic](../tasks/archive/2026-10-27-pql-odcs-pql-assert-0-8.md)). The `BlankRate…V2`, `NullOrBlankRate…V2`, and `ValuesShouldContain` live checks noted below are still open: pql-odcs's 0.8 catalog uses `NullRateShouldBeAtMostV2` and `ValuesShouldContain`, but its output has not yet been run against a 0.8.0 model.
**Why it exists:** [pql-odcs](../packages/pql-odcs/README.md) turns ODCS data-contract rules into PQL.Assert calls. Building it surfaced places where PQL.Assert 0.7.1 is missing a function, or where an existing function behaves differently from what its name suggests. This plan closes those gaps in 0.8.0 **without breaking anything written against 0.7.1**.

Every finding below was reproduced with read-only DAX queries against `examples/SampleModel` (dev workspace) on 2026-10-25. Every function whose full body appears below was parsed and run there as a query-scoped `DEFINE FUNCTION`; nothing was deployed to the model. Results are under **Live check**. The variants described only as "same shape" have **not** been run yet: `BlankRate…V2`, `NullOrBlankRate…V2`, and `ValuesShouldContain`. Validate them before release.

## Backward-compatibility rules

These rules apply to every item in this plan:

1. **Additive only.** 0.8.0 adds functions. It changes no existing function's name, parameter list, parameter types, or pass/fail result.
2. **One name, one signature.** A DAX user-defined function has exactly one signature; there are no overloads.
   - An existing signature may only grow by an **optional trailing parameter** whose default reproduces 0.7.1 behaviour. `RetrieveTestsByEnvironmentV2` already uses this pattern: `(environment: STRING = "")`.
   - Any change in meaning, or a new required parameter, gets a **new name** (descriptive, or a `V2` suffix as with `RetrieveTestsV2`). The old function stays as it is.
3. **Same output shape.** New functions return the standard 4-column row (`TestName`, `Expected`, `Actual`, `Passed`), so pql-test and existing UNION-based suites accept them unchanged.
4. **Deprecate, don't remove.** A superseded function gets a `Deprecated: use <new>` note in its description. Nothing is removed before 1.0.
5. **Text-only fixes are opt-in.** The 0.7.1 `Expected`/`Actual` text is left as it is, even where it has a cosmetic bug (D1). Some CI logs and snapshot tests match on it. The corrected formatting appears only in the new functions.
6. **Detectable version.** Callers detect 0.8.0+ by calling a new function (R1). Its absence means 0.7.x, so a tool can keep using the 0.7 behaviour against older models.

A suite written for 0.7.1 therefore produces **identical results on 0.8.0**.

## Verified findings in 0.7.1

| ID | Function | What it actually does | Evidence (SampleModel) |
|---|---|---|---|
| C1 | `Col.ShouldNotBeNull` | Passes when **any** value is non-blank (`DISTINCTCOUNTNOBLANK(col) > 0`). It does not check that **no** row is blank. | `MarvelSource[Year]` has 815 blank rows and still passes. |
| C2 | `Col.NullRateShouldBeAtMost`, `Col.BlankRateShouldBeAtMost`, `Col.NullOrBlankRateShouldBeAtMost` | The denominator is `COUNTROWS(ALLNOBLANKROW(col))`, which is the number of **distinct values**, not rows. The reported rate is therefore wrong, and any threshold above 0% is meaningless. A `0` threshold is still correct (it passes only when there are no blanks). `maxNullPct` is a percentage (0–100). | `Year`: `Actual = "1072.37% (815 of 76)"`. The real rate is 815 / 16,376 = 4.98%. |
| C3 | `ShouldMatch` | Uses `CONTAINSSTRING`: a case-insensitive **substring** match with `?`/`*` wildcards. It is not a regex and not a whole-value match. | From the 0.7.1 source. |
| C4 | `Col.ShouldBeDistinct`, `Col.ShouldNotContainDuplicates` | Compare `DISTINCTCOUNT` (counts BLANK as a value) with `COUNTA` (ignores blanks). A single blank **fails** an otherwise distinct column. One blank plus one duplicate **passes**: for `{1, 1, BLANK}`, both counts are 2. | `Year`: `DISTINCTCOUNT` = 76 and `DISTINCTCOUNTNOBLANK` = 75, while `COUNTA` = 15,561, which excludes the 815 blanks. |
| C5 | Blank vs empty string | `COUNTBLANK` counts empty strings (`""`) as well as true BLANK, but `ISBLANK("")` is FALSE and `COUNTA` counts `""`. Text columns loaded with `""` look "blank" to some functions and not to others. | `MarvelSource[GSM]`: `COUNTBLANK` = 16,286, `ISBLANK` rows = 0, `COUNTA` = 16,376. |
| D1 | Rate and threshold text | `FORMAT(x, "0.##")` renders whole numbers with a trailing dot. | `Expected = "Null rate <= 0.%"`. |
| — | Version | No function reports the installed version. Tools can't tell 0.7.1 from earlier releases. `Version` can't be used as a name: `FUNCTION PQL.Assert.Version` is a DAX syntax error. | Parse error at `Version`. |

## Proposed additions for 0.8.0

The C items are clarifications of existing behaviour. The R items are new functions. In every new function body, `+ 0` turns the BLANK that `COUNTROWS` returns for an empty table into `0`. `FORMAT(ROUND(x, 2), "General Number")` fixes D1.

### R1 — Library version

```dax
function 'PQL.Assert.LibraryVersion' = () => "0.8.0"
```

Callers detect it with `EVALUATE { PQL.Assert.LibraryVersion() }`. An error means the model has 0.7.x or older.

### C1 + R4 — Null count (true nulls only)

```dax
function 'PQL.Assert.Col.NullCountShouldBeAtMost' =
    (testName : STRING, tableRef : TABLE EXPR, columnRef : ANYREF EXPR, maxCount : INT64) =>
        VAR _NullCount = COUNTROWS(FILTER(tableRef, ISBLANK(columnRef))) + 0
        RETURN ROW(
            "TestName", testName,
            "Expected", "Null count <= " & FORMAT(maxCount, "0"),
            "Actual", FORMAT(_NullCount, "0") & " null(s)",
            "Passed", _NullCount <= maxCount
        )
```

- `maxCount = 0` gives the "no row is null" check that `Col.ShouldNotBeNull` is often assumed to be (C1).
- Any other value covers ODCS `nullValues` with an absolute threshold (R4).
- The function takes `tableRef`, because a row count can't be derived from a column reference alone (C2, C5).
- It counts true nulls only (`ISBLANK`), so empty strings are **not** nulls. Use the `Blank` / `NullOrBlank` variants below for those.
- **Live check:** `Year` gives 815 nulls (fails); `DateDim[DateID]` gives 0 (passes).
- **Change to `Col.ShouldNotBeNull`:** description only. Rename it in the docs to "column has at least one value", and point readers to `NullCountShouldBeAtMost(…, 0)`.

### C2 — Correct rates (V2)

```dax
function 'PQL.Assert.Col.NullRateShouldBeAtMostV2' =
    (testName : STRING, tableRef : TABLE EXPR, columnRef : ANYREF EXPR, maxNullPct : DOUBLE) =>
        VAR _Rows = COUNTROWS(tableRef) + 0
        VAR _NullCount = COUNTROWS(FILTER(tableRef, ISBLANK(columnRef))) + 0
        VAR _NullPct = IF(_Rows = 0, 0, DIVIDE(_NullCount, _Rows) * 100)
        RETURN ROW(
            "TestName", testName,
            "Expected", "Null rate <= " & FORMAT(ROUND(maxNullPct, 2), "General Number") & "%",
            "Actual", FORMAT(ROUND(_NullPct, 2), "General Number") & "% ("
                & FORMAT(_NullCount, "0") & " of " & FORMAT(_Rows, "0") & " rows)",
            "Passed", _NullPct <= maxNullPct
        )
```

- Add `Col.BlankRateShouldBeAtMostV2` (filter `columnRef == ""`) and `Col.NullOrBlankRateShouldBeAtMostV2` (filter `ISBLANK(columnRef) || columnRef == ""`) with the same shape.
- Units stay **percent (0–100)**, the same as 0.7.1.
- **Live check:** `Year` at 5% passes with `"4.98% (815 of 16376 rows)"`.
- Mark the three 0.7.1 rate functions deprecated in favour of V2.

### C4 — Distinct checks that handle blanks

```dax
function 'PQL.Assert.Col.NonBlankValuesShouldBeDistinct' =
    (testName : STRING, columnRef : ANYREF EXPR) =>
        VAR _Distinct = DISTINCTCOUNTNOBLANK(columnRef) + 0
        VAR _NonBlank = COUNTA(columnRef) + 0
        RETURN ROW(
            "TestName", testName,
            "Expected", "Non-blank values distinct",
            "Actual", FORMAT(_Distinct, "0") & " distinct of " & FORMAT(_NonBlank, "0") & " non-blank",
            "Passed", _Distinct = _NonBlank
        )

function 'PQL.Assert.Col.ShouldBePrimaryKey' =
    (testName : STRING, columnRef : ANYREF EXPR) =>
        VAR _Blank = COUNTBLANK(columnRef) + 0
        VAR _Distinct = DISTINCTCOUNTNOBLANK(columnRef) + 0
        VAR _NonBlank = COUNTA(columnRef) + 0
        RETURN ROW(
            "TestName", testName,
            "Expected", "No blanks and all values distinct",
            "Actual", FORMAT(_Blank, "0") & " blank, " & FORMAT(_Distinct, "0") & " distinct of " & FORMAT(_NonBlank, "0"),
            "Passed", _Blank = 0 && _Distinct = _NonBlank
        )
```

- `NonBlankValuesShouldBeDistinct` matches ODCS `unique` and `duplicateValues = 0`: blanks are ignored.
- `ShouldBePrimaryKey` matches ODCS `primaryKey`: no blanks (empty strings included, via `COUNTBLANK`) and all values distinct.
- **Live check:** `DateDim[DateID]` passes both. `Year` fails `ShouldBePrimaryKey` with `"815 blank, 75 distinct of 15561"`.
- Mark `Col.ShouldBeDistinct` and `Col.ShouldNotContainDuplicates` deprecated. Their description should record the `{1, 1, BLANK}` false pass.

### R2 — Not between

```dax
function 'PQL.Assert.ShouldNotBeBetween' =
    (testName : STRING, lowerBound : DOUBLE, upperBound : DOUBLE, actual : DOUBLE) =>
        RETURN ROW(
            "TestName", testName,
            "Expected", "NOT " & FORMAT(lowerBound, "General Number") & " <= value <= " & FORMAT(upperBound, "General Number"),
            "Actual", FORMAT(actual, "General Number"),
            "Passed", actual < lowerBound || actual > upperBound
        )
```

- The argument order mirrors `ShouldBeBetween`.
- **Live check:** `COUNTROWS(DateDim)` = 1,039, which is not between 0 and 10, so it passes.

### R3 — Composite keys with any number of columns

```dax
function 'PQL.Assert.Tbl.RowsShouldBeDistinct' =
    (testName : STRING, keyTable : TABLE EXPR) =>
        VAR _Rows = COUNTROWS(keyTable) + 0
        VAR _Distinct = COUNTROWS(DISTINCT(keyTable)) + 0
        RETURN ROW(
            "TestName", testName,
            "Expected", "All key rows distinct",
            "Actual", FORMAT(_Distinct, "0") & " distinct of " & FORMAT(_Rows, "0") & " rows",
            "Passed", _Rows = _Distinct
        )
```

- The caller passes the key projection, e.g. `SELECTCOLUMNS('T', "a", 'T'[a], "b", 'T'[b], "c", 'T'[c])`. That removes the two-column limit of `Col.ComboShouldBeDistinct` without needing a variable number of parameters.
- **Live check:** the 3-column key on `MarvelFact` fails (6,832 distinct of 16,376 rows); the 1-column `DateDim` key passes.

### R5 — Filtered counts and rates

```dax
function 'PQL.Assert.Tbl.RowCountShouldBeAtMost' =
    (testName : STRING, filteredTable : TABLE EXPR, maxCount : INT64) =>
        VAR _Count = COUNTROWS(filteredTable) + 0
        RETURN ROW(
            "TestName", testName,
            "Expected", "Matching rows <= " & FORMAT(maxCount, "0"),
            "Actual", FORMAT(_Count, "0"),
            "Passed", _Count <= maxCount
        )

function 'PQL.Assert.Tbl.RowRateShouldBeAtMost' =
    (testName : STRING, filteredTable : TABLE EXPR, baseTable : TABLE EXPR, maxPct : DOUBLE) =>
        VAR _Matching = COUNTROWS(filteredTable) + 0
        VAR _Rows = COUNTROWS(baseTable) + 0
        VAR _Pct = IF(_Rows = 0, 0, DIVIDE(_Matching, _Rows) * 100)
        RETURN ROW(
            "TestName", testName,
            "Expected", "Matching rows <= " & FORMAT(ROUND(maxPct, 2), "General Number") & "%",
            "Actual", FORMAT(ROUND(_Pct, 2), "General Number") & "% (" & FORMAT(_Matching, "0") & " of " & FORMAT(_Rows, "0") & ")",
            "Passed", _Pct <= maxPct
        )
```

- These are generic building blocks for ODCS `invalidValues` and `missingValues` with a threshold or a percentage. The caller supplies the `FILTER`, e.g. `FILTER('T', NOT 'T'[status] IN {"open", "closed"})`.
- **Live check:** both pass on `MarvelSource`: 90 ≤ 100 rows, and 4.98% ≤ 5%.

### R6 — Duplicate count threshold

```dax
function 'PQL.Assert.Col.DuplicateCountShouldBeAtMost' =
    (testName : STRING, columnRef : ANYREF EXPR, maxCount : INT64) =>
        VAR _Duplicates = COUNTA(columnRef) - DISTINCTCOUNTNOBLANK(columnRef)
        RETURN ROW(
            "TestName", testName,
            "Expected", "Duplicate values <= " & FORMAT(maxCount, "0"),
            "Actual", FORMAT(_Duplicates, "0"),
            "Passed", _Duplicates <= maxCount
        )
```

- Duplicates are counted among non-blank values: rows minus distinct values.
- **Live check:** `DateDim[Year]` has 950 duplicates, so a threshold of 5 fails.

### C3 + R7 — Patterns

- **C3 (docs only):** document `ShouldMatch` as a substring, case-insensitive, `?`/`*` wildcard check, and leave it unchanged.
- **R7:** DAX has no regular expressions. A wildcard `SEARCH` anchors only at the start of the value, not the end. So R7 adds explicit, exact column checks:

```dax
function 'PQL.Assert.Col.ValuesShouldStartWith' =
    (testName : STRING, columnRef : ANYREF EXPR, prefix : STRING) =>
        VAR _Values = FILTER(DISTINCT(columnRef), NOT ISBLANK(columnRef))
        VAR _Bad = COUNTROWS(FILTER(_Values, LEFT(columnRef & "", LEN(prefix)) <> prefix)) + 0
        RETURN ROW(
            "TestName", testName,
            "Expected", "All non-blank values start with '" & prefix & "'",
            "Actual", FORMAT(_Bad, "0") & " distinct value(s) do not",
            "Passed", _Bad = 0
        )
```

- Add `Col.ValuesShouldEndWith` (using `RIGHT`) and `Col.ValuesShouldContain` (using `CONTAINSSTRINGEXACT`) in the same shape.
- pql-odcs will translate only simple anchored regexes into these: `^literal`, `literal$`, and a bare literal. Every other pattern stays reported as skipped.
- **Live check:** `MarvelSource[EYE]` ends with "Eyes" fails, with 4 distinct values that don't (e.g. "Black Eyeballs").

### R8 — Freshness

```dax
function 'PQL.Assert.Col.MaxDateShouldBeWithinDays' =
    (testName : STRING, dateColumnRef : ANYREF EXPR, maxAgeDays : DOUBLE) =>
        VAR _Latest = MAX(dateColumnRef)
        VAR _AgeDays = IF(ISBLANK(_Latest), BLANK(), (UTCNOW() - _Latest) * 1.0)
        RETURN ROW(
            "TestName", testName,
            "Expected", "Latest value within " & FORMAT(ROUND(maxAgeDays, 2), "General Number") & " day(s)",
            "Actual", IF(ISBLANK(_Latest), "NO VALUES", FORMAT(ROUND(_AgeDays, 2), "General Number") & " day(s) old"),
            "Passed", NOT ISBLANK(_AgeDays) && _AgeDays <= maxAgeDays
        )
```

- The function uses `UTCNOW()`, so results are the same in the service and on Desktop. An empty column fails.
- This covers ODCS `slaProperties` freshness (`latency` in days).
- **Live check:** `DateDim[Date]` is 238.78 days old, so a 30-day threshold fails.

## Summary of 0.8.0

| ID | New in 0.8.0 | Replaces (kept, deprecated) | ODCS rule it unlocks in pql-odcs |
|---|---|---|---|
| R1 | `LibraryVersion` | — | catalog selection |
| C1 / R4 | `Col.NullCountShouldBeAtMost` | `Col.ShouldNotBeNull` (docs only) | `required`, `nullValues` with an absolute threshold |
| C2 | `Col.NullRateShouldBeAtMostV2`, `Col.BlankRateShouldBeAtMostV2`, `Col.NullOrBlankRateShouldBeAtMostV2` | the three 0.7.1 rate functions | `nullValues` / `missingValues` with `unit: percent` |
| C4 | `Col.NonBlankValuesShouldBeDistinct`, `Col.ShouldBePrimaryKey` | `Col.ShouldBeDistinct`, `Col.ShouldNotContainDuplicates` | `unique`, `primaryKey`, `duplicateValues = 0` (from approximated to mapped) |
| R2 | `ShouldNotBeBetween` | — | `mustNotBeBetween` |
| R3 | `Tbl.RowsShouldBeDistinct` | — | composite keys, `duplicateValues` across 3+ columns |
| R5 | `Tbl.RowCountShouldBeAtMost`, `Tbl.RowRateShouldBeAtMost` | — | `invalidValues` / `missingValues` with thresholds |
| R6 | `Col.DuplicateCountShouldBeAtMost` | — | `duplicateValues` with a non-zero threshold |
| C3 / R7 | `Col.ValuesShouldStartWith`, `Col.ValuesShouldEndWith`, `Col.ValuesShouldContain` | `ShouldMatch` (docs only) | simple `pattern` rules |
| R8 | `Col.MaxDateShouldBeWithinDays` | — | `slaProperties` freshness |

That is 16 new functions, 0 changed signatures, and 0 removals.

## How pql-odcs adopts 0.8.0

pql-odcs keeps working against 0.7.1 models while adopting the new functions:

1. Add a second catalog, `catalog/pql_assert_0_8.yaml`, alongside the existing `pql_assert_0_7.yaml`, which stays as it is.
2. The new catalog maps `col.distinct`/`col.primary_key` to the C4 functions and `required` to `NullCountShouldBeAtMost(…, 0)`. It adds ops for R2–R8.
3. Choose the catalog per model:
   - `generate --pql-assert 0.7|0.8` sets it explicitly; the default stays `0.7` until 0.8.0 is common.
   - `contract run` detects it with `EVALUATE { PQL.Assert.LibraryVersion() }`; an error means 0.7.
4. With the 0.8 catalog:
   - rules approximated today because of C4 and C5 become **mapped**;
   - the "arrives in v0.2/v0.3" skips for R2–R8 become mapped.

   Suites generated earlier against 0.7 keep running unchanged.

## Test plan (PQL.Assert repository)

- Add a small test table with known rows to the PQL.Assert sample model:
  - a numeric column holding `{1, 1, BLANK}`, which C4 must fail and the old function passes;
  - a fully distinct numeric column with one BLANK;
  - a text column containing `""` and true BLANK;
  - a date column.
- For every new function, add one passing and one failing case, and assert the `Passed` value.
- Regression check: re-run the 0.7.1 suites against 0.8.0 and diff the four output columns. They must be identical (rules 1 and 5).

## Related note for pql-test (not PQL.Assert)

pql-test discovery calls `PQL.Assert.RetrieveTestsV2("<ENV>")`, but in 0.7.1 `RetrieveTestsV2` takes no arguments. Discovery then falls back to client-side filtering, so behaviour is correct but costs one failed query. pql-test should call `PQL.Assert.RetrieveTestsByEnvironmentV2` when it exists. This should be tracked in pql-test; no PQL.Assert change is needed.
