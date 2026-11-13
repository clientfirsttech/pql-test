---
name: code-coverage
description: Report direct test-UDF coverage for a PBIP semantic model — which calculated columns, measures, tables, relationships, partitions, and roles have a discovered DAX test UDF directly evidencing them, plus AI-ready gap hints for the rest.
version: 0.2.1
---

Run `pql-test code-coverage MODEL_PATH` to report which model objects have direct test-UDF evidence and which don't, so an AI agent or developer can prioritize missing tests.

## Behavioral Contract

```sudolang
Interface CodeCoverage {
  exit_code: 0 | 1 | 2
    // 0 = report produced, coverage at/above --min-coverage (or no threshold set)
    // 1 = no XMLA connection, or coverage below --min-coverage (report is still written first)
    // 2 = Click usage error (malformed --min-coverage / --output without --format json) — fails BEFORE any XMLA query

  output_format: "text" | "json"
    // text (default): overall percentage + covered/eligible counts by object type
    // json: stable report (summary, categories, evidence, gaps, exclusions, unavailable) — requires --format json for --output

  colors: "PASS" (green) | "SKIP" (yellow) | "FAIL" (red)
    // overall line + each category percentage
    // no --min-coverage: default watermarks (Istanbul/Jest) — >= 80 green, 50..<80 yellow, < 50 red
    // --min-coverage N: binary — >= N green, < N red (matches the exit code)
}

Constraints {
  // What counts as "covered"
  TABLE | CALC_COLUMN | MEASURE => covered only via a direct INFO.CALCDEPENDENCY() edge
    from a discovered test UDF (OBJECT_TYPE=FUNCTION, OBJECT=test name)
  RELATIONSHIP => covered only when a discovered test UDF's own DAX expression
    contains a PQL.Assert.Relationship.ShouldExist(...) call matching a real relationship
  ROLE => covered only when a discovered test UDF carries a PQLAssert_RoleName
    annotation matching a real role
  PARTITION => always excluded (no PQL.Assert helper targets partitions) —
    never counted covered or uncovered

  // Never inferred
  Coverage is NEVER inferred from transitive dependencies (e.g. a test that only
  reaches a helper FUNCTION, which itself reaches a table, does not count as
  covering that table)

  // Threshold (same semantics as pytest-cov --cov-fail-under / coverage.py fail_under)
  --min-coverage compares the 2-decimal rounded overall percent; it only rounds to
    100 when every eligible object is covered, so --min-coverage 100 cannot pass with a gap
  When met, prints "Required coverage of N% reached. Total coverage: X%"
    (to stderr when JSON is on stdout, so stdout stays parseable)

  // Failure handling
  A category whose XMLA metadata query fails is reported as "unavailable" with
  its cause, never silently presented as 0% coverage
}
```

See [tasks/direct-udf-code-coverage-metadata-contract.md](../../tasks/direct-udf-code-coverage-metadata-contract.md) for the full verified evidence contract, including why relationships/roles need indirect evidence and why partitions have none at all.

## MODEL_PATH Formats

MODEL_PATH accepts three formats:
- **Filesystem path** — the PBIP root directory containing the `.pbip` file and `.SemanticModel` sub-folder (or the `.SemanticModel` directory itself).
- **`local/<model_name>`** — connect to a locally-open Power BI Desktop instance by model name.
- **`<workspace>.Workspace/<semantic_model>.SemanticModel`** — canonical Fabric service path (requires `--tenant-id`, `--client-id`, `--client-secret`, or a stored interactive login via `pql-test auth login`).

Options:
- `-v, --verbose` — List covered objects with their direct test-UDF evidence and uncovered objects with AI-ready test targets. Without it, only the overall percentage and per-category counts are printed.
- `--format text|json` — Output format. `text` (default) is human-readable; `json` emits the stable report shape.
- `-o, --output FILE` — Write the JSON report to FILE. With `--format text`, the text report is printed as well.
- `-q, --quiet` — Print only the summary line (messages on stderr still appear; the exit code is unchanged). Cannot be combined with `--verbose`.
- `--min-coverage PERCENT` — Exit `1` when overall eligible coverage is below PERCENT (0-100), after the report is written; prints `Required coverage of N% reached` when met. Also colors the report pass/fail against PERCENT instead of the default 50/80 watermarks. A malformed or out-of-range value fails with a Click usage error (exit 2) before any XMLA query.
- `--tenant-id ID` — Azure AD tenant ID (or set `PQL_TENANT_ID` env var).
- `--workspace-id ID` — Power BI workspace GUID (or set `PQL_WORKSPACE_ID` env var).
- `--dataset-id ID` — Dataset / semantic model GUID (or set `PQL_DATASET_ID` env var).
- `--client-id ID` — Service principal client ID (or set `PQL_CLIENT_ID` env var).
- `--client-secret SECRET` — Service principal client secret (or set `PQL_CLIENT_SECRET` env var).

Exit codes: `0` = report produced (and coverage at/above `--min-coverage` if set), `1` = no XMLA connection detected, or coverage below `--min-coverage`, `2` = Click usage error (malformed `--min-coverage`, or `--output` without `--format json`) before any XMLA query.

## JSON Report Shape

```json
{
  "model_path": "local/SampleModel",
  "test_count": 4,
  "summary": { "covered": 10, "eligible": 23, "percent": 43.48 },
  "categories": { "TABLE": { "covered": 4, "eligible": 8 }, "...": "..." },
  "evidence": [{ "object_type": "TABLE", "identifier": "MarvelFact", "test_names": ["DataQuality.DEV.Tests"] }],
  "gaps": [{ "object_type": "MEASURE", "identifier": "MarvelFact[Rank of Appearances]", "test_target_hint": "Add a PQL.Assert test asserting on MEASURE MarvelFact[Rank of Appearances]" }],
  "exclusions": [{ "object_type": "PARTITION", "identifier": "MarvelFact[MarvelFact-guid]", "reason": "no PQL.Assert helper targets partitions ..." }],
  "unavailable": [{ "object_type": "RELATIONSHIP", "reason": "INFO.USERDEFINEDFUNCTIONS() query failed: ..." }]
}
```

Usage:
```
# Terse human-readable report
pql-test code-coverage local/SampleModel

# Verbose: list every covered object's evidence and every gap's AI test-target hint
pql-test code-coverage ../examples/SampleModel.SemanticModel --verbose

# Stable JSON report saved to a file (for CI artifacts or an AI agent to read)
pql-test code-coverage local/SampleModel --format json --output coverage.json

# Fail CI when overall eligible coverage drops below 60%
pql-test code-coverage local/SampleModel --min-coverage 60

# Against a remote Fabric workspace
pql-test code-coverage "MyWorkspace.Workspace/MySemanticModel.SemanticModel" \
  --tenant-id $PQL_TENANT_ID --client-id $PQL_CLIENT_ID --client-secret $PQL_CLIENT_SECRET
```
