# Direct Test-UDF Code Coverage Epic

**Status**: 📋 PLANNED
**Goal**: Add a `pql-test code-coverage` command that reports coverage from direct `.Test` and `.Tests` UDF evidence, identifies test gaps, and can enforce a minimum coverage threshold in CI

## Overview

WHY Power BI and Fabric developers need an actionable view of which calculated columns, measures, tables, relationships, partitions, and roles have direct test-UDF coverage, so they can prioritize missing tests and let AI agents generate targeted test work without counting incidental PQL.Assert internals as model coverage.

---

## Validate Direct Test-UDF Metadata Contract

Run live XMLA queries against an example model to record the object-type values and direct edges returned by `INFO.CALCDEPENDENCY()` for discovered `.Test` and `.Tests` UDFs.

**Requirements**:
- Given test UDFs returned by `PQL.Assert.RetrieveTestsV2()`, should capture their direct calculation-dependency edges without including dependencies that originate only from PQL.Assert helper functions
- Given the requested categories of calculated columns, measures, tables, relationships, partitions, and roles, should document the verified XMLA metadata source and identifier shape for every category before the collector contract is implemented
- Given a requested category that cannot be identified from direct UDF metadata, should define explicit evidence or exclusion behavior rather than infer coverage from transitive dependencies

---

## Define Direct Coverage Evidence

Define the normalized inventory, direct-test evidence, exclusions, and AI-ready gap records for calculation and metadata object categories.

**Requirements**:
- Given a calculated column, measure, or table in the eligible inventory, should mark it covered only when a discovered test UDF has a direct `INFO.CALCDEPENDENCY()` edge to it
- Given a relationship, partition, or role, should mark it covered only from explicit evidence attributable to a discovered test UDF
- Given an object excluded by the selected coverage policy, should retain its identifier and exclusion reason without adding it to either the covered or uncovered totals
- Given an uncovered eligible object, should produce its type, stable model identifier, and a test-target hint usable by an AI agent

---

## Implement Coverage Collection

Add isolated runner functionality that retrieves the test-UDF set, inventories eligible model objects, and produces normalized direct-coverage evidence.

**Requirements**:
- Given any supported `MODEL_PATH` with a resolved XMLA connection, should reuse existing connection resolution and test discovery to collect coverage without reading secrets from files
- Given a model with no discovered test UDFs, should return a valid zero-coverage report and list every eligible object as uncovered
- Given duplicate evidence from multiple test UDFs, should count the model object once while preserving all contributing test names
- Given an XMLA metadata query failure, should report the unavailable category and its cause without presenting it as zero coverage

---

## Add Code Coverage Command

Expose terse human output, verbose evidence and gaps, JSON output, and a CI threshold through the Click CLI.

**Requirements**:
- Given `pql-test code-coverage MODEL_PATH`, should print the overall percentage and covered/eligible counts by object type
- Given `--verbose`, should list covered objects with direct test-UDF evidence and uncovered objects with AI-ready test targets
- Given `--format json` and `--output`, should emit a stable report containing summary, category counts, evidence, gaps, exclusions, and unavailable categories
- Given `--min-coverage <percent>`, should exit non-zero when the overall eligible coverage is below the configured threshold
- Given malformed output or threshold options, should fail with Click validation before making an XMLA query

---

## Cover And Document The Workflow

Add unit and live-model validation for the coverage contract, then document the command and the limits of dependency-based evidence.

**Requirements**:
- Given mocked XMLA metadata rows, should test coverage classification, deduplication, unavailable categories, gap generation, output serialization, and threshold exit behavior without a live service
- Given the SampleModel live XMLA validation environment, should verify that direct test-UDF evidence matches the recorded metadata contract
- Given users and AI agents reading the command documentation, should distinguish direct dependency coverage from proof that an assertion fully validates an object's behavior