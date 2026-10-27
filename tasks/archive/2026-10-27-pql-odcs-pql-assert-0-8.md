# pql-odcs PQL.Assert 0.8 Adoption Epic

**Status**: ✅ COMPLETED (2026-10-27)
**Goal**: Let pql-odcs generate PQL.Assert 0.8.0 calls, so contract rules that were approximated or skipped against 0.7.1 become exactly mapped, while 0.7 output stays byte-identical.

## Overview

PQL.Assert 0.8.0 shipped the functions pql-odcs was missing: true-null counts, correct rates, blank-safe distinct and primary-key checks, `ShouldNotBeBetween`, multi-column key checks, duplicate-count thresholds, column pattern checks, and freshness. Until pql-odcs adopts them, contract owners get "approximated" or "skipped" for rules the library can now check exactly. A second, versioned catalog keeps models still on 0.7.x working and makes the choice explicit. The design is in [docs/pql-assert-gap-plan.md](../docs/pql-assert-gap-plan.md).

---

## Catalog Selection

Add `catalog/pql_assert_0_8.yaml` and a way to choose a catalog per run, without touching 0.7 output.

**Requirements**:
- Given no catalog option, should select the 0.7 catalog, and every golden file should stay byte-identical
- Given `--pql-assert 0.8` on `generate`, `coverage`, or `trace`, should map and render with the 0.8 catalog and name it in the suite header
- Given a mapper that wants an op the selected catalog lacks, should fall back to the 0.7 behaviour (approximated or skipped) rather than emit a partial call

---

## Exact Null and Key Rules

Map `required`, `primaryKey`, `unique`, and zero-duplicate rules to the functions that match their meaning.

**Requirements**:
- Given `required: true` under 0.8, should emit `Col.NullCountShouldBeAtMost(…, 0)` as mapped, including on string columns, because ODCS null means a true null
- Given `primaryKey` on one column under 0.8, should emit `Col.ShouldBePrimaryKey` as mapped
- Given `unique` or `duplicateValues mustBe 0` on a column under 0.8, should emit `Col.NonBlankValuesShouldBeDistinct` as mapped
- Given a composite `primaryKey` or a multi-column `duplicateValues mustBe 0` under 0.8, should emit `Tbl.RowsShouldBeDistinct` over a `SELECTCOLUMNS` projection as mapped

---

## Thresholds and Ranges

Map the comparators that 0.7 could only skip.

**Requirements**:
- Given `nullValues` with an absolute threshold under 0.8, should emit `Col.NullCountShouldBeAtMost`
- Given `nullValues` with `unit: percent` under 0.8, should emit `Col.NullRateShouldBeAtMostV2` with the percentage unchanged
- Given `duplicateValues` on a column with a non-zero ceiling under 0.8, should emit `Col.DuplicateCountShouldBeAtMost`
- Given `rowCount mustNotBeBetween` under 0.8, should emit `ShouldNotBeBetween` over `COUNTROWS`

---

## Pattern Rules

Translate only the simple regexes that PQL.Assert 0.8 can check exactly.

**Requirements**:
- Given a pattern of `^literal`, `literal$`, or a bare literal (no regex metacharacters), should emit `Col.ValuesShouldStartWith`, `Col.ValuesShouldEndWith`, or `Col.ValuesShouldContain` as mapped
- Given any other pattern, should stay skipped with a reason that says why it cannot be translated
- Given an `invalidValues` pattern rule with a non-zero ceiling, should stay skipped

---

## Freshness

Turn ODCS latency SLAs into a `Col.MaxDateShouldBeWithinDays` check.

**Requirements**:
- Given a `latency` slaProperty with a `table.column` element and a unit of days or hours under 0.8, should emit `Col.MaxDateShouldBeWithinDays` with the value converted to days
- Given any other SLA property, element, or unit, should stay skipped with a specific reason

---

## Version Detection in contract run

Let `pql-test contract run` pick the catalog from the live model.

**Requirements**:
- Given no `--pql-assert` option, should query `PQL.Assert.LibraryVersion()` over the run's XMLA connection and use 0.8 when it returns 0.8 or later
- Given the query errors or no connection exists, should use 0.7 and say so in one line
- Given `--pql-assert 0.7|0.8`, should skip detection and use the choice

---

## Docs and Release Notes

**Requirements**:
- Given the pql-odcs README, CHANGELOG, and mapping plan, should describe `--pql-assert`, the 0.8 mappings, and the 0.7 default
- Given the gap plan, should record that 0.8.0 shipped and pql-odcs adopted it
