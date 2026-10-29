# Contract Rule Coverage Epic

**Status**: 📋 PLANNED
**Goal**: Every PQL.Assert assertion is reachable from an ODCS contract, either through an ODCS rule with the same meaning or through a `type: custom`, `engine: pql-test` DAX rule, and freshness distinguishes source latency from refresh frequency.

## Overview

Contract owners can enforce only 26 of PQL.Assert 0.8's ~101 data assertions today. Ranges, text length, allowed values, missing values and relationships are skipped even though PQL.Assert has functions for them. Scenario tests (a measure's value in a given filter context) cannot be written in a contract at all. Freshness measures only the newest value in a column, and nothing separates "the source is late" (ODCS `latency`) from "the model stopped refreshing" (ODCS `frequency`). A successful refresh of stale source data looks fresh, so the two must never share a check. This epic maps the remaining ODCS rules, adds a DAX rule type for anything ODCS cannot express, and splits the freshness semantics in pql-test and, through a handoff document, in PQL.Assert.

---

## Value Ranges

Map `logicalTypeOptions` numeric bounds to the PQL.Assert 0.8 range functions.

**Requirements**:
- Given `minimum` and `maximum` on an `integer` or `number` property under 0.8, should emit `Col.ShouldBeInRange` as mapped
- Given only `minimum` or only `maximum`, should emit `Col.MinShouldBeAtLeast` or `Col.MaxShouldBeAtMost`
- Given `exclusiveMinimum: 0` with no other lower bound, should emit `Col.ShouldBePositive`
- Given an exclusive bound on an `integer` property, should convert it to the inclusive bound one step inward (`> n` becomes `>= n + 1`) and report it as mapped
- Given an exclusive bound other than 0 on a `number` property, bounds on `date` or `timestamp`, `multipleOf`, or `format`, should stay skipped with a specific reason
- Given the 0.7 catalog, should stay skipped with a reason naming `--pql-assert 0.8`, so every 0.7 golden file stays byte-identical

---

## Text Length

Map `minLength` and `maxLength` to `Col.TextLengthShouldBeInRange`.

**Requirements**:
- Given only one of `minLength` or `maxLength`, should fill the other with 0 or the largest INT64, so one call covers both
- Given a property whose `logicalType` is not `string`, should stay skipped with a reason

---

## Allowed Values

Map v3.2 `enum` and `invalidValues` with `arguments.validValues` to `Col.ValuesShouldBeInSet`.

**Requirements**:
- Given an allowed-value list, should emit it as a DAX table constructor with string literals escaped (`"` doubled), so values containing quotes cannot break the suite
- Given `invalidValues` with `validValues` and a zero ceiling, should emit `Col.ValuesShouldBeInSet` as mapped (NULL rows are skipped, as ODCS intends)
- Given `invalidValues` with `validValues` and a non-zero count or percent ceiling, should emit `Tbl.RowCountShouldBeAtMost` or `Tbl.RowRateShouldBeAtMost` over `FILTER(table, NOT ISBLANK(col) && NOT col IN {…})`

---

## Missing Values

Map `missingValues` to the completeness functions.

**Requirements**:
- Given no `arguments.missingValues` list, should treat the default (null and `""`) as missing and emit `Col.NullOrBlankRateShouldBeAtMostV2` for percent or zero ceilings, or `Tbl.RowCountShouldBeAtMost` for count ceilings
- Given an explicit list, should count a row as missing when it is null (if the list holds `null`) or its value is in the list, through `Tbl.RowCountShouldBeAtMost` or `Tbl.RowRateShouldBeAtMost`
- Given a floor comparator (`mustBeGreaterThan` and the like), should stay skipped, because a missing-value rule is a ceiling

---

## Relationships

Map v3.1 `relationships` to `Relationship.ShouldExist` in the Schema suite.

**Requirements**:
- Given a property-level or schema-level `foreignKey` relationship whose ends resolve to model columns through `pbiTable` / `pbiColumn`, should emit `Relationship.ShouldExist` with the resolved names
- Given a composite (array) relationship, or an end that names no contract property, should stay skipped with a specific reason
- Given `lint CONTRACT MODEL_PATH`, should report a relationship the model's TMDL does not define

---

## Freshness: Latency Is Data Age

Keep ODCS `latency` (source-to-destination delay) mapped only to the age of the newest value in a timestamp column.

**Requirements**:
- Given `latency` in hours, should emit `Col.MaxDateShouldBeWithinHours`. Days keep `Col.MaxDateShouldBeWithinDays`. Existing 0.8 suites that use hours change, and that is a documented regeneration
- Given `latency` whose `element` names a table with no column, should stay skipped with "latency needs a timestamp column; refresh time is not source latency"
- Given a comma-separated `element`, should emit one assertion per element
- Given any approximated latency rule, should give a reason saying it measures the newest row actually in the model (source delay plus refresh delay)

---

## Freshness: Frequency Is Refresh Recency

Map ODCS `frequency` to the time since the table's partitions last refreshed.

**Requirements**:
- Given `frequency` with a table `element` under 0.8, should emit `PQL.Assert.ShouldBeLessOrEqual` on the hours since `MAX(INFO.PARTITIONS()[RefreshedTime])` for that table, as approximated with the reason "proves the refresh ran, not that the source sent new data"
- Given any refresh check, should put it in its own `<Prefix>.RefreshAge.<ENV>.Tests` suite (not `Refresh`, which the DAX parser rejects in a function name), so an `INFO.*` permission error cannot fail the Schema or DataQuality rules
- Given `timeOfAvailability` or `retention`, should stay skipped with a specific reason

---

## PQL.Assert Freshness Handoff

Write `docs/pql-assert-freshness-request.md`, a self-contained brief to feed to the PQL.Assert repository for 0.9.0.

**Requirements**:
- Given a reader with no pql-test context, should specify `PQL.Assert.Tbl.LastRefreshShouldBeWithinHours(testName : STRING, tableName : STRING, maxAgeHours : DOUBLE)`: its table lookup through `INFO.PARTITIONS()` and `INFO.TABLES()` (as `Partitions.ShouldExist` does), the standard 4-column row, its `Expected` and `Actual` text, and its result for an unknown table, a never-refreshed partition, and an empty table
- Given PQL.Assert's backward-compatibility rules, should require it to be purely additive (no existing name, signature, or `Expected` / `Actual` text changes), with `LibraryVersion()` returning `0.9.0`
- Given the latency / frequency confusion, should specify the documentation changes: `Col.MaxDateShouldBeWithinDays` and `…Hours` describe **data age (ODCS latency)** when pointed at a load timestamp, and **refresh recency (ODCS frequency)** when pointed at a refresh-log column. The new function states that it measures refresh recency only, and that a successful refresh of stale source data passes it. The README gets a latency vs frequency table with one example of each
- Given what is not yet verified, should list the live checks PQL.Assert must run before release: whether `RefreshedTime` is UTC, its meaning for Direct Lake (reframe), DirectQuery, and calculated-table partitions, and the permissions `INFO.PARTITIONS()` needs for reader and admin identities
- Given the PQL.Assert test plan pattern, should list the passing and failing test cases for the new function

---

## Freshness: Adopt PQL.Assert 0.9

Add `catalog/pql_assert_0_9.yaml` once PQL.Assert 0.9.0 ships (blocked on the upstream release).

**Requirements**:
- Given `--pql-assert 0.9` or a model reporting `LibraryVersion()` 0.9 or later, should emit `Tbl.LastRefreshShouldBeWithinHours` for `frequency` in place of the 0.8 inline check
- Given `--pql-assert 0.8`, should keep emitting the inline 0.8 check byte-for-byte

---

## DAX Rules: Expression and Comparator

Map `type: custom` with `engine: pql-test` and `implementation: {expression, <one comparator>}` to the PQL.Assert scalar assertions.

**Requirements**:
- Given `mustBe`, `mustNotBe`, `mustBeGreaterThan`, `mustBeGreaterOrEqualTo`, `mustBeLessThan`, `mustBeLessOrEqualTo`, `mustBeBetween`, or `mustNotBeBetween`, should emit `ShouldEqual`, `ShouldNotEqual`, `ShouldBeGreaterThan`, `ShouldBeGreaterOrEqual`, `ShouldBeLessThan`, `ShouldBeLessOrEqual`, `ShouldBeBetween`, or `ShouldNotBeBetween` as mapped, on both catalogs
- Given `mustBe` with a string value, should emit `ShouldEqualExactly`, because DAX `=` ignores case and the contract's value does not
- Given an expression that contains `EVALUATE` or `DEFINE` outside a string literal, or unbalanced brackets or quotes, should skip the rule and have `lint` report it
- Given an expression that ends in a `//` comment, should still produce a well-formed call (the expression ends its own line)
- Given the coverage JSON, should keep status `mapped` and add `"source": "contract-dax"`, so existing consumers keep working and reviewers can tell hand-written DAX from translated rules

---

## DAX Rules: Direct Function Calls

Map `implementation: {function, args}` to a call of any PQL.Assert assertion, with pql-test supplying `testName`.

**Requirements**:
- Given a function name, should validate it and its argument count (required and optional) against a packaged signature list for the selected PQL.Assert version, which a conformance test keeps in sync with the vendored library
- Given `RetrieveTests*`, `LibraryVersion`, or an unknown function, should skip the rule and have `lint` report it
- Given string arguments, should emit them as DAX source unchanged, and numbers and booleans as DAX literals
- Given `type: custom` with any other engine, or no engine, should stay skipped with today's reason

---

## Coverage Matrix Test

Answer "is every PQL.Assert function reachable from a contract?" with a test, not a document.

**Requirements**:
- Given every assertion in the vendored PQL.Assert library, should classify each one as reached by an ODCS mapper, reached only through `engine: pql-test`, or out of scope with a reason (`BP.*` and the discovery helpers), and fail when an upstream function is added without a classification
- Given the existing golden fixtures, should keep them byte-identical apart from the documented latency-hours change, and cover every new mapping in a new golden fixture for 0.7 and 0.8

---

## Live Proof

Add must-pass and must-fail contracts against SampleModel to `test_contract_live.py`, covering every new mapping, both DAX rule forms, latency, and frequency.

**Requirements**:
- Given the must-fail contract, should fail each targeted rule for the reason its fixture states, not for a DAX error
- Given a run identity without `INFO.*` permission, should error only the RefreshAge suite

---

## Docs, Skill, and Release

Update the contract documentation and skill, and bump the version.

**Requirements**:
- Given `docs/contracts.md`, should replace "`type: custom` not planned" with the `engine: pql-test` rule reference, update the mapping and skipped tables, and add a "Freshness: latency vs frequency" section saying which column to point `latency` at (a load timestamp, not a business date) and why a contract needs both SLAs
- Given the contract skill, should teach both DAX rule forms and the latency / frequency split, with the source and packaged copies byte-identical
- Given the release, should follow `pql-test-version-bump`, run `pql-test-docs-check`, and record in `docs/pql-assert-gap-plan.md` that freshness moved to the 0.9 request
