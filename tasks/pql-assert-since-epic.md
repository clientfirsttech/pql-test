# PQL.Assert Function Versions Epic

**Status**: ✅ COMPLETED (2026-11-19)
**Goal**: A contract's direct PQL.Assert call needs only the PQL.Assert version that function needs, so vendoring a new release never blocks calls to functions it did not change

## Overview

An `engine: pql-test` rule can call any PQL.Assert assertion by name. pql-test checks the call against the newest vendored signatures and, so a call cannot reach a function the model lacks, requires a catalog of that release's minor version. That one requirement covers every function: vendoring 0.9.0 made a call to `Col.MeanShouldBeInRange` (unchanged since 0.7.1) need `--pql-assert 0.9`, and vendoring 0.10.0 would do the same again. Like a lock file's minimum versions, each function should carry the oldest release with the signature a call needs, and the call should need only that.

`pql_assert_functions.yaml` records, for each function, the first supported release that has it (`since`), and for a function whose arguments grew in a later release, the release each argument count arrived in. The history is read once from the DAX Lib packages 0.7.1 to 0.9.1 (0.7.1, the oldest release pql-test supports, stands for "0.7.1 or earlier"); after that the gap check records each new release's additions.

---

## Record Each Function's Versions

**Requirements**:
- Given every function in `pql_assert_functions.yaml`, should record `since`: a release, or a mapping of release to parameter count for a function whose parameters grew (`Relationship.ShouldExist`: 0.8.0 → 8, 0.9.1 → 10)
- Given a function whose newest recorded parameter count differs from its `params`, the function matrix test should fail, so a changed signature cannot go unrecorded
- Given every catalog op, its function should be available with that many arguments at the catalog's minimum version, or a test should fail

---

## Gate Direct Calls Per Function

**Requirements**:
- Given a direct call, should skip it only when the selected catalog is older than the release that has the function with that many arguments, naming the release and the `--pql-assert` value that has it
- Given a direct call to a function unchanged since 0.8.0 under `--pql-assert 0.8`, should map it, as before PQL.Assert 0.9.0 was vendored
- Given a direct call to `Relationship.ShouldExist` with 9 or 10 arguments under `--pql-assert 0.9`, should skip it, naming 0.9.1

---

## Epic Vision (Definition of Done)

### Quality Gates (All Must Pass)

- **Tests**: `cd python && pytest` passes, golden output reviewed
- **Documentation**: docs/contracts.md describes which version a direct call needs; the gap-check skill tells the maintainer to record `since` for a new or changed function
