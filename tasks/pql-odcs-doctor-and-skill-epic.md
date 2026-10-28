# pql-odcs Doctor and Skill Epic

**Status**: 📋 PLANNED
**Goal**: Give standalone pql-odcs users (Bitol, datacontract-cli) the two pql-test conveniences that make sense without XMLA: a readiness check, and an installable AI skill.

## Overview

pql-test users get `check-prereqs` (pql-test has no `doctor` command; `check-prereqs` is the closest one) and `skill` (list, print, and install skills into Claude, Copilot, Cursor, or Windsurf). Standalone pql-odcs users get neither. That matters most for the PQL.Assert version, the most likely failure: suites generated with `--pql-assert 0.8` fail on a model that still has 0.7, and pql-odcs never tells you which version the model has. pql-test's other commands (`auth`, `run-tests`, `retrieve-tests`, `retrieve-test`, `code-coverage`) all need XMLA, which the vision keeps in pql-test, so they are not brought over. pql-test's `cli_format.py`, `skills_resolver.py`, and skill install code are BUSL-1.1, so pql-odcs reimplements what it needs from scratch and copies nothing. Harness install paths are facts, not code, so reusing them is fine.

**Decided 2026-10-27:** the command is named `doctor`, and the pql-odcs skill is written fresh under MIT. It is not derived from `skills/contract/SKILL.md`, which is BUSL-1.1.

---

## Offline `contract doctor` (pql-odcs)

Add `doctor` to the `contract` group, so it appears as both `pql-odcs doctor` and `pql-test contract doctor`.

**Requirements**:
- Given no arguments, should report: Python version, pql-odcs version, PyYAML/jsonschema/click versions, bundled ODCS schema versions, available PQL.Assert catalogs, and whether pql-test is installed (via `importlib.metadata` only, never an import)
- Given a PBIP `MODEL_PATH`, should check that the model directory and `DAXQueries/` exist, read the PQL.Assert version from the `DAXLIB_PackageVersion` annotations in `definition/functions.tmdl`, and recommend a `--pql-assert` value
- Given a model whose PQL.Assert functions carry more than one version, or none, should warn and name the versions found
- Given suite files in `DAXQueries/` that pql-odcs did not generate but would overwrite, should list them and mention `--force`
- Given `--format json`, should emit one machine-readable report; given any failed check, should exit 1, keeping the existing 0/1/2 exit-code convention
- Given the import-linter contract, should still pass (TMDL is read as data)

---

## Live Checks in `pql-test contract doctor` (pql-test)

Extend the doctor from `contract_run.py`, the same way `run` is added to the group today.

**Requirements**:
- Given a model path and a working connection, should add: XMLA connection resolves, and the deployed `PQL.Assert.LibraryVersion()` via `detect_pql_assert`
- Given a TMDL version that differs from the deployed version (e.g. 0.8.0 committed, 0.7 deployed), should flag the drift, because suites generated from the committed model will fail against the deployed one
- Given `pql-test check-prereqs`, should add a row for the optional `pql-odcs` (contract commands available, with version) that does not fail the check when pql-odcs is missing
- Given the pql-test skill or CLI text changes, should bump the pql-test version per `aidd-custom/skills/pql-test-version-bump`

---

## Offline `--pql-assert auto` for generate, coverage, trace (optional)

Reuse the doctor's TMDL detection, so standalone users can match the model without knowing its version.

**Requirements**:
- Given `--pql-assert auto` with a PBIP model, should pick the catalog from `functions.tmdl` and print one line saying which version was found
- Given no option, should keep 0.7 as the default, and every golden file should stay byte-identical

---

## pql-odcs Skill Content

Write a skill that ships inside the pql-odcs wheel, never under `skills/` or `python/pql_test/skills/`.

**Requirements**:
- Given `packages/pql-odcs/src/pql_odcs/skills/pql-odcs/SKILL.md`, should cover generate, coverage, lint, trace, and doctor, and point to `pql-test contract run` for running suites
- Given the skill's frontmatter, should carry the pql-odcs version, and a test should fail when it does not match `packages/pql-odcs/pyproject.toml`
- Given the skill name, should differ from pql-test's `contract` skill so both can be installed in one harness

---

## `pql-odcs skill` Command

Add `skill` to the standalone `pql-odcs` root only. pql-test already has `pql-test skill`, so a `pql-test contract skill` would be a confusing duplicate.

**Requirements**:
- Given `pql-odcs` with no `skill` options, should list the skill; given a skill name, should print it
- Given `--install claude|copilot|cursor|windsurf` or `--all`, should install the skill with a version marker; given `--show`, `--uninstall`, or `--dry-run`, should behave like pql-test's flags of the same name, reimplemented without copying code
- Given `pql-test contract --help`, should list `doctor` but not `skill`, which means `main()` needs a root group that mounts the contract commands plus `skill`

---

## Guardrails, CI, and Docs

**Requirements**:
- Given the wheel-contents guardrail, should still pass with the skill under `pql_odcs/`, and the skill should be added to `package-data`
- Given the `standalone-install` job, should smoke-test `pql-odcs doctor --model examples/SampleModel.SemanticModel` (expecting a 0.7 recommendation for its 0.4.0 library) and `pql-odcs skill --install claude --dry-run`
- Given the `plugin-install` job, should require `doctor` in `pql-test contract --help`
- Given the pql-odcs README and CHANGELOG, should document `doctor` and `skill` and bump the pql-odcs minor version
