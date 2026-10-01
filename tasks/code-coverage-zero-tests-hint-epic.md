# Code Coverage Zero-Tests Hint Epic

**Status**: 📋 PLANNED
**Goal**: Make it obvious when `code-coverage` reports 0 discovered tests because PQL.Assert isn't installed, instead of leaving the user to guess from a raw percentage table.

## Overview

A user running `pql-test code-coverage` against a model without PQL.Assert installed gets `Tests discovered: 0` followed by a coverage table that looks like an ordinary (if extreme) low-coverage result, with no indication that coverage cannot be measured at all until the PQL.Assert framework is installed. The fix adds a hint line rather than replacing the report, since the eligible/excluded breakdown is still accurate information even with zero tests.

---

## Show an Install Hint When Zero Tests Are Discovered

**Requirements**:
- Given `code-coverage`'s text output and `report.test_count == 0`, should print an additional line after "Tests discovered: 0" pointing out that if PQL.Assert isn't installed in this model, coverage cannot be measured until it is
- Given `report.test_count > 0`, should not print this hint (unchanged behavior)
- Given the `--format json` output path, should not be affected — the hint is a text-mode UX addition only
