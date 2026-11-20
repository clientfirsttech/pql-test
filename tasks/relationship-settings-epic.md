# Relationship Settings Epic

**Status**: ✅ COMPLETED (2026-11-19), except the live quality gate, which waits on CodeCoverage open in Power BI Desktop · planned 2026-11-17, re-planned 2026-11-19 for PQL.Assert 0.9.1
**Goal**: A contract relationship can pin the four settings on Power BI's Edit relationship dialog that change results (cardinality, cross-filter direction, active, security filter), checked by one `Relationship.ShouldExist` call on PQL.Assert 0.9.1

## Overview

A contract relationship checks only that its two columns are related, so it keeps passing when someone makes the relationship inactive, switches it to cross-filter Both, or changes its cardinality, and each of those changes the numbers the model returns. PQL.Assert 0.9.1 (a patch release, now on DAX Lib) gives `Relationship.ShouldExist` optional arguments 9 and 10, `crossFilteringBehavior` and `isActive`, and reports security filter value 3 as `None`; 0.8.0 and 0.9.0 already take cardinality and `securityFilteringBehavior` (arguments 6 to 8). So this epic adds `customProperties` named after the TMDL property each one checks, like `pbiDataType`, and a `--pql-assert 0.9.1` catalog that passes all of them in one call. On older catalogs pql-test passes what the library can check and reports the rest as not checked, rather than querying `INFO.VIEW.RELATIONSHIPS()` itself: updating PQL.Assert is a DAX Lib update, and `doctor` names the version to install.

PQL.Assert 0.9.0's docs called `securityFilteringBehavior` the "filter direction": on CodeCoverage (cross-filter Both, security box unchecked) `ShouldExist(…, "BothDirections")` fails with `SecurityFiltering: OneDirection`. 0.9.1 fixed the docs; contracts name the property after TMDL so the two cannot be confused. "Assume referential integrity" (DirectQuery only) is out of scope, and so is `init` writing relationships (it writes none today; `coverage` suggests them).

This epic replaces the 0.10 follow-up epic planned on 2026-11-17: PQL.Assert shipped the change as 0.9.1.

---

## Contract Properties

Add four relationship `customProperties`, named after the TMDL property, with dialog words as values where the dialog has words.

**Requirements**:
- Given `pbiCardinality`, should accept `manyToOne`, `oneToMany`, `oneToOne`, or `manyToMany`, read from the relationship's `from` to its `to` (one dialog dropdown, two TMDL properties: `fromCardinality`, `toCardinality`)
- Given `pbiCrossFilteringBehavior`, should accept the dialog words `single` or `both`, the TMDL names `oneDirection` or `bothDirections`, and `automatic` (TMDL only, not on the dialog)
- Given `pbiIsActive`, should accept `true` or `false`
- Given `pbiSecurityFilteringBehavior`, should accept only the TMDL names `oneDirection` (unchecked), `bothDirections` (checked), or `none` (limited relationships), never `single`/`both`, because the dialog control is a checkbox and those words belong to the cross-filter dropdown
- Given a relationship without these properties, should check existence only and generate exactly what it generated before this epic
- Given a value that is not one of the listed values (in any case), `lint` should report it, so a typo cannot skip the check
- Given `pbiSecurityFilteringBehavior`, docs and messages should call it the security filter (RLS), never the filter direction

---

## Mapping

Pass every stated setting the selected catalog's PQL.Assert can check to the one `Relationship.ShouldExist` call.

**Requirements**:
- Given `--pql-assert 0.9.1`, should pass every stated setting to `ShouldExist`, with `""` for each one the contract leaves out, and TMDL names for values (`manyToOne` as `"Many"`, `"One"`; `single` as `"OneDirection"`; `true` as `"TRUE"`)
- Given `--pql-assert 0.8` or `0.9`, should pass `pbiCardinality` and `pbiSecurityFilteringBehavior` `oneDirection`/`bothDirections`, and report the rule approximated, naming each setting it did not check and the `--pql-assert 0.9.1` it needs (`pbiCrossFilteringBehavior`, `pbiIsActive`, and `pbiSecurityFilteringBehavior: none`, which 0.9.0 reports as `Unknown`)
- Given PQL.Assert 0.7, should keep skipping the relationship rule
- Given the same contract, should generate byte-identical suites on every run

---

## Tell PQL.Assert 0.9.0 From 0.9.1

Pick the 0.9.1 catalog only for a model whose `ShouldExist` takes the new arguments.

**Requirements**:
- Given a connected model whose `PQL.Assert.LibraryVersion()` is 0.9.1 or later, `--pql-assert auto` should pick 0.9.1; given 0.9.0, it should pick 0.9 and warn that pql-test supports up to 0.9.1
- Given a model folder whose functions all exist but with fewer parameters than a catalog passes (`ShouldExist` with 8), `doctor` should not recommend that catalog, and should say which function is too old
- Given `--pql-assert 0.9.1` on a model with 0.9.0, should warn as for any catalog newer than the model supports
- Given `engine: pql-test` direct calls, should keep working under `--pql-assert 0.9` (a patch release adds only optional arguments)

---

## Read And Compare The Model's Settings

Read the settings from TMDL and the live model, using Power BI's defaults for absent lines.

**Requirements**:
- Given TMDL, should read each relationship's `fromCardinality`, `toCardinality`, `crossFilteringBehavior`, `isActive`, and `securityFilteringBehavior`, with Power BI's defaults when a line is absent (many, one, oneDirection, true, oneDirection)
- Given `lint CONTRACT MODEL_PATH`, should report a stated setting that differs from the TMDL, naming the contract property and both values
- Given `coverage --live`, should read the same settings from the connected model's `INFO.RELATIONSHIPS()`

---

## Suggest The Model's Settings

**Requirements**:
- Given an uncovered relationship, `coverage` should suggest it with its four settings as the model has them, with dialog words where they exist (`single`, `both`)

---

## Epic Vision (Definition of Done)

### Quality Gates (All Must Pass)

- **Tests**: `cd python && pytest` passes, including the ODCS rule matrix, the function matrix, the library conformance test (every catalog against the vendored 0.9.1 package), golden suites (unchanged for contracts without settings), and docs-to-code agreement
- **Live**: on CodeCoverage (cross-filter Both, PQL.Assert 0.9.1) in Power BI Desktop, `pbiCrossFilteringBehavior: both` passes and `single` fails
- **Documentation**: docs/contracts.md has the four properties, a YAML example, the dialog-to-property table (dialog control, TMDL property, contract property, values), the mapping rows, and a PQL.Assert 0.9.1 section; the contract skill (source and packaged) describes them, with a version bump; `pql-test-contract-gap-check` runs clean
