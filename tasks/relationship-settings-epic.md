# Relationship Settings Epic

**Status**: 📋 PLANNED (2026-11-17)
**Goal**: A contract relationship can pin the settings on Power BI's Edit relationship dialog (cardinality, cross-filter direction, active, security filter), checked on PQL.Assert 0.8 and 0.9 today

## Overview

A contract relationship maps to `Relationship.ShouldExist` with its four ends only, so it keeps passing when someone makes the relationship inactive, switches it to cross-filter Both, or changes its cardinality, and each of those changes the numbers the model returns.

PQL.Assert 0.9.0's `ShouldExist` already checks cardinality (`fromCardinality`, `toCardinality`) and the RLS checkbox "Apply security filter in both directions" (`securityFilteringBehavior`). It cannot check the cross-filter direction or the active state, and its docs call `securityFilteringBehavior` the "filter direction", which it is not: on CodeCoverage (cross-filter Both, security box unchecked) `ShouldExist(…, "BothDirections")` fails with `SecurityFiltering: OneDirection`. PQL.Assert 0.10.0 adds `crossFilteringBehavior` and `isActive` (PQL.Assert `docs/relationship-settings-plan.md` on `dev`); until it ships, pql-test checks those two from `INFO.VIEW.RELATIONSHIPS()`, which `ShouldExist` already queries. Moving them into the single 0.10 call is [a separate epic](pql-assert-0-10-relationship-epic.md).

ODCS has no relationship fields for these settings, so they use `customProperties` on the relationship, like `pbiTable`, `pbiColumn`, and `pbiDataType`:

```yaml
relationships:
- to: schema/date_dim/properties/date_id
  customProperties:
  - property: pbiCardinality      # manyToOne | oneToOne | oneToMany | manyToMany
    value: manyToOne
  - property: pbiCrossFilter      # single | both | automatic (or oneDirection | bothDirections)
    value: single
  - property: pbiActive           # true | false
    value: true
  - property: pbiSecurityFilter   # single | both (or oneDirection | bothDirections): RLS only
    value: single
```

---

## Contract Properties

**Requirements**:
- Given a relationship with `pbiCardinality`, `pbiCrossFilter`, `pbiActive`, or `pbiSecurityFilter`, should check that setting of the model relationship
- Given a relationship without them, should check existence only, as today
- Given a value that is not one of the listed values (in any case), `lint` should report it, so a typo cannot skip the check
- Given `pbiSecurityFilter`, docs and messages should call it the security filter (RLS), never the filter direction

---

## Mapping On PQL.Assert 0.8 And 0.9

**Requirements**:
- Given `pbiCardinality` or `pbiSecurityFilter`, should pass them to the one `Relationship.ShouldExist` call (`manyToOne` as `"Many"`, `"One"`)
- Given `pbiCrossFilter` or `pbiActive`, should add a check of that setting against `INFO.VIEW.RELATIONSHIPS()`, under the same rule id, with Expected and Actual naming the setting and both values
- Given a relationship the model lacks, the setting checks should fail saying the relationship was not found
- Given PQL.Assert 0.7, should keep skipping the relationship rule
- Given the same contract, should generate byte-identical suites on every run

---

## Read And Compare The Model's Settings

**Requirements**:
- Given TMDL, should read each relationship's `fromCardinality`, `toCardinality`, `crossFilteringBehavior`, `isActive`, and `securityFilteringBehavior`, with Power BI's defaults when a line is absent (many, one, oneDirection, true, oneDirection)
- Given `lint CONTRACT MODEL_PATH`, should report a stated setting that differs from the TMDL, with both values
- Given `coverage --live`, should read the same settings from the connected model

---

## Write The Model's Settings

**Requirements**:
- Given `init`, should write the four settings each relationship has today
- Given an uncovered relationship, `coverage` should suggest it with its four settings

---

## Tell PQL.Assert 0.9 From 0.10

**Requirements**:
- Given a model whose functions all exist but with fewer parameters than a catalog calls, `--pql-assert auto` and `doctor` should not pick that catalog, and should say which function is too old

---

## Epic Vision (Definition of Done)

### Quality Gates (All Must Pass)

- **Tests**: `cd python && pytest` passes, including the ODCS rule matrix, golden suites, and docs-to-code agreement
- **Live**: on CodeCoverage (cross-filter Both) `pbiCrossFilter: both` passes and `single` fails, in Power BI Desktop
- **Documentation**: docs/contracts.md has the four properties, the dialog-to-property table, and the mapping rows; the contract skill (source and packaged) describes them, with a version bump
