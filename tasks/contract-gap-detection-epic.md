# Contract Gap Detection Epic

**Status**: 📋 PLANNED
**Goal**: A gap in `pql-test contract`'s ODCS-to-PQL.Assert coverage — a new ODCS rule kind, a new PQL.Assert release, or docs that drifted from the code — fails a test or an AIDD review step before it reaches a user, instead of surfacing only as a silent "unrecognised" skip.

## Overview

The PQL.Assert side of this mapping already guards itself: `test_function_matrix.py` fails when the vendored library gains a function nobody has classified, and `test_library_conformance.py` fails when a catalog calls a function with the wrong signature. The ODCS side has no equivalent. The bundled schemas define a handful of small, closed enums — quality metrics, quality types, `logicalType`, relationship types, and the `logicalTypeOptions` keys per type — and nothing checks that every value in each one is classified as mapped, approximated, or skipped-with-a-reason. A future ODCS release that adds a metric or an option key would show up only as `unrecognised library metric 'x'` in some contract's coverage report, not as a failing test. Separately, the hand-written mapping tables in `docs/contracts.md` can drift from the catalogs with no test noticing, and nothing in the AIDD review or release flow asks whether either side needs rechecking. This epic closes both gaps and gives learners runnable example contracts instead of test fixtures.

---

## ODCS Rule Matrix

Enumerate the closed vocabularies the bundled ODCS schemas define, and classify every value.

**Requirements**:
- Given the `metric` enum (`DataQualityLibrary`), the quality `type` enum (`DataQuality`), the `logicalType` enum, the relationship `type` enum, and the `logicalTypeOptions` property keys for each `logicalType` across the bundled ODCS v3.0.2, v3.1.0, and v3.2.0 schemas, should classify every value found (union across versions) as `mapped`, `dax-only` (reachable only via `engine: pql-test`), or `out-of-scope` with a reason, in a packaged `odcs_rules.yaml` alongside `pql_assert_functions.yaml`
- Given a value with no entry, should fail a test (mirroring `test_function_matrix.py`'s `test_only_non_assertions_are_out_of_scope`), so a future ODCS release that adds a metric or option key is caught before release, not discovered from a user's `coverage` output
- Given descriptive/governance property fields with no quality-rule meaning (`classification`, `role`, `partitioned`, `encryptedName`, `transformLogic`, `transformSourceObjects`, `criticalDataElement`, the `dimension` label on a quality rule), should record them as `out-of-scope` once, with the shared reason "descriptive metadata, not a data quality rule — no DAX check applies"
- Given `slaProperties.property`, which ODCS leaves as free text rather than an enum, should document it as a named exception the matrix cannot enumerate, and rely on `sla_rules`' existing generic skip for an unrecognised property name
- Given every value the matrix marks `mapped` or `dax-only`, should also require it to appear in at least one fixture under `python/tests/odcs/fixtures/` (reusing `every-row.odcs.yaml` and `rule-coverage.odcs.yaml` where possible, extending them only for values not already covered)

---

## Docs-to-Code Agreement

Catch drift between `docs/contracts.md`'s hand-written mapping tables and what the catalogs actually generate.

**Requirements**:
- Given every PQL.Assert function named in `docs/contracts.md`'s "Rule mapping" and "PQL.Assert 0.8" tables, should assert each one is a function some catalog op or the `pql_assert_functions.yaml` `dax` set actually names, so a renamed or removed function in the docs fails a test instead of silently misleading a reader
- Given every function a catalog generates or a contract can call directly, should assert it appears in `docs/contracts.md` somewhere (the mapping tables or the DAX-rules section), so a new mapping landing without a docs update fails a test
- Given the "skipped" / "not planned" tables in `docs/contracts.md`, should assert each named ODCS rule kind matches a reason actually produced by `map_contract` for an unmapped example, so a skip reason that changes wording leaves the docs correct or fails loudly

---

## AIDD Gap-Check Skill

Wire both matrices into the existing AIDD review and release flow, the same way `pql-test-docs-check` is wired in today.

**Requirements**:
- Given a new `aidd-custom/skills/pql-test-contract-gap-check/SKILL.md`, should describe checking for a new Bitol ODCS release and a new PQL.Assert (DAX Lib) release, running `test_function_matrix.py` and the new ODCS matrix test, and what to do on a failure: classify the new value, map it if a corresponding function exists, extend a fixture, and update `docs/contracts.md`
- Given `aidd-custom/AGENTS.md`'s "Documentation step" rule, should add a parallel "Contract gap-check step" rule: run the new skill in `/aidd-review` step 9 whenever `python/pql_test/odcs/`, a contract fixture, or `docs/contracts.md` changes, and before every release
- Given `aidd-custom/skills/index.md`, should list the new skill the same way the existing two are listed

---

## Example Contracts for Learners

Give a user runnable contracts instead of pointing them at test fixtures.

**Requirements**:
- Given a new `examples/contracts/` with three contracts (a starter from `init`, one exercising scenario tests and the direct-call form, one exercising `latency` and `frequency`), should lint clean and run with every mapped rule passing against `examples/SampleModel`, checked by a live test the same way `marvel.odcs.yaml` is
- Given `docs/contracts.md`'s "Quick start" and "Writing a contract" sections, should link to `examples/contracts/` instead of only showing inline snippets
- Given the video plan (`contract-videos.local.md`), should note that these become the demo material for videos 2, 7, and 8 in place of the test fixtures, once this epic lands

---

## Docs and Release

**Requirements**:
- Given `docs/contracts.md`, should add a short "How we keep this mapping complete" note pointing at the two matrix tests and the gap-check skill, so a future contributor knows why both pass today
- Given the release, should follow `pql-test-version-bump` and run `pql-test-docs-check`
