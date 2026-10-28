# pql-odcs: ODCS Contracts → PQL.Assert — Implementation Plan

Originally drafted 2026-10-24 by John Kerski. Imported and adjusted during AIDD discovery on 2026-10-25. The v0.1 work is tracked in [tasks/archive/2026-10-25-pql-odcs-v0.1.md](../tasks/archive/2026-10-25-pql-odcs-v0.1.md).

## Discovery decisions (2026-10-25)

| Topic | Decision |
|---|---|
| Package name | **`pql-odcs`** (import `pql_odcs`, console script `pql-odcs`, release tag `pql-odcs-v*`). Replaces the draft name `odcs-pql` throughout. Free on PyPI as of 2026-10-25. |
| MIT copyright holder | **Client First Technologies** (same licensor as pql-test's BUSL-1.1) |
| Vision | `vision.md` updated to describe pql-odcs as an MIT companion package with a one-way license boundary |
| Epic scope | The epic covers **v0.1 only**. v0.2, v0.3, and v1.0 items are in the `plan.md` backlog. |
| pql-test release workflow | **Keep `release.yml` as is.** The PyPI trusted publisher is bound to that file name, so renaming it to `release-pql-test.yml` would mean re-registering the publisher. The `v*` tag glob already doesn't match `pql-odcs-v*`. GitHub doesn't apply `paths:` filters to tag pushes, so "scope to `python/**`" can't work. |
| Root license file | It is `LICENSE.txt`, not `LICENSE`. The scope note goes in `LICENSE.txt` and in its synced copy `python/LICENSE.txt`. |
| ODCS 3.2 | **Supported in v0.1** (decided 2026-10-25). The 3.2.0 schema is bundled. Quality rules are unchanged from 3.1. The 3.2 `enum` is reported as skipped until v0.2 (`Col.ValuesShouldBeInSet`). `map` and `vector` properties have no model column; rules inside a map's key or value are reported as skipped. |
| Python floor | pql-odcs core keeps `requires-python >= 3.9`. The `[datacontract]` extra needs Python 3.10+ because datacontract-cli 1.2.7 requires `>=3.10,<3.15`, so the extra gets a Python-version marker. `importlib.metadata.entry_points(group=…)` only exists on 3.10+, so pql-test's plugin hook needs a 3.9 fallback. |
| `contract run` execution path | With a live connection, `run_tests_from_model` only runs suites already registered in the model ([discovery.py](../python/pql_test/runner/discovery.py)). Freshly generated suites are skipped as "not registered in the deployed dataset". So `contract run` builds `PqlTest`s from the generated files and executes their `DEFINE FUNCTION … EVALUATE` text with `run_tests()`. |
| Warning suites | Keep the proposed separate `<Suite>.<ENV>WARN.Tests.dax` suites. pql-test matches environments exactly on the second-to-last name token, so `--environment DEV` does not pick them up. `contract run --env DEV` must run both suites, and only the DEV suite decides the exit code. |
| Name mapping | **customProperties only** (decided 2026-10-26): `pbiTable` / `pbiColumn` on the contract, else the logical name. The sidecar file was removed before release. customProperties is ODCS's own extension point, valid in 3.0–3.2, and travels with the contract (the datacontract-cli adapter receives only the contract object). ODCS 3.2's `vendor` field on custom properties allows namespacing later without breaking. |
| Generated `.dax` files | **Both workflows supported** (decided 2026-10-26): regenerate in CI with `contract run` (files git-ignored), or commit them and fail CI on drift (`generate` + `git diff --exit-code`). Documented in the pql-odcs README. |
| Still open | Counsel review of `LICENSES.md` and the NOTICE wording (parked as the last epic). |
| Gaps in the source plan | The **Milestones** section was empty, and the **Plugin loading masks errors** risk had no mitigation (proposed below). The PQL.Assert gap plan is now [docs/pql-assert-gap-plan.md](pql-assert-gap-plan.md) (C1–C5, R1–R8, D1). It contains only backward-compatible changes, and every finding in it was verified against SampleModel. |

## Summary

Add an MIT-licensed package, `pql-odcs`, to the pql-test monorepo. It converts ODCS v3.1 data contract quality rules into PQL.Assert DAX test suites. pql-test (BUSL-1.1) consumes it as an optional extra and exposes it as `pql-test contract …`. The same package ships standalone on PyPI for Bitol and datacontract-cli users.

## Goals

- One shared core: parsing, mapping, DAX emission, and coverage reporting live only in pql-odcs.
- Two front doors: a standalone `pql-odcs` CLI and a `pql-test contract` command group.
- A coverage report that marks every contract rule as mapped, approximated, or skipped, so nothing is dropped silently.
- Traceability: every generated test name carries the contract ID and rule ID, and pql-test results map back to them.
- A clean license boundary: MIT code never imports or copies BUSL code.

## Non-goals for v0.1

- Translating `type: sql` rules to DAX automatically.
- Running Soda, Great Expectations, or other `type: custom` engines.
- SLA and freshness checks.
- Writing results back into the ODCS contract.

## Monorepo layout

The new package sits beside `python/` under `packages/`, with its own `pyproject.toml`, LICENSE, tests, and changelog. A uv workspace at the root links the two packages for local development, so an editable install of pql-test picks up pql-odcs from source.

```
pql-test/                          # repo root
├── LICENSE.txt                    # BUSL-1.1 (unchanged) + scope note
├── LICENSES.md                    # which license covers which path
├── pyproject.toml                 # uv workspace: members = [python, packages/pql-odcs]
├── python/                        # pql-test (BUSL-1.1)
│   ├── pyproject.toml             # extra: contracts = ["pql-odcs>=0.1,<0.2"]
│   └── pql_test/
│       ├── cli.py                 # loads plugins from entry points
│       └── contract_run.py        # NEW: `pql-test contract run` (BUSL)
├── packages/
│   └── pql-odcs/                  # MIT
│       ├── LICENSE                # MIT
│       ├── NOTICE                 # attribution, trademark note
│       ├── pyproject.toml
│       ├── CHANGELOG.md
│       ├── README.md
│       ├── src/pql_odcs/
│       │   ├── __init__.py
│       │   ├── loader.py          # parse + JSON-schema validate ODCS
│       │   ├── naming.py          # warehouse → semantic model names
│       │   ├── ir.py              # neutral assertion model
│       │   ├── mapping/           # one module per ODCS rule family
│       │   │   ├── library.py     # rowCount, nullValues, ...
│       │   │   ├── schema.py      # tables, columns, relationships
│       │   │   └── registry.py    # rule → mapper lookup
│       │   ├── catalog/
│       │   │   └── pql_assert_0_7.yaml  # function names + arg order
│       │   ├── emit/
│       │   │   └── dax.py         # IR → *.Tests.dax
│       │   ├── coverage.py        # mapped / approximated / skipped
│       │   ├── results.py         # pql-test JSON → rule IDs
│       │   └── cli.py             # click group `contract`
│       ├── adapters/
│       │   └── datacontract_cli.py
│       └── tests/
│           ├── fixtures/          # sample .odcs.yaml contracts
│           ├── golden/            # expected .dax outputs
│           └── test_*.py
└── .github/
    ├── CODEOWNERS
    └── workflows/
        ├── release.yml            # pql-test, tag v* (unchanged name — see decisions)
        └── release-pql-odcs.yml   # tag pql-odcs-v*
```

## Licensing model

The rule is one-way: pql-test (BUSL) may depend on pql-odcs (MIT); pql-odcs never imports, vendors, or copies pql-test code. This is a plan, not legal advice. Have counsel confirm the points marked open.

| Path | License | Published as | May depend on |
|---|---|---|---|
| `python/` | BUSL-1.1 | `pql-test` on PyPI | pql-odcs (optional extra) |
| `packages/pql-odcs/` | MIT | `pql-odcs` on PyPI | PyYAML, jsonschema, click only |
| `packages/pql-odcs/adapters/` | MIT | inside pql-odcs | datacontract-cli (optional extra, MIT, Python ≥3.10) |

**How the boundary is marked**

- Every source file under `packages/pql-odcs/` starts with `# SPDX-License-Identifier: MIT`; files under `python/` carry `BUSL-1.1`.
- The root `LICENSE.txt` gets a scope note: BUSL-1.1 covers the repository except paths listed in `LICENSES.md`.
- The pql-odcs wheel and sdist include only its own LICENSE and NOTICE, built from `packages/pql-odcs/` alone.
- `pyproject.toml` declares `license = "MIT"` with `license-files = ["LICENSE"]`.

**What the MIT side may know about pql-test**

- PQL.Assert function names and argument order, kept as data in the catalog file. The generated DAX calls these functions but contains none of their code.
- pql-test's documented `--output` JSON shape, for `results.py`. It is written fresh from the documented format and never copied from pql-test's parser.

PQL.Assert itself is MIT-licensed (v0.7.1 on DAX Lib), so pql-odcs may bundle its `functions.tmdl` for query-scoped runs and persistent deploys. PQL.Assert's copyright notice must be kept in NOTICE.

**Contributions**

- Contributions to `packages/pql-odcs/` use a DCO sign-off (matches Linux Foundation and Bitol norms).
- CODEOWNERS requires a pql-odcs maintainer's review for any change under that path.

## Package architecture

The core is a straight pipeline with a neutral intermediate representation (IR) in the middle, so mapping and DAX emission can be tested separately.

1. **Load** (`loader.py`): reads the YAML, or accepts an already-parsed dict (the datacontract-cli adapter hands its ODCS object over this way). Checks `apiVersion` against the supported versions (3.0.x, 3.1.x, 3.2.x) and validates against the bundled ODCS JSON schema.
2. **Resolve names** (`naming.py`): maps each schema object and property to a semantic model table and column. It uses `customProperties` keys `pbiTable` / `pbiColumn`, with the logical name as the fallback.
3. **Map** (`mapping/`): `registry.py` dispatches each rule, by type and metric, to a mapper that returns IR assertions plus a coverage status.
4. **Emit** (`emit/dax.py`): renders IR assertions through the catalog into one `*.Tests.dax` file per suite.
5. **Report** (`coverage.py`): writes a coverage table (text and JSON) listing every rule and its status.
6. **Trace results** (`results.py`): reads pql-test's `--output` JSON and joins failures back to contract rule IDs.

### IR sketch

```python
# SPDX-License-Identifier: MIT
from __future__ import annotations  # Python 3.9: allows `str | None` in annotations

from dataclasses import dataclass
from enum import Enum

class Status(Enum):
    MAPPED = "mapped"              # exact equivalent
    APPROXIMATED = "approximated"  # close, documented difference
    SKIPPED = "skipped"            # no target; reason required

@dataclass(frozen=True)
class Target:
    table: str                     # semantic model name
    column: str | None = None

@dataclass(frozen=True)
class Assertion:
    rule_id: str                   # contract id + rule path
    suite: str                     # "Schema" | "DataQuality"
    op: str                        # catalog key, e.g. "col.not_null"
    target: Target
    args: dict                     # thresholds, value lists
    severity: str = "error"

@dataclass(frozen=True)
class RuleOutcome:
    rule_id: str
    status: Status
    assertions: tuple[Assertion, ...]
    reason: str | None = None
```

### Catalog

`catalog/pql_assert_0_7.yaml` maps each IR op to a PQL.Assert call template. When PQL.Assert adds or renames a function, only this file changes.

```yaml
# Targets PQL.Assert 0.7.1 (DAX Lib)
min_version: "0.7.1"
col.null_rate_at_most:
  fn: PQL.Assert.Col.NullRateShouldBeAtMost
  args: [testName, columnRef, maxNullPct]
col.distinct:
  fn: PQL.Assert.Col.ShouldBeDistinct
  args: [testName, columnRef]
col.in_set:
  fn: PQL.Assert.Col.ValuesShouldBeInSet
  args: [testName, columnRef, allowedValuesTable, allowedValuesColumn]
tbl.more_rows_than:
  fn: PQL.Assert.Tbl.ShouldHaveMoreRowsThan
  args: [testName, threshold, tableToCheck]   # threshold before table
cmp.lt:
  fn: PQL.Assert.ShouldBeLessThan
  args: [testName, threshold, actual]
```

**Test naming**: `ODCS <contractId> <ruleId>: <description>`. Rule IDs use the ODCS v3.1 `id` field when present. Otherwise they use a stable path such as `payments.transaction_id.quality[0]`.

## Rule mapping catalog

Phase 1 ships the rows marked v0.1. The coverage report shows the rest as skipped until they land. The ODCS library metrics are `rowCount`, `duplicateValues`, `nullValues`, `missingValues`, and `invalidValues`, each with one comparator.

| ODCS rule | PQL.Assert v0.7.1 output | Status | Release |
|---|---|---|---|
| Schema object present | `Tbl.ShouldExist` | mapped | v0.1 |
| Properties present | `Tbl.ShouldHaveColumns` (one call per table) | mapped | v0.1 |
| Closed schema (opt-in flag) | `Tbl.ShouldNotHaveExtraColumns` | mapped | v0.1 |
| `required: true`, `nullValues mustBe 0` | `Col.NullRateShouldBeAtMost(…, 0)`. C1 is confirmed: `Col.ShouldNotBeNull` only checks that some value exists, so it is never used. Switch to `Col.NullCountShouldBeAtMost(…, 0)` from 0.8.0. | mapped (approximated on string columns) | v0.1 |
| `primaryKey`, `unique`, property `duplicateValues mustBe 0` | `Col.ShouldBeDistinct` | mapped | v0.1 |
| `rowCount mustBeGreaterThan 0` | `Tbl.ShouldHaveRows` | mapped | v0.1 |
| `rowCount mustBe n` | `Tbl.ShouldHaveRowCount` | mapped | v0.1 |
| `rowCount mustBeGreaterThan n` | `Tbl.ShouldHaveMoreRowsThan` | mapped | v0.1 |
| `rowCount` other comparators | `ShouldBeLessThan`, `ShouldBeLessOrEqual`, `ShouldBeGreaterOrEqual`, `ShouldNotEqual`, `ShouldBeBetween` on `COUNTROWS` | mapped | v0.1 |
| `logicalType` / `physicalType` | `Tbl.ColumnDataTypeShouldBe`, via an ODCS-to-model type table | mapped | v0.2 |
| v3.1 relationships | `Relationship.ShouldExist` with cardinality and filter direction | mapped | v0.2 |
| `logicalTypeOptions` minimum / maximum | `Col.ShouldBeInRange`, `Col.MinShouldBeAtLeast`, `Col.MaxShouldBeAtMost` | mapped | v0.2 |
| `logicalTypeOptions` minLength / maxLength | `Col.TextLengthShouldBeInRange` | mapped | v0.2 |
| `nullValues` with `unit: percent` | `Col.NullRateShouldBeAtMost` (units per C2) | mapped | v0.2 |
| `missingValues` (null and blank) | `Col.NullOrBlankRateShouldBeAtMost` | mapped | v0.2 |
| `missingValues` custom tokens, `mustBe 0` | `Col.ValuesShouldNotBeInSet` | mapped | v0.2 |
| `invalidValues` with `validValues`, `mustBe 0` | `Col.ValuesShouldBeInSet` | mapped | v0.2 |
| Schema-level `duplicateValues`, 2 columns | `Col.ComboShouldBeDistinct` | mapped | v0.2 |
| `nullValues` absolute threshold | `ShouldBeLessOrEqual` on `COUNTBLANK` (R4) | fallback | v0.2 |
| `invalidValues` / `missingValues` with threshold or percent | `ShouldBeLessOrEqual` over a `FILTER` count (R5) | fallback | v0.2 |
| Schema-level `duplicateValues`, 3+ columns | `SUMMARIZE` row-count comparison (R3) | fallback | v0.2 |
| `mustNotBeBetween` | `ShouldBeTrue` with an OR expression (R2) | fallback | v0.2 |
| `duplicateValues` non-zero threshold | `COUNTROWS - DISTINCTCOUNT` comparison (R6) | fallback | v0.3 |
| `invalidValues` with pattern | `ShouldMatch` per C3 / R7, else skipped | skipped | v0.3 |
| `type: sql` | none | skipped; optional LLM-drafted DAX stub marked for review | later |
| `type: custom`, `type: text` | none | skipped | none |
| `slaProperties` freshness (R8) | none | skipped | none |

"Fallback" rows emit a hand-built expression until the gap plan function (R-number) ships, then switch over through a catalog update.

Rules with `severity: warning` are emitted into a separate `<Suite>.<ENV>WARN.Tests.dax` suite, so CI can run them without failing the build.

Gaps in PQL.Assert itself are tracked in [docs/pql-assert-gap-plan.md](pql-assert-gap-plan.md): a version function (`LibraryVersion`), threshold variants, 3+ column keys, column patterns, freshness, and clarifications C1–C5 against v0.7.1. All of them are additive 0.8.0 functions. Until each ships, pql-odcs either emits the fallback expression or reports the rule as skipped, then adopts the new function through a `pql_assert_0_8.yaml` catalog.

## CLI surface

One click group, `contract`, is defined once in `pql_odcs/cli.py` and mounted in two places. `run` exists only inside pql-test because it needs the XMLA runner.

| Command | Standalone `pql-odcs` | `pql-test contract` | What it does |
|---|---|---|---|
| `generate CONTRACT MODEL_PATH --env ENV` | yes | yes | Writes `*.Tests.dax` into `MODEL_PATH/DAXQueries/` |
| `coverage CONTRACT [--format text\|json]` | yes | yes | Lists every rule with mapped / approximated / skipped |
| `lint CONTRACT` | yes | yes | Schema-validates the contract and checks name mappings resolve |
| `trace CONTRACT RESULTS_JSON` | yes | yes | Joins pql-test results to rule IDs |
| `run CONTRACT MODEL_PATH --env ENV` | no | yes | Runs generate, then pql-test's runner, then trace, in one step |

**Shared flags**:
- `--dry-run` prints the DAX to stdout.
- `--suite-prefix` sets the suite prefix; it defaults to the contract's `dataProduct`, then its `name`.
- `--fail-on-skipped` exits 1 if any rule is skipped, for strict CI.

**Exit codes**:
- 0 means success.
- 1 means the contract is invalid, or `--fail-on-skipped` was triggered.
- 2 means a usage error.
- `run` inherits pql-test's exit codes for test failures.

Generated files carry a header line, `// Generated by pql-odcs <version> from <contract> — do not edit`. `generate` refuses to overwrite a file without that header unless `--force` is passed.

## datacontract-cli adapter

The adapter is a library-level plugin, not a new `datacontract` command. Per the datacontract-cli docs, custom formats are only available through the Python library, not the standalone `datacontract` command. The standalone `pql-odcs` CLI remains the command-line path. A `datacontract export pql-assert` command would need an upstream pull request (moved to v1.0, optional).

**How it plugs in**: subclass `Exporter`, implement `export(...)`, and register it with `exporter_factory.register_exporter("pql-assert", ...)`. Registration runs when `pql_odcs.adapters.datacontract_cli` is imported, and the module also exposes `register()` for explicit use. It ships as the optional extra `pql-odcs[datacontract]`, which requires Python 3.10 or later.

| `export()` argument | What the adapter does with it |
|---|---|
| `data_contract` (an `OpenDataContractStandard` object) | Dumps it to a dict with `model_dump(by_alias=True, exclude_none=True)`, so `schema_` becomes `schema`, and passes that to the pql-odcs loader. The core never imports the pydantic model. |
| `schema_name` ("all" or one schema) | Limits generation to that schema object. |
| `server` (name or None) | Selects the server entry whose `customProperties` give the semantic model's table names and, for query and deploy targets, the workspace and model. |
| `sql_server_type` | Ignored. |
| `export_args` | Passes these options: `env`, `suite` (Schema, DataQuality, or all), `catalog_version`, `include_coverage`. |

**One string out**: `export()` returns a single string, but pql-odcs produces several suites. With `suite=all` (the default), the adapter returns one `.dax` bundle that defines every suite function, followed by one `EVALUATE` per suite. With `include_coverage=true`, it appends the coverage report as a DAX comment block. Writing separate files stays a job for the pql-odcs CLI.

**Version handling**: the ODCS object passed in may carry a different `apiVersion` than the YAML on disk; the docs' importer example builds a v3.0.2 object. The loader's version gate must accept anything the installed `open-data-contract-standard` package produces, and a test pins the supported package range.

**Decision for review**: should Power BI targeting live on an ODCS `servers` entry? That would be a custom-type server whose `customProperties` hold the workspace, the semantic model, and the table name map. It fits datacontract-cli's `server` argument and keeps Power BI details out of `schema`. If adopted, it is also a candidate Bitol RFC for a standard Power BI / Fabric semantic model server type.

**Later, optional**: the same factory pattern supports a custom importer. A pbip importer could read a semantic model's TMDL tables, columns, and relationships and produce a starter ODCS contract, closing the loop from model to contract to tests.

## Changes to pql-test

pql-test gains a plugin hook and one BUSL command. Nothing else in the runner changes.

1. **Plugin loading** in the main click group, so any package can add commands without pql-test naming it:

   ```python
   # SPDX-License-Identifier: BUSL-1.1
   from importlib.metadata import entry_points

   for ep in entry_points(group="pql_test.commands"):  # 3.10+ API; needs a 3.9 fallback
       try:
           cli.add_command(ep.load())
       except Exception as exc:  # a broken plugin must not break pql-test
           click.echo(f"warning: plugin {ep.name} failed to load: {exc}", err=True)
   ```

2. **Optional extra** in `python/pyproject.toml`: `contracts = ["pql-odcs>=0.1,<0.2"]`. Users opt in with `pip install pql-test[contracts]`.
3. **`contract run`** (`contract_run.py`, BUSL): attaches to the `contract` group at load time when pql-odcs is installed. It calls `pql_odcs.generate()`. It then runs the generated suites from their own file text with `run_tests()`, not `run_tests_from_model` (see the decisions table). Finally it calls `pql_odcs.trace()` and prints failures by rule ID. It supports the existing `--log-format` and `--output` flags.
4. **pql-test skill**: add a `contract` skill file so the AI harness install covers the new commands.
5. **code-coverage**: no change in v0.1. Later, the contract coverage report can be shown beside it as a second view: which contract rules are enforced, versus which model objects are tested.
6. **Docs**: a README section, "Testing against ODCS data contracts", linking to the pql-odcs README for the mapping table.

**Version coupling**: pql-odcs pins nothing on pql-test. Instead, its catalog declares the minimum PQL.Assert version it targets. `contract run` warns when the model's installed PQL.Assert functions are older; the check will use `INFO.FUNCTIONS()` or RetrieveTestsV2 metadata, which is still to be confirmed.

## Models not in PBIP format: XMLA delivery

A model may be a `.pbix` open in Desktop, or exist only in a Fabric or Premium workspace. Then there is no `DAXQueries/` folder to write into, so the generated tests must travel over XMLA. Two modes cover this. Query-scoped is the default because it needs only read access.

| | Query-scoped (default) | Persistent deploy |
|---|---|---|
| How | Prepend the needed PQL.Assert functions and the generated test function into one `DEFINE FUNCTION … EVALUATE` query, sent over XMLA | Create or replace the PQL.Assert library and test functions as model UDFs over XMLA, then run them |
| XMLA permission | Read | Read/write |
| Workspace role (service) | Viewer | Contributor or higher |
| Changes the model | No | Yes |
| Test discovery | From the contract at run time | `RetrieveTestsV2()` finds them in the model |
| pql-test code-coverage | Blind: query-scoped functions are not in `INFO.CALCDEPENDENCY()` | Works as today |
| Works on | Desktop (.pbix or PBIP) and service | Service first; Desktop needs a spike |
| Ships in | v0.2 | v0.3 |

**Target selection**:
- `--target files` (PBIP) writes into `DAXQueries/`.
- `--target query` sends a query-scoped run.
- `--target deploy` makes a persistent deploy.

The default is `files` when MODEL_PATH is a PBIP folder, otherwise `query`.

**Where the code lives**: XMLA transport belongs in pql-test (BUSL), which already owns ADOMD.NET, auth, and connection resolution. pql-odcs (MIT) only produces text: DAX query bundles for query mode, and TMDL or TMSL scripts for deploy mode. This keeps the license boundary intact and keeps pql-odcs free of the Windows-only ADOMD.NET dependency.

### Persistent deploy rules

- Check the model's installed `PQL.Assert.Version()` first. Install or upgrade the library only when it is missing or older, and only with `--install-library`.
- Generated test functions are tagged with an annotation (for example `PQLAssert_GeneratedBy = pql-odcs`), so `--clean` removes only what pql-odcs created.
- `--dry-run` prints the TMDL or TMSL script instead of executing it.
- Refuse to deploy to a workspace whose name or ID matches a configured production list, unless `--allow-production` is passed.

### Prerequisites and side effects to document

- An admin must enable XMLA read/write on the capacity before deploy mode can work.
- After an XMLA write, a service model may no longer be downloadable as a `.pbix`. Recommend deploying tests to a test or development copy of the model.
- Microsoft's support for XMLA writes against the Desktop local instance is limited, and changes may be lost if the file is not saved. Treat Desktop deploy as experimental until the spike passes.
- The spike must confirm, before v0.3 work starts, whether TOM and TMSL expose UDFs as a scriptable object, and whether TMDL scripts over XMLA can create them.

## Build, release and CI guardrails

The two packages release independently, from separate tags and workflows, and CI enforces the license boundary on every pull request.

**Release**

- pql-test keeps `release.yml` and its `v*` tag trigger unchanged (see the decisions table).
- pql-odcs releases on `pql-odcs-vX.Y.Z` tags through its own `release-pql-odcs.yml`, building from `packages/pql-odcs/` only. It uses PyPI Trusted Publishing, as pql-test does today.
- Each package has its own version in its own `pyproject.toml` and its own `CHANGELOG.md`.

**CI guardrails (all blocking)**

- [ ] **Import boundary**: an import-linter contract forbids `pql_odcs` from importing `pql_test`.
- [ ] **SPDX headers**: a check that every file under `packages/pql-odcs/` is MIT-tagged and every file under `python/` is BUSL-tagged (REUSE tool or a short script).
- [ ] **Wheel contents**: build the pql-odcs wheel and fail if it contains anything outside `pql_odcs/`, LICENSE, NOTICE, or README.md.
- [ ] **Dependency licenses**: run pip-licenses on pql-odcs's resolved dependencies and fail on anything not MIT, BSD, or Apache-2.0.
- [ ] **Standalone install**: install pql-odcs in a clean venv without pql-test and run its CLI smoke tests.
- [ ] **Plugin install**: install `pql-test[contracts]` and check that `pql-test contract --help` lists the commands. Until pql-odcs is on PyPI, this must install `packages/pql-odcs` from the local path first.
- [ ] **Golden files**: fixture contracts must regenerate byte-identical DAX.
- [ ] **Platform matrix**: pql-odcs runs on Linux, macOS, and Windows, since it needs no ADOMD.NET. `contract run` tests stay Windows-only like the rest of pql-test.

## Testing strategy

Most testing needs no Power BI at all. Only one layer touches a live model.

| Layer | What it proves | Needs Power BI | Runs in |
|---|---|---|---|
| Unit: loader | Valid and invalid contracts, ODCS 3.0.x vs 3.1.x differences | no | every PR, all OSes |
| Unit: mappers | Each rule → expected IR and coverage status, including skipped reasons | no | every PR, all OSes |
| Golden: emitter | Fixture contracts → byte-identical `.dax` files | no | every PR, all OSes |
| Property-based | Random valid contracts never crash the pipeline; every rule gets a status | no | every PR |
| Trace | Sample pql-test JSON → correct rule IDs | no | every PR |
| Integration | Generated suites run against `examples/SampleModel` via `pql-test contract run`; planted bad data fails the right rules | yes | Windows runner, nightly + release |

**Fixtures to build**:
- a contract for SampleModel's MarvelFact and DateDim tables (good data);
- a copy with rules that must fail;
- one contract that exercises every row of the mapping catalog, including the skipped ones.

## Milestones

*Not filled in by the source plan; dates are for the maintainer to set.* Proposed gates:

- **v0.1**: the [v0.1 epic](../tasks/archive/2026-10-25-pql-odcs-v0.1.md) is complete. All blocking CI guardrails pass. `pql-test contract run` passes the integration layer against SampleModel.
- **v0.2**: query-scoped XMLA target. The v0.2 mapping rows and fallbacks R2–R5. The datacontract-cli adapter.
- **v0.3**: persistent deploy target (after the TOM/TMSL UDF spike). Fallback R6 and pattern rules.
- **v1.0**: optional upstream `datacontract export pql-assert` PR. A pbip importer.

## Risks and open questions for review

**Decisions needed**

- [x] Package name → `pql-odcs` (2026-10-25)
- [x] Copyright holder for the MIT code → Client First Technologies (2026-10-25)
- [x] Name mapping → customProperties only (2026-10-26)
- [x] Warning severity → separate WARN suites (default kept, 2026-10-25)
- [x] Generated `.dax` files → both workflows supported and documented (2026-10-26)

**To confirm with counsel**

- [ ] The root `LICENSE.txt` scope note and `LICENSES.md` approach for a mixed-license repo.
- [ ] Attribution for bundling PQL.Assert's MIT-licensed `functions.tmdl` inside pql-odcs (NOTICE file wording).

**Technical risks**

| Risk | Effect | Mitigation |
|---|---|---|
| PQL.Assert renames or changes argument order | Generated tests break | Versioned catalog; golden tests; version warning in `contract run` |
| ODCS 3.2 changes quality rule shape | Mappers miss rules | Loader version gate; unknown rules reported as skipped, never dropped |
| Semantic model differs from source (filters, RLS, incremental refresh) | False passes or failures | Document clearly; `generate` notes in each file header that results are model-scoped |
| DAX BLANK treats null and empty string alike | `nullValues` counts differ from the warehouse | Document; offer strict mode using `ISBLANK` vs `= ""` where the column type allows |
| `Col.ShouldNotBeNull` only checks that some values are non-null (gap plan C1, **confirmed** 2026-10-25) | Required columns would pass with nulls present | Map to `Col.NullRateShouldBeAtMost(…, 0)`, which is correct at a 0 threshold; adopt `Col.NullCountShouldBeAtMost` in 0.8.0 |
| `Col.ShouldBeDistinct` is skewed by blanks (gap plan C4, confirmed) | One blank plus one duplicate passes | Report `primaryKey`/`unique`/`duplicateValues` as approximated; adopt `Col.ShouldBePrimaryKey` / `Col.NonNullValuesShouldBeDistinct` in 0.8.0 |
| Plugin loading masks errors | Silent missing commands | *(proposed — source plan was truncated here)* One-line stderr warning naming the plugin and the exception; `PQL_TEST_STRICT_PLUGINS=1` re-raises so CI fails loudly; the plugin-install CI check asserts `pql-test contract --help` lists every command |
| Generated suites not yet deployed to a live model | `contract run` silently skips them | Run generated suites from their file text through `run_tests()`, not live discovery (see decisions) |
| Golden files differ by line ending on Windows | Byte-identical check fails on one OS | Emitter writes `\n` explicitly; `.gitattributes` marks golden `.dax` files `eol=lf` |
