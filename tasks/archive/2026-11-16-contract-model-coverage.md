# Contract Model Coverage Epic

**Status**: ✅ COMPLETED (2026-11-16)
**Goal**: Given an ODCS contract and a semantic model, show which tables, columns, relationships, and measures the contract leaves uncovered, so its owner knows what to add, without ever writing to the model.

## Overview

A contract owner cannot see which parts of a model their contract leaves untested: `contract coverage` only reports how the contract's rules map to PQL.Assert, and `code-coverage` only counts test functions saved in the model, which `contract run` never deploys. Deploying the tests to measure them is ruled out, because a write over XMLA stops a Desktop-authored model from being downloaded as a PBIX, and a failed cleanup leaves test functions in production. Most of the answer is already in the contract, since every generated assertion names its table and column. A spike on 2026-11-16 (SampleModel, in Desktop and in the service) showed that `INFO.CALCDEPENDENCY("QUERY", …)` reports what un-deployed DAX references without changing the model, but folds in the columns that referenced measures use internally. This epic renames the rule-mapping report to `contract mapping`, adds `contract coverage CONTRACT MODEL_PATH`, which works from files by default, and adds an opt-in `--live` mode that asks the engine about the DAX a contract wrote.

---

## Rename the Rule Mapping Report

Rename `contract coverage CONTRACT` to `contract mapping CONTRACT`, freeing `coverage` for the model report.

**Requirements**:
- Given `contract coverage CONTRACT` with no MODEL_PATH, should fail with a usage error that points to `contract mapping`, so existing scripts fail loudly instead of reading a different report
- Given `contract mapping`, should print the same text and JSON (`schemaVersion` 1) the old command printed
- Given the documented Python API `pql_test.odcs.coverage.build_report`, should move it to `pql_test.odcs.mapping_report` (`pql_test.odcs.mapping` is the rule mappers' package)
- Given every doc, skill, CLI message, workflow, and promptfoo eval that means the rule-mapping report (including `linux.yml`, `tests/promptfoo/tests/contract.yaml`, and vision.md lines 42, 58, and 70), should name `contract mapping`

---

## List the Model's Objects from TMDL

Extend the TMDL reader in `pbip.py` to list every object the report counts.

**Requirements**:
- Given a table's TMDL, should list its measures with their home table, and mark each column as data or calculated
- Given a hidden column, should still list it, because the keys relationships use are usually hidden
- Given Power BI's automatic date tables and measure tables (measures, only hidden placeholder columns, and no relationship), should leave them out by reusing `init`'s rules, so `init`'s starter contract covers every listed table and column
- Given a fact table that hides every column and shows only measures, should count it, because it joins its dimensions

---

## Find What Each Rule Covers from the Contract

Turn each rule into the model objects it covers, without connecting to the model.

**Requirements**:
- Given a rule in the Schema suite, should mark its table, column, or relationship as listed; given a rule in any other suite, should mark its target as values tested
- Given an object the contract lists whose every rule is skipped, should show it as listed but not enforced rather than not covered
- Given a column reference, should also count its table, because the engine reports a table row for every column reference and the two modes must agree
- Given a contract-DAX rule, should read `'Table'[Column]`, `Table[Column]`, and `[Name]` references outside string literals and comments (a bracket after a keyword, as in `RETURN [Total]`, is a bare name), resolve `[Name]` to a measure first, and report a name that matches nothing as unresolved instead of guessing
- Given a contract-DAX rule placed under a table, should not count that table unless its DAX references it
- Given a rule that references a measure, should not count what that measure uses internally (direct references only, as in `code-coverage`)

---

## Add the Contract Coverage Command

`contract coverage CONTRACT MODEL_PATH` classifies every listed model object and reports it.

**Requirements**:
- Given a PBIP MODEL_PATH without `--live`, should run without ADOMD.NET, so it works in Linux CI
- Given each table, column, relationship, and measure, should classify it as values tested, listed only, or not covered, with rule ids as evidence, through `cli_format.py` and the same layout as `code-coverage`
- Given a calculated column with no value rule, should list it as its own gap, because its values come from DAX, which only a rule on its values tests
- Given a measure, should never show it as listed only, because an ODCS schema has no place to list a measure
- Given roles, partitions, and calculation groups, should leave them out and say why
- Given `--min-coverage N`, should compare the share of objects with at least one enforced rule, using `code-coverage`'s rounding so 100 cannot pass with any gap
- Given `--format json`, should emit `schemaVersion: 1` output described by a packaged JSON schema, with a test that validates real output against it

---

## Show What to Change in the Contract

Turn the gaps into edits a contract owner or an agent can apply.

**Requirements**:
- Given a table or column missing from the contract, should print an ODCS YAML snippet built with `init`'s property builder
- Given an uncovered measure, should print a `type: custom`, `engine: pql-test` rule template that references it
- Given a contract table, column, or relationship the model lacks, should report it in the same run by reusing `lint`'s model checks, so one command answers both what to add and what to remove

---

## Ask the Engine About Contract DAX

With `--live`, replace the text scan for contract-DAX rules with `INFO.CALCDEPENDENCY("QUERY", …)`.

**Requirements**:
- Given a contract-DAX rule, should ask once and keep only MEASURE rows, then replace those measure references (outside string literals) with `BLANK()`, ask again, and keep only TABLE and COLUMN rows, because the engine also lists columns used inside measures, at any depth
- Given several rules, should batch them in one query as `UNION(SELECTCOLUMNS(INFO.CALCDEPENDENCY("QUERY", q), "rule", <index>, …))`, because the engine leaves its own `[QUERY]` column empty
- Given FUNCTION rows and internal `RowNumber-<GUID>` columns, should drop them
- Given any evidence, should label it as found by the engine or by the text scan
- Given SampleModel and `examples/contracts/scenario-tests.odcs.yaml` under `-m live`, should credit `[Running Total of Character Appearances]` and `MarvelFact` to `running-total-does-not-exceed-row-count`, should not credit `MarvelFact[DateID]` or `DateDim[DateID]`, and should leave the model's function and dependency counts unchanged

---

## Connect Live Mode to Desktop and the Service

Use `contract run`'s connection path and the connected model's own object list.

**Requirements**:
- Given `local/<name>`, a PBIP path with workspace and dataset IDs (flags or `PQL_*` variables), or stored `auth login` credentials, should connect exactly as `contract run` does
- Given `--live`, should list the model's objects from the connected model's `INFO.*` functions (as `code-coverage` does), with the file-only mode's exclusions, so objects and evidence come from the same published version
- Given an identity without write permission on the model, should count from the PBIP folder and the text scan and say why, never report 0%
- Given a machine without ADOMD.NET, should fail `--live` with `xmla_unavailable()`'s reason, and the file-only mode should keep working

---

## Document and Release

Explain how contract coverage is counted, and ship the breaking rename.

**Requirements**:
- Given docs/contracts.md, should explain the three coverage levels, the direct-reference rule, why tests are never deployed to measure coverage, and the write permission `--live` needs
- Given the breaking rename, should bump the minor version (0.3.0) by following the version-bump skill
