# PQL.Assert 0.9.0 request: refresh recency, and latency vs frequency in the docs

**For:** the PQL.Assert repository (a maintainer, or an AI agent working there).
**From:** pql-test, whose `pql-test contract` command turns ODCS data contracts into PQL.Assert test suites.
**Asks for:** one new function, `PQL.Assert.Tbl.LastRefreshShouldBeWithinHours`, and documentation changes that separate two kinds of freshness. Nothing existing changes behaviour.

## Why

"Is the data fresh?" is two different questions, and PQL.Assert 0.8.0 only answers one of them.

| Question | ODCS SLA property | What answers it | In PQL.Assert 0.8.0 |
|---|---|---|---|
| How old is the newest data in the model? | `latency`: the delay between the source and the destination | The newest value in a load or ingestion timestamp column | `Col.MaxDateShouldBeWithinDays`, `Col.MaxDateShouldBeWithinHours` |
| Did the model refresh on schedule? | `frequency`: how often the data is updated | When the table's partitions last refreshed | **Missing** |

They fail independently:

- **A refresh succeeds against stale source data.** The refresh time is recent, so a refresh check passes; the newest row is old, so the data-age check fails. Only `latency` catches this.
- **The refresh stops running.** The newest row may still be inside its latency limit for a while, but the refresh time keeps getting older. A refresh check catches this first.

Today the docs blur the two. `Col.MaxDateShouldBeWithinHours` suggests a refresh-log column as its example, which makes it a refresh check, while the same function on a load timestamp is a data-age check. Users cannot tell from the docs which question they are answering.

## Compatibility rules (unchanged from 0.8.0)

1. **Additive only.** No existing function changes its name, parameters, parameter types, or pass/fail result.
2. **One name, one signature.** No overloads; a change in meaning gets a new name.
3. **Same output shape.** The new function returns the standard 4-column row (`TestName`, `Expected`, `Actual`, `Passed`).
4. **Existing `Expected` and `Actual` text does not change.** CI logs and snapshot tests match on it. Only the `///` descriptions and the README change.
5. **Detectable version.** `PQL.Assert.LibraryVersion()` returns `"0.9.0"`. pql-test reads it to choose its catalog.

A suite written for 0.8.0 must produce identical results on 0.9.0.

## The new function

```dax
/// Freshness: refresh recency (ODCS frequency)
/// Asserts that the table's partitions were refreshed at most maxAgeHours hours before UTCNOW().
/// This checks that the refresh ran, not that the data is fresh: a refresh that succeeds against
/// stale source data passes. To check data age (ODCS latency), use Col.MaxDateShouldBeWithinHours
/// on a load or ingestion timestamp column. Fails when the table is not found or none of its
/// partitions has a refresh time. Reads INFO.TABLES() and INFO.PARTITIONS(), like Partitions.ShouldExist.
/// @param {STRING} testName - Description of the test being performed
/// @param {STRING} tableName - Name of the table whose refresh to check
/// @param {DOUBLE} maxAgeHours - Largest allowed time since the last refresh, in hours
function 'PQL.Assert.Tbl.LastRefreshShouldBeWithinHours' =
        (testName : STRING, tableName : STRING, maxAgeHours : DOUBLE) =>
            VAR _TableID = MAXX(FILTER(INFO.TABLES(), [Name] = tableName), [ID])
            VAR _Refreshed =
                MAXX(
                    FILTER(INFO.PARTITIONS(), [TableID] = _TableID && [RefreshedTime] > DATE(1900, 1, 1)),
                    [RefreshedTime]
                )
            VAR _AgeHours = IF(ISBLANK(_Refreshed), BLANK(), (UTCNOW() - _Refreshed) * 24.0)
            VAR _Passed = NOT ISBLANK(_AgeHours) && _AgeHours <= maxAgeHours
            RETURN ROW(
                "TestName", testName,
                "Expected", "Last refresh within " & FORMAT(ROUND(maxAgeHours, 2), "General Number") & " hour(s)",
                "Actual",
                    SWITCH(
                        TRUE(),
                        ISBLANK(_TableID), "TABLE NOT FOUND",
                        ISBLANK(_Refreshed), "NEVER REFRESHED",
                        "Last refresh " & FORMAT(ROUND(_AgeHours, 2), "General Number") & " hour(s) ago"
                    ),
                "Passed", _Passed
            )
    annotation DAXLIB_PackageId = PQL.Assert
    annotation DAXLIB_PackageVersion = 0.9.0
```

Place it with the other `Tbl.*` functions in `lib/functions-tbl-assertions.tmdl`.

### Behaviour

| Case | `Actual` | `Passed` |
|---|---|---|
| Last partition refresh 5.2 hours ago, `maxAgeHours` 24 | `Last refresh 5.2 hour(s) ago` | TRUE |
| Last partition refresh 30 hours ago, `maxAgeHours` 24 | `Last refresh 30 hour(s) ago` | FALSE |
| `tableName` is not a model table | `TABLE NOT FOUND` | FALSE |
| The table's partitions have never been refreshed | `NEVER REFRESHED` | FALSE |
| The table refreshed recently but has no rows | `Last refresh … hour(s) ago` | TRUE: row presence is `Tbl.ShouldHaveRows`'s job, not this function's |

- **Several partitions:** the newest refresh time counts. With incremental refresh, only recent partitions refresh, and that is still "the refresh ran".
- **The `> DATE(1900, 1, 1)` filter** treats a placeholder time as no refresh. Confirm the placeholder in the live checks below; remove the filter if a never-refreshed partition reports BLANK.
- **Not in scope:** "every partition refreshed" (a partial-refresh check). It could be a later `Tbl.OldestPartitionRefreshShouldBeWithinHours` if someone asks.

## Documentation changes

Only the `///` descriptions and the README change. No `Expected` or `Actual` text changes (rule 4).

### `Col.MaxDateShouldBeWithinDays` and `Col.MaxDateShouldBeWithinHours`

Replace each description with this text (say "days" or "hours" to match the function):

> Asserts that the newest value in a date/datetime column is at most maxAgeHours hours before UTCNOW().
> What it measures depends on the column. On a load or ingestion timestamp it checks **data age (ODCS
> latency)**: the delay between the source and the model, as the model's users see it. On a refresh-log
> column it checks **refresh recency (ODCS frequency)**; prefer Tbl.LastRefreshShouldBeWithinHours for that,
> which needs no extra column. A business date (such as an order date) can lag for legitimate reasons,
> such as no sales on a weekend, so it gives false failures. Fails when the column has no values. Compares
> against UTC, so a column stored in local time is off by the UTC offset.

This removes the current example in `Col.MaxDateShouldBeWithinHours`'s description ("e.g. a refresh-log timestamp that must be no older than 3 hours"), which presents a refresh check as the main use.

### `Partitions.ShouldBe`, `Partitions.ShouldExist`, `Partitions.ShouldBeAtLeast`

Add one sentence to each description:

> This checks partition structure, not freshness: an incremental refresh policy creates a partition for a
> date range whether or not the source delivered rows for it.

### README: a "Freshness: latency vs frequency" section

Add this section near the column and table assertion reference:

```markdown
## Freshness: latency vs frequency

"Fresh" means two different things. Check both: each catches a failure the other misses.

| | Data age (ODCS `latency`) | Refresh recency (ODCS `frequency`) |
|---|---|---|
| Question | How old is the newest data in the model? | Did the model refresh on schedule? |
| Function | `Col.MaxDateShouldBeWithinHours` / `…Days` | `Tbl.LastRefreshShouldBeWithinHours` |
| Point it at | A load or ingestion timestamp column | A table |
| Catches | A refresh that succeeded against stale source data | A refresh that failed or stopped running |
| Misses | A refresh that stopped while the newest row is still within the limit | Stale source data that refreshed successfully |

PQL.Assert.Col.MaxDateShouldBeWithinHours("Orders loaded within 3 hours", 'Orders'[LoadedAtUtc], 3)
PQL.Assert.Tbl.LastRefreshShouldBeWithinHours("Orders refreshed within 26 hours", "Orders", 26)

Avoid a business date (such as an order date) for data age: it can lag for legitimate reasons.
```

## Live checks before release

None of these can be checked from the TMDL. Run each against a real model, and record the result in the function's description or the README:

1. **Time zone:** is `INFO.PARTITIONS()[RefreshedTime]` UTC? Refresh a model, then compare the value with the refresh history in the Power BI service. If it is local time, convert it before comparing it with `UTCNOW()`.
2. **Never refreshed:** what does a partition that has never been refreshed report: BLANK, or a placeholder such as `1699-12-30`? Adjust the `> DATE(1900, 1, 1)` filter to match.
3. **Storage modes:**
   - **Direct Lake:** does `RefreshedTime` change on a reframe? (Expected: yes, and that is the right meaning for refresh recency.)
   - **DirectQuery:** what does it report? A DirectQuery table is never refreshed, so the function should not pass on a meaningless time. Recommended: fail with `Actual` = `DIRECTQUERY (no refresh)`, detected from `INFO.PARTITIONS()[Mode]`.
   - **Calculated tables:** they recalculate on refresh. Confirm `RefreshedTime` moves with the model refresh.
4. **Permissions:** run the function as a workspace Viewer, a Contributor, and an Admin. Record which roles can read `INFO.PARTITIONS()`. `Partitions.*` already depend on it, so the README may already state this; if not, add it.
5. **Desktop and service:** the result should be the same in Power BI Desktop (`UTCNOW()` is used for that reason).

## Tests to add

Following the 0.8.0 test plan pattern (one passing and one failing case per function, asserting `Passed`):

| Test | Setup | Expected |
|---|---|---|
| Passes after a refresh | Refresh the sample model, then run with `maxAgeHours` 24 | `Passed` TRUE, `Actual` starts with `Last refresh` |
| Fails when the threshold is tighter than the age | `maxAgeHours` 0.0001 | `Passed` FALSE |
| Unknown table | `tableName` = `"No Such Table"` | `Passed` FALSE, `Actual` = `TABLE NOT FOUND` |
| Never refreshed | A table added and deployed without a refresh (or the placeholder found in live check 2) | `Passed` FALSE, `Actual` = `NEVER REFRESHED` |
| Empty table | A refreshed table with no rows | `Passed` TRUE |
| Version | `EVALUATE { PQL.Assert.LibraryVersion() }` | `"0.9.0"` |
| Regression | Re-run every 0.8.0 suite on 0.9.0 and diff the four output columns | Identical, except the freshness rows' age, which depends on when they run |

## How pql-test will use it

pql-test's 0.8 catalog checks `frequency` today with an inline expression:

```dax
PQL.Assert.ShouldBeLessOrEqual(
    "ODCS orders slaProperties[1]: orders refreshed within the last 26 h",
    26,
    (UTCNOW() - MAXX(FILTER(INFO.PARTITIONS(), [TableID] = MAXX(FILTER(INFO.TABLES(), [Name] = "Orders"), [ID])), [RefreshedTime])) * 24
)
```

When 0.9.0 ships, a new `pql_assert_0_9` catalog will call `PQL.Assert.Tbl.LastRefreshShouldBeWithinHours(testName, tableName, maxAgeHours)` instead, which gives a clearer `Actual` (`TABLE NOT FOUND`, `NEVER REFRESHED`, or the age in hours). `latency` keeps mapping to `Col.MaxDateShouldBeWithinDays` / `…Hours`. The ODCS mapping, for the README if useful:

| ODCS SLA | `element` | PQL.Assert |
|---|---|---|
| `latency` | `table.column` (a load timestamp) | `Col.MaxDateShouldBeWithinHours` / `…Days` |
| `frequency` | `table` | `Tbl.LastRefreshShouldBeWithinHours` |
