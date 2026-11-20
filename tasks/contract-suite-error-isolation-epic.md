# Contract Suite Error Isolation Epic

**Status**: ✅ COMPLETED (2026-11-17)
**Goal**: When one generated assertion cannot run, `pql-test contract run` reports the error on that rule and the real result on every other rule in its suite

## Overview

`contract run` runs each generated suite as one DAX query. When one call in a suite cannot run, the whole query fails, and `trace` attributes that single error to every rule in the suite. A contract with `measure-check` (`[Measure] > 0`) and `measure-2-check` (`[Measure 2] > 0`, where `Measure 2` returns text) reported the type error on both rules, so the owner of `measure-check` could not tell whether their rule ran. Free-form contract DAX makes this common, but any suite can hit it, for example when the model lacks a function one call uses.

The generated `*.Tests.dax` files stay as they are (byte-identical on every run). Only the run that follows a suite failure changes.

---

## Re-Run A Failed Suite One Call At A Time

**Requirements**:
- Given a suite that fails to run because one of its calls errors, should report that error on the rule whose call errors
- Given the same suite, should report the passed or failed result of every other rule in it
- Given a suite of one call that fails to run, should report the error on its rule without running it again
- Given no XMLA connection, should report every rule as not executed without running anything again

---

## Epic Vision (Definition of Done)

### Quality Gates (All Must Pass)

- **Tests**: `cd python && pytest` passes
- **Documentation**: docs/contracts.md describes how a suite that fails to run is reported
