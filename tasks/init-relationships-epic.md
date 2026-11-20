# Init Writes Relationships Epic

**Status**: ✅ COMPLETED (2026-11-19)
**Goal**: `pql-test contract init` writes the model's relationships, with their settings, so a starter contract checks them from the first run

## Overview

`init` writes a starter contract that states what the model is today, but only its tables, columns, and types: relationships had to be added later from `coverage` suggestions. Now that a contract relationship can pin cardinality, cross-filter direction, active state, and the security filter ([relationship settings epic](relationship-settings-epic.md)), the starter should carry each relationship with the settings it has, written the same way `coverage` suggests one.

---

## Write Relationships

**Requirements**:
- Given a model relationship whose two tables are in the starter, should write it as a schema-level foreign key under its `from` table, with its four settings (`pbiCardinality`, `pbiCrossFilteringBehavior`, `pbiIsActive`, `pbiSecurityFilteringBehavior`) in dialog words where the dialog has them
- Given ends whose names a `table.property` reference can hold, should use that form; otherwise should reference by id and give the schema object and property that id, unique within its array, reusing an id already given
- Given a relationship to a table the starter leaves out (a measure table, an automatic date table, or one `--table` did not pick), should not write it
- Given the same model, should write byte-identical output

---

## Starter Still Passes

**Requirements**:
- Given the starter for each example model, `lint` against the model should pass, and no rule should be skipped under the newest `--pql-assert`
- Given the starter's header, should say it states the model's relationships too

---

## Epic Vision (Definition of Done)

### Quality Gates (All Must Pass)

- **Tests**: `cd python && pytest` passes
- **Documentation**: docs/contracts.md's `init` section and the contract skill (source and packaged) say `init` writes relationships
