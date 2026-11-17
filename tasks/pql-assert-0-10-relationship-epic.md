# PQL.Assert 0.10 Relationship Epic

**Status**: 📋 PLANNED (2026-11-17) · **Blocked on**: PQL.Assert 0.10.0 released on DAX Lib
**Goal**: On a model with PQL.Assert 0.10.0, a contract relationship's settings are checked by one `Relationship.ShouldExist` call

## Overview

[The relationship settings epic](relationship-settings-epic.md) checks cardinality and the security filter through `ShouldExist`, and cross-filter direction and active state through `INFO.VIEW.RELATIONSHIPS()`, because PQL.Assert 0.9.0 cannot check those two. PQL.Assert 0.10.0 adds them to `ShouldExist` as optional arguments 9 and 10, `crossFilteringBehavior` and `isActive` (PQL.Assert `docs/relationship-settings-plan.md`), without a new function or a breaking change. This epic adds a `pql_assert_0_10` catalog that uses them, the way `pql_assert_0_9` replaced the inline refresh-age expression with `Tbl.LastRefreshShouldBeWithinHours`.

Contracts do not change: the same `pbiCrossFilter` and `pbiActive` properties generate one call on 0.10 and the separate checks on 0.8 and 0.9.

---

## Catalog For PQL.Assert 0.10

**Requirements**:
- Given a model with PQL.Assert 0.10.0, should check every stated relationship setting in one `Relationship.ShouldExist` call, with no `INFO.VIEW.RELATIONSHIPS()` check
- Given a model with PQL.Assert 0.8 or 0.9, should generate exactly what it generated before this epic
- Given a model whose `ShouldExist` has 8 parameters, `--pql-assert auto` and `doctor` should pick 0.9, not 0.10
- Given a connected model, should pick 0.10 from `PQL.Assert.LibraryVersion()` returning `0.10.0`
- Given `--pql-assert 0.10` on a model with 0.9, should warn as for any newer catalog than the model supports

---

## Library Fixture And Gap Check

**Requirements**:
- Given the released 0.10.0 package, should vendor it as `python/tests/odcs/fixtures/pql-assert-0.10.0/`, and the conformance test should check the catalog's calls against it
- Given the PQL.Assert function matrix, should record `Relationship.ShouldExist` with 10 parameters, 5 of them optional

---

## Epic Vision (Definition of Done)

### Quality Gates (All Must Pass)

- **Tests**: `cd python && pytest` passes, with golden suites for 0.9 unchanged and new ones for 0.10
- **Live**: a model on 0.10.0 passes and fails the same relationship cases as on 0.9
- **Documentation**: docs/contracts.md lists the 0.10 catalog and its single call; `pql-test-contract-gap-check` runs clean
- **Depends on me (the maintainer)**: publishing PQL.Assert 0.10.0 to DAX Lib, and updating the example models and the published test models to 0.10.0
