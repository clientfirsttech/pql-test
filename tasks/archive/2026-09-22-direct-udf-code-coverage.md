# Direct Test-UDF Code Coverage Epic

**Status**: ✅ COMPLETED (2026-09-22)
**Goal**: Add a `pql-test code-coverage` command that reports coverage from direct `.Test` and `.Tests` UDF evidence, identifies test gaps, and can enforce a minimum coverage threshold in CI

## Overview

WHY Power BI and Fabric developers need an actionable view of which calculated columns, measures, tables, relationships, partitions, and roles have direct test-UDF coverage, so they can prioritize missing tests and let AI agents generate targeted test work without counting incidental PQL.Assert internals as model coverage.

---

## Validate Direct Test-UDF Metadata Contract ✅ (2026-09-22)

Run live XMLA queries against an example model to record the object-type values and direct edges returned by `INFO.CALCDEPENDENCY()` for discovered `.Test` and `.Tests` UDFs.

**Validated** — see [direct-udf-code-coverage-metadata-contract.md](../direct-udf-code-coverage-metadata-contract.md) for the recorded evidence (live against SampleModel, RLS_Model, OLS_Model). Headline finding: tables, columns/calc-columns, and measures have a true direct-edge path; relationships, partitions, and roles do not and need the exclusion/indirect-evidence behavior documented there.

**Requirements**:
- Given test UDFs returned by `PQL.Assert.RetrieveTestsV2()`, should capture their direct calculation-dependency edges without including dependencies that originate only from PQL.Assert helper functions
- Given the requested categories of calculated columns, measures, tables, relationships, partitions, and roles, should document the verified XMLA metadata source and identifier shape for every category before the collector contract is implemented
- Given a requested category that cannot be identified from direct UDF metadata, should define explicit evidence or exclusion behavior rather than infer coverage from transitive dependencies

---

## Define Direct Coverage Evidence ✅ (2026-09-22)

Define the normalized inventory, direct-test evidence, exclusions, and AI-ready gap records for calculation and metadata object categories.

**Implemented** — [python/pql_test/runner/coverage.py](../../python/pql_test/runner/coverage.py) defines `CoverageObjectType`, `EligibleObject`, `CoverageEvidence`, `ExclusionRecord`, `CoverageGap`, and the pure `classify_coverage()` rule (exclusion beats evidence; evidence with no contributing test names doesn't count; gaps carry an AI-ready hint). No XMLA calls here — inputs are built by "Implement Coverage Collection" next. Covered by [python/tests/test_coverage.py](../../python/tests/test_coverage.py) (8 tests, 100% line coverage on the new module) using synthetic data, not a live connection.

**Requirements**:
- Given a calculated column, measure, or table in the eligible inventory, should mark it covered only when a discovered test UDF has a direct `INFO.CALCDEPENDENCY()` edge to it
- Given a relationship, partition, or role, should mark it covered only from explicit evidence attributable to a discovered test UDF
- Given an object excluded by the selected coverage policy, should retain its identifier and exclusion reason without adding it to either the covered or uncovered totals
- Given an uncovered eligible object, should produce its type, stable model identifier, and a test-target hint usable by an AI agent

---

## Implement Coverage Collection ✅ (2026-09-22)

Add isolated runner functionality that retrieves the test-UDF set, inventories eligible model objects, and produces normalized direct-coverage evidence.

**Implemented** — [python/pql_test/runner/coverage_collector.py](../../python/pql_test/runner/coverage_collector.py) adds `collect_coverage(model_path, ...)`, reusing `resolve_xmla_connection`/`retrieve_tests` exactly like `run_tests_from_model`. Direct `INFO.CALCDEPENDENCY()` edges cover tables/calc-columns/measures; `PQLAssert_RoleName` (already on each discovered `PqlTest`) joined against the role inventory covers roles; `PQL.Assert.Relationship.ShouldExist(...)` calls are regex-parsed out of each test UDF's own DAX expression text (`INFO.USERDEFINEDFUNCTIONS()[Expression]`) and matched against `INFO.VIEW.RELATIONSHIPS()` for relationships; partitions are always excluded (no PQL.Assert helper targets them). Each category's XMLA query is wrapped independently so a failure reports that category `unavailable` with its cause rather than presenting it as zero coverage — including the case where an inventory query succeeds but the evidence query for the same category fails (verified with a regression test). Verified live against SampleModel, RLS_Model, and OLS_Model — output matches the metadata contract exactly. Covered by [python/tests/test_coverage_collector.py](../../python/tests/test_coverage_collector.py) (11 tests, mocked XMLA, 96% line coverage).

**Requirements**:
- Given any supported `MODEL_PATH` with a resolved XMLA connection, should reuse existing connection resolution and test discovery to collect coverage without reading secrets from files
- Given a model with no discovered test UDFs, should return a valid zero-coverage report and list every eligible object as uncovered
- Given duplicate evidence from multiple test UDFs, should count the model object once while preserving all contributing test names
- Given an XMLA metadata query failure, should report the unavailable category and its cause without presenting it as zero coverage

---

## Add Code Coverage Command ✅ (2026-09-22)

Expose terse human output, verbose evidence and gaps, JSON output, and a CI threshold through the Click CLI.

**Implemented** — `pql-test code-coverage MODEL_PATH` in [python/pql_test/cli.py](../../python/pql_test/cli.py), backed by [python/pql_test/runner/coverage_report.py](../../python/pql_test/runner/coverage_report.py) (pure summary/JSON-shape helpers, unit-tested independent of Click). `--output` without `--format json` and a malformed/out-of-range `--min-coverage` both fail via Click validation before any XMLA query (verified live and with a mocked spy in tests). Added the `code-coverage` skill (`skills/code-coverage/SKILL.md`, synced byte-for-byte to `python/pql_test/skills/`) and bumped the package version to `0.1.18b1` across `pyproject.toml`, `plugin.json`, and all 5 skill files, per the project's skill-versioning convention in CONTRIBUTING.md. Covered by [python/tests/test_coverage_report.py](../../python/tests/test_coverage_report.py) (6 tests) and [python/tests/test_code_coverage_cli.py](../../python/tests/test_code_coverage_cli.py) (9 tests), plus 7 new skill-content/packaging tests.

**Requirements**:
- Given `pql-test code-coverage MODEL_PATH`, should print the overall percentage and covered/eligible counts by object type
- Given `--verbose`, should list covered objects with direct test-UDF evidence and uncovered objects with AI-ready test targets
- Given `--format json` and `--output`, should emit a stable report containing summary, category counts, evidence, gaps, exclusions, and unavailable categories
- Given `--min-coverage <percent>`, should exit non-zero when the overall eligible coverage is below the configured threshold
- Given malformed output or threshold options, should fail with Click validation before making an XMLA query

---

## Cover And Document The Workflow ✅ (2026-09-22)

Add unit and live-model validation for the coverage contract, then document the command and the limits of dependency-based evidence.

**Implemented** — Unit coverage across classification, dedup, unavailable categories, gap generation, JSON serialization, and CLI threshold/exit behavior was already built test-first in the prior three tasks (44 tests across `test_coverage.py`, `test_coverage_collector.py`, `test_coverage_report.py`, `test_code_coverage_cli.py`). Added [python/tests/test_coverage_live.py](../../python/tests/test_coverage_live.py) (`@pytest.mark.live`, gated on the same `python/tests/.env` service credentials as `test_live_service.py`) pinning the exact evidence recorded in the metadata contract against the deployed SampleModel — table/measure/relationship coverage, partitions always excluded, and no unavailable categories against a healthy connection. Documented the command in [README.md](../../README.md) (`### code-coverage` section, Table of Contents, Exit Codes table, Architecture module table), with an explicit "dependency coverage vs. assertion coverage" explanation so users and AI agents don't mistake a high score for a correctness guarantee.

**Requirements**:
- Given mocked XMLA metadata rows, should test coverage classification, deduplication, unavailable categories, gap generation, output serialization, and threshold exit behavior without a live service
- Given the SampleModel live XMLA validation environment, should verify that direct test-UDF evidence matches the recorded metadata contract
- Given users and AI agents reading the command documentation, should distinguish direct dependency coverage from proof that an assertion fully validates an object's behavior