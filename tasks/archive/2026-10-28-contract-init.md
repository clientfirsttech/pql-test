# Contract Init and Authoring Skill Epic

**Status**: ✅ COMPLETED (2026-10-28)

**Changed during the work (2026-10-28):**
- An untyped column gets an ODCS `description` saying why, not a YAML comment: it is valid ODCS and survives editing.
- Measure tables are also left out when their only columns are hidden placeholders (SampleModel's `_Measures[Measure Group]`).
- `--output` refuses a path inside the model folder, and reports a missing folder as a usage error.
- Tables are read in case-insensitive file-name order, so the starter is the same on Windows and Linux.
**Goal**: Make writing an ODCS contract for a semantic model easy: a command that starts one from the model, and skill guidance that lets an AI agent write the rest.

## Overview

The contract skill teaches an agent to lint, generate, run, and trace an existing contract, but nothing helps write one: there is no template, no "start from my model", and no list of the ODCS fields pql-test understands. plan.md already lists a "pbip importer (TMDL → starter ODCS contract)" as optional.

**Decided 2026-10-28 (maintainer):** build both a `pql-test contract init` command and a "Writing a contract" section in the contract skill.

**Choices made while planning (easy to reverse):**
- `init` prints the contract to stdout, and writes a file only with `--output FILE`, refusing to overwrite without `--force`. It only reads the model, so the "run never changes the project" rule holds.
- The starter states what the model already is: tables, columns, and their types. It adds no quality rules, so it lints clean and passes against the model; the author adds the rules that matter.
- ODCS v3.1.0, `status: draft`, `version: 1.0.0`, `id` and `name` from the model name (`--id` to override). ODCS names are the model's own table and column names, so no `pbiTable` / `pbiColumn` is needed.

---

## `pql-test contract init MODEL_PATH`

**Requirements**:
- Given a PBIP model (any MODEL_PATH form, including `local/<name>`), should emit a valid ODCS v3.1.0 contract with one schema object per table and one property per column, in TMDL order
- Given a column's TMDL `dataType`, should set the `logicalType` the type check maps back to the same model type: `string`→`string`, `int64`→`integer`, `double`→`number`, `decimal`→`number` with `pbiDataType: Currency`, `boolean`→`boolean`, `dateTime`→`date`; a column with no TMDL type (calculated) or a type with no ODCS equivalent (`binary`) gets no `logicalType`, and a `description` says why
- Given measure tables (no columns, or only hidden placeholder columns) or Power BI's automatic date tables (`LocalDateTable_*`, `DateTableTemplate_*`), should leave them out; given `--table NAME` (repeatable), should include only those tables
- Given `--output FILE`, should write it and refuse an existing file unless `--force`; otherwise should print to stdout
- Given the starter for each example model, `lint CONTRACT MODEL` should pass and `coverage` should report no skipped rules

---

## Writing-a-contract guidance

**Requirements**:
- Given the contract skill, should add a "Writing a contract" section: start with `init`, a minimal annotated template, the ODCS rules pql-test maps (and that skipped ones are reported, never enforced), when to use `pbiTable`, `pbiColumn`, and `pbiDataType`, and the loop `init` → edit → `lint CONTRACT MODEL` → `coverage` → `run`
- Given docs/contracts.md and the README contract table, should document `init`
- Given the skill tests, every `init` flag should appear in the skill, and the source and packaged skill should stay byte-identical
