# pql-odcs v0.1 Epic

**Status**: 📋 PLANNED
**Goal**: Ship pql-odcs v0.1. It is an MIT package that turns ODCS v3.x contract quality rules into PQL.Assert `*.Tests.dax` suites and gives a rule-by-rule coverage report. pql-test exposes it as `pql-test contract …` through an optional extra.

## Overview

Teams that write ODCS data contracts can't currently enforce them against a Power BI semantic model. They hand-write DAX tests that drift from the contract, and nothing tells them which contract rules are actually checked. pql-odcs closes that gap:
- It generates PQL.Assert suites straight from the contract.
- It reports every rule as mapped, approximated, or skipped, so no rule is dropped silently.
- It traces pql-test failures back to contract rule IDs.

It ships under MIT so Bitol and datacontract-cli users can adopt it standalone. pql-test (BUSL-1.1) consumes it only one way, through a plugin hook. The full design, mapping table, and discovery decisions are in [docs/pql-odcs-implementation-plan.md](../docs/pql-odcs-implementation-plan.md).

---

## Workspace Scaffold

Create `packages/pql-odcs/` as its own package, and a root uv workspace that links it to `python/`.

**Requirements**:
- Given `uv sync` at the repo root, should install both packages editable, with pql-test resolving pql-odcs from `packages/pql-odcs/` rather than PyPI
- Given the pql-odcs `pyproject.toml`, should declare `license = "MIT"`, `license-files = ["LICENSE"]`, `requires-python = ">=3.9"`, and runtime dependencies limited to PyYAML, jsonschema, and click
- Given the existing pip-based CI (`cd python && pip install -e .`), should keep working unchanged with no uv on the runner
- Given the version-alignment test, should pass unchanged, because pql-odcs versions independently and adds no SKILL.md under `skills/` or `python/pql_test/skills/`

---

## License Boundary Markers

Mark which license covers which path, in a form both people and CI checks can read.

**Requirements**:
- Given `LICENSE.txt` and its synced copy `python/LICENSE.txt`, should carry an identical scope note pointing to `LICENSES.md`
- Given `LICENSES.md`, should map each path to its license, its published package, and the dependencies it may have
- Given every source file under `packages/pql-odcs/` and `python/`, should start with the matching `# SPDX-License-Identifier:` line
- Given the pql-odcs NOTICE, should name Client First Technologies as copyright holder and keep PQL.Assert's MIT copyright notice for any bundled `functions.tmdl`
- Given a change under `packages/pql-odcs/`, should require a pql-odcs CODEOWNERS review and a DCO sign-off, documented in CONTRIBUTING.md

---

## Contract Loader

Parse and validate ODCS contracts from a YAML file or an already-parsed dict.

**Requirements**:
- Given a YAML path and the equivalent dict, should return identical validated contracts
- Given an `apiVersion` outside 3.0.x / 3.1.x, should fail and name the supported range
- Given a contract that breaks the bundled ODCS JSON schema, should report every violation with its JSON path, not just the first

---

## Name Resolution

Map each schema object and property to a semantic model table and column.

**Requirements**:
- Given `customProperties` `pbiTable` / `pbiColumn`, should use them over a sidecar entry and over the logical name
- Given a `--mapping` sidecar entry and no customProperties, should use the sidecar; otherwise should fall back to the logical name
- Given a sidecar entry for an object that is not in the contract, should report it rather than silently ignore it

---

## IR and Versioned Catalog

Define the frozen IR dataclasses and the `pql_assert_0_7.yaml` catalog that turns IR ops into PQL.Assert calls.

**Requirements**:
- Given Python 3.9, should import the IR (`from __future__ import annotations` for `str | None`)
- Given any PQL.Assert function name or argument order, should appear only in the catalog file, never in Python code
- Given an IR op missing from the catalog, should fail at emit time, naming the op and the catalog version, and never emit a partial call
- Given a rule with an ODCS `id`, should use that `id` as `rule_id`; otherwise should use a path such as `payments.transaction_id.quality[0]` that is the same on every run of an unchanged contract

---

## Schema Rule Mappers

Map the v0.1 schema rows: object present, properties present, closed schema, required, and distinct.

**Requirements**:
- Given a schema object with N properties, should emit one `Tbl.ShouldHaveColumns` per table, not one per column
- Given no closed-schema opt-in, should not emit `Tbl.ShouldNotHaveExtraColumns`
- Given `required: true` or `nullValues mustBe 0`, should map to `Col.NullRateShouldBeAtMost(…, 0)`, not `Col.ShouldNotBeNull`, until gap plan C1 is confirmed
- Given a column that is any combination of `primaryKey`, `unique`, and `duplicateValues mustBe 0`, should emit exactly one `Col.ShouldBeDistinct`, with every source rule ID traced to it

---

## rowCount Mappers

Map the `rowCount` library metric with all its v0.1 comparators.

**Requirements**:
- Given `rowCount mustBeGreaterThan 0`, should emit `Tbl.ShouldHaveRows`, not `ShouldHaveMoreRowsThan(0)`
- Given `mustBe n` or `mustBeGreaterThan n`, should emit `Tbl.ShouldHaveRowCount` or `Tbl.ShouldHaveMoreRowsThan`, with arguments in catalog order (threshold before table)
- Given `mustBeLessThan`, `mustBeLessOrEqualTo`, `mustBeGreaterOrEqualTo`, `mustNotBe`, or `mustBeBetween`, should emit the matching comparator over `COUNTROWS`
- Given `mustNotBeBetween`, should be SKIPPED with a reason naming fallback R2 / v0.2

---

## Rule Registry

Dispatch every rule to a mapper and guarantee each rule gets exactly one outcome.

**Requirements**:
- Given `type: sql`, `type: custom`, `type: text`, or a library metric scheduled after v0.1, should return SKIPPED with a reason naming the planned release, or saying that none is planned
- Given a rule shape the registry doesn't recognise (for example an ODCS 3.2 addition), should report it as SKIPPED and never drop it or crash
- Given any contract, should produce exactly one `RuleOutcome` per rule
- Given a rule with `severity: warning`, should carry that severity into every IR assertion it produces

---

## DAX Emitter

Render IR assertions through the catalog into one `*.Tests.dax` file per suite.

**Requirements**:
- Given a suite prefix and an environment, should name suite functions `<Prefix><Suite>.<ENV>.Tests`, which matches pql-test's environment token, and send warning-severity assertions to `<Prefix><Suite>.<ENV>WARN.Tests`
- Given each assertion, should name it `ODCS <contractId> <ruleId>: <description>`, with DAX string escaping
- Given the same contract on any OS, should produce byte-identical output with `\n` line endings
- Given each generated file, should start with `// Generated by pql-odcs <version> from <contract> — do not edit` and a note that results are model-scoped

---

## Coverage Report

Report every rule's status as text and as JSON.

**Requirements**:
- Given `--format json`, should emit every rule with its rule ID, status, assertion count, and reason, in a stable documented schema
- Given text output, should not import pql-test's `cli_format.py`, because of the license boundary
- Given `--fail-on-skipped` and at least one skipped rule, should print the full report and then exit 1

---

## Contract CLI Group

Define the `contract` click group once, with `generate`, `coverage`, and `lint`, and mount it as the standalone `pql-odcs` command and under the `pql_test.commands` entry point.

**Requirements**:
- Given `generate` and an existing target file without the generated header, should refuse to overwrite it unless `--force` is passed
- Given `--dry-run`, should print the DAX to stdout and write nothing
- Given no `--suite-prefix`, should derive one from the contract's `dataProduct`, then its `name`, so generated suites never collide with hand-written ones such as `Schema.DEV.Tests`
- Given a MODEL_PATH that is not a PBIP folder, should exit 2, saying that query and deploy targets arrive in v0.2 and v0.3
- Given `lint` on a contract with an invalid schema or unresolved names, should list every problem and exit 1; usage errors should exit 2

---

## Result Tracing

Join pql-test `--output` JSON results back to contract rule IDs (`trace` command).

**Requirements**:
- Given pql-test's documented `--output` JSON, should map each assertion result to its rule ID by parsing the `ODCS <contractId> <ruleId>:` test-name prefix
- Given results from a different contract ID, or from tests not generated by pql-odcs, should list them as unmatched rather than drop them
- Given a contract rule with no result, should report it as not executed, which is distinct from skipped
- Given the parser, should be written from the README's documented format and tested against fixture JSON, never copied from pql-test code

---

## Fixtures, Golden and Property Tests

Build the fixture contracts and the regression layers that protect generated output.

**Requirements**:
- Given contracts for SampleModel's MarvelFact and DateDim (good, and a must-fail copy), and an every-row contract that includes skipped rules, should regenerate byte-identical golden `.dax` files
- Given `.gitattributes`, should pin golden `.dax` files to `eol=lf`, so checkouts on Windows match
- Given random valid contracts (hypothesis), should never crash the pipeline, and every rule should get a status

---

## pql-test Plugin Hook

Load extra click commands from the `pql_test.commands` entry point group.

**Requirements**:
- Given Python 3.9, where `entry_points(group=…)` is unavailable, should still discover plugins
- Given a plugin that raises on load, should print a one-line stderr warning naming the plugin and the error, and keep every built-in command working
- Given `PQL_TEST_STRICT_PLUGINS=1`, should re-raise plugin load errors so CI fails loudly
- Given a plugin command whose name collides with a built-in, should keep the built-in and warn

---

## Contract Run Command

Add `pql-test contract run` (BUSL), which runs generate, execute, and trace in one step, plus the `contracts` extra.

**Requirements**:
- Given `pip install pql-test[contracts]`, should install `pql-odcs>=0.1,<0.2`, and `contract run` should attach only when pql-odcs is importable
- Given a live connection, should execute the generated suites' own `DEFINE FUNCTION … EVALUATE` text through `run_tests()`, because `run_tests_from_model` would skip suites that are not yet registered in the model
- Given `--env DEV`, should run both the DEV and DEVWARN suites, and only DEV failures should affect the exit code
- Given failures, should group them by contract rule ID, using `cli_format.py`, and honor the existing `--log-format` and `--output` flags

---

## Contract Skill and Docs

Document the feature for users and for the AI harness.

**Requirements**:
- Given a new `contract` skill, should be byte-identical in `skills/` and `python/pql_test/skills/`, carry pql-test's version, and trigger a bump per `pql-test-version-bump`
- Given promptfoo-eval, should include a `contract` skill case that checks the CLI guidance
- Given the pql-test README, should add a "Testing against ODCS data contracts" section linking to the pql-odcs README's mapping table
- Given the pql-odcs README, should document install, CLI usage, the v0.1 mapping table with statuses, and name-resolution precedence

---

## License Guardrail CI

Add blocking CI checks that enforce the license boundary on every pull request.

**Requirements**:
- Given import-linter, should fail when `pql_odcs` imports `pql_test`
- Given a file under `packages/pql-odcs/` or `python/` with a missing or wrong SPDX header, should fail
- Given the built pql-odcs wheel, should fail if it contains anything outside `pql_odcs/`, LICENSE, NOTICE, or README.md
- Given pip-licenses on pql-odcs's resolved dependencies, should fail on any license that is not MIT, BSD, or Apache-2.0

---

## Cross-Platform Test CI

Run pql-odcs tests on every OS, and check both install paths.

**Requirements**:
- Given a pull request, should run pql-odcs tests on Linux, macOS, and Windows, for Python 3.9 and the newest supported version
- Given a clean venv without pql-test, should install pql-odcs and pass CLI smoke tests
- Given a local `packages/pql-odcs` install plus `./python[contracts]`, should list `generate`, `coverage`, `lint`, `trace`, and `run` under `pql-test contract --help`

---

## pql-odcs Release Workflow

Publish pql-odcs independently with `release-pql-odcs.yml`.

**Requirements**:
- Given a `pql-odcs-vX.Y.Z` tag, should build from `packages/pql-odcs/` only, check that the tag matches its `pyproject.toml` version, and publish through Trusted Publishing
- Given a `pql-odcs-v*` tag, should not trigger pql-test's `release.yml`, which keeps its name so its existing trusted publisher stays valid

---

## Live Integration Run

Prove generated suites against SampleModel on a real connection.

**Requirements**:
- Given the good SampleModel contract, should pass every mapped rule through `pql-test contract run`
- Given the must-fail contract, should fail exactly the rules marked as expected failures, each traced to its rule ID
- Given no PQL_* credentials, should skip under the existing `live` pytest marker

---
