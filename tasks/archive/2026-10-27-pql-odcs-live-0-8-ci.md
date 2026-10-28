# pql-odcs PQL.Assert 0.8 Live CI Epic

**Status**: ✅ COMPLETED (2026-10-28). SampleModel was republished with PQL.Assert 0.8.0, and `python/tests/test_contract_live.py` passed (14 tests) over the service connection once the secret was renewed. pql-odcs was later merged into pql-test ([merge epic](2026-10-28-merge-pql-odcs-agpl.md)).
**Goal**: Prove in the existing CI pipeline that pql-odcs's 0.8 output and `contract run` auto-detection work against a real model with PQL.Assert 0.8.0, and run the library variants the gap plan has not yet checked.

## Overview

The 0.8 catalog shipped (2026-10-27), but nothing has run it against a live model. Every example model in the CI workspace carries PQL.Assert 0.4.0 (SampleModel, RLS_Model, OLS_Model) or 0.6.2 (CodeCoverage). Stage 3a ([pytest.yml](../.github/workflows/pytest.yml)) already installs pql-odcs from source with `pql-test[contracts]`, ADOMD.NET, and the `PQL_*` service principal. It also already runs [test_contract_live.py](../python/tests/test_contract_live.py). So that test runs today, but `--pql-assert auto` detects 0.7 and the 0.8 path is never exercised. No new workflow, runner, or secret is needed; the missing piece is PQL.Assert 0.8.0 functions that the live query can see. Phase A puts them in the query, which needs no workspace change and unblocks verification now. Phase B deploys them into a model, which is the only way to test auto-detection end to end. `pql-odcs.yml` stays credential-free and cross-platform: live XMLA work belongs on the pql-test side of the license boundary.

**Decided 2026-10-27:** upgrade `examples/SampleModel` in place to PQL.Assert 0.8.0. PQL.Assert's MIT license allows vendoring 0.8.0 as a test fixture. The 0.8.0 source is `clientfirsttech/PQL.Assert` `src/lib/*.tmdl` at `origin/main` (manifest 0.8.0).

---

## Align the 0.8 Catalog with the Released Library

Checking the catalog against the released 0.8.0 TMDL found four ops that call functions which do not exist: the catalog followed the gap plan's proposed names. Every 0.8 suite using them would fail on a real model.

**Requirements**:
- Given `unique` or `duplicateValues mustBe 0` under 0.8, should emit `Col.NonNullValuesShouldBeDistinct` (the released name; NULLs ignored, `""` counts as a value)
- Given a simple pattern under 0.8, should emit `Col.ShouldStartWith` / `Col.ShouldEndWith` / `Col.ShouldContainString` with `matchCase` `"Y"`, so that all three are case-sensitive like a regex and are reported as mapped
- Given the vendored 0.8.0 fixture, should have a test that fails when any catalog op (0.7 or 0.8) names a function the library lacks or passes an argument count it does not accept

---

## Run What Exists Today

Get a green baseline for the 0.7 live path on `dev-odcs` before changing anything. `ci.yml` only runs on pushes to main/master/`copilot/**` and on pull requests, and `dev-odcs` has neither a PR nor a CI run yet.

**Requirements**:
- Given `dev-odcs` with no CI run, should trigger Stage 3a by opening a PR to main, or with `gh workflow run pytest.yml --ref dev-odcs`, and record whether `test_contract_live.py` ran or skipped
- Given the run's log, should confirm the two contract tests executed (not skipped) and that auto-detection chose 0.7

---

## Vendor the PQL.Assert 0.8.0 Library as a Test Fixture

Phase A needs the 0.8.0 function bodies, and the repo has only their signatures (in `catalog/pql_assert_0_8.yaml`).

**Requirements**:
- Given the PQL.Assert 0.8.0 package (MIT), should store it with a note on its source and version under `packages/pql-odcs/tests/fixtures/`. Changed 2026-10-27: MIT into MIT, not in the wheel, and the pql-odcs conformance test needs it on every OS
- Given the fixture, should have a unit test asserting every function is annotated `DAXLIB_PackageVersion = 0.8.0` and that every 0.8 catalog op has a matching function
- Given a test helper, should turn the fixture into query-scoped `DEFINE FUNCTION` text for only the functions the target model does not already define, since redefining a model function in the query is not known to work

---

## Live 0.8 Suites, Query-Scoped (Phase A)

Run pql-odcs's 0.8 output against the existing SampleModel dataset with the 0.8-only functions defined in the query, in the same way the gap plan's live checks were done.

**Requirements**:
- Changed 2026-10-27: a new `marvel-0-8.odcs.yaml` replaces running `marvel` and `marvel-must-fail` under 0.8, because those two reach only 3 of the 11 0.8 ops. It has one rule per 0.8 op
- Given `marvel-0-8.odcs.yaml` generated with `--pql-assert 0.8`, should give a pinned outcome per rule, where each entry has a comment naming the data fact that makes it fail (e.g. `DateDim[Year]` 815 nulls of 16,376 rows), taken from the gap plan's live-check numbers rather than copied from a first run
- Given the fixture contracts, should cover `Col.NullRateShouldBeAtMostV2` and `Col.ValuesShouldContain`, adding a contract rule if neither fixture emits them
- Given no `PQL_*` credentials or no pql-odcs, should skip the same way `test_contract_live.py` does

---

## Library Smoke for the Unrun Variants

`Col.BlankRateShouldBeAtMostV2` and `Col.NullOrBlankRateShouldBeAtMostV2` are never emitted by the 0.8 catalog, so no contract can reach them. Check them directly.

**Requirements**:
- Given SampleModel and query-scoped 0.8.0 definitions, should run `BlankRate…V2`, `NullOrBlankRate…V2`, and `ValuesShouldContain` with one passing and one failing threshold each, and assert pass/fail plus the `Actual` text shape (e.g. `"4.98% (815 of 16376 rows)"`)
- Given a result that disagrees with the gap plan, should fail with a message that points at the gap plan section, because the bug is upstream in PQL.Assert, not in pql-odcs

---

## Deployed 0.8 Model and Auto-Detection (Phase B)

Depends on the decision above, and on a maintainer publishing the upgraded model to the CI workspace. That publish is a manual, outward-facing step: there is no deploy workflow.

**Requirements**:
- Given the chosen model with `functions.tmdl` upgraded to PQL.Assert 0.8.0 and published, should have `contract run` with no `--pql-assert` select 0.8 and print the detection line
- Given that model, should parametrize `test_contract_live.py` over forced `0.7`, forced `0.8`, and `auto` (expected `0.8`), each with its own expected-failure set
- Given RLS_Model, which stays on 0.4.0, should assert live that `detect_pql_assert` returns `"0.7"`, so the old-library path keeps a live check
- Given SampleModel is upgraded, should keep Stage 3b green on SampleModel's existing suites (this is the 0.8 backward-compatibility check)
- Given 0.8.0's NULL policy changes results for NULL input, all-NULL columns, and empty tables, should check SampleModel's existing suites for affected calls before publishing, and note any expectation that changes

---

## Docs and Status

**Requirements**:
- Given the gap plan's status line, should mark the `BlankRate…V2`, `NullOrBlankRate…V2`, and `ValuesShouldContain` live checks as done, with the date and results
- Given `pytest.yml`'s header comment, should list the contract live tests and what they need
- Given `plan.md`, should move this epic to Completed Work
