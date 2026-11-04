---
name: pql-test-contract-gap-check
description: The gap-detection step for pql-test contract changes. Checks for a new Bitol ODCS release and a new PQL.Assert (DAX Lib) release, runs the ODCS rule matrix and the PQL.Assert function matrix, and checks docs/contracts.md against the mapping code. Use in the documentation step of an AIDD review (/aidd-review step 9) whenever python/pql_test/odcs/, a contract fixture under python/tests/odcs/fixtures/, or docs/contracts.md changes, and before every release.
allowed-tools: Bash(python:*) WebFetch
---

# pql-test contract gap check

Act as the maintainer of `pql-test contract`'s ODCS-to-PQL.Assert mapping. The mapping's own promise is that every contract rule is reported as mapped, approximated, or skipped — never silently dropped. That promise only holds while two matrix tests stay green and an upstream release hasn't quietly opened a gap neither one has been taught to see yet.

## Process

```sudolang
GapCheck() {
  1. Check for new releases:
     - Bitol ODCS: https://github.com/bitol-io/open-data-contract-standard/releases
       (bundled schemas: python/pql_test/odcs/schemas/odcs-json-schema-v*.json)
     - PQL.Assert (DAX Lib): https://github.com/clientfirsttech/PQL.Assert/releases
       (vendored copy for conformance: python/tests/odcs/fixtures/pql-assert-0.9.0/)
     // If neither moved since the last gap check (see plan.md), skip to step 4.

  2. On a new ODCS release:
     - Copy its JSON schema into python/pql_test/odcs/schemas/, add it to loader.SCHEMAS
     - cd python && pytest tests/odcs/test_odcs_rule_matrix.py
     - Every failure names an unclassified (or stale) value: add it to
       pql_test/odcs/catalog/odcs_rules.yaml as mapped, dax-only, or out-of-scope
       with a reason; demonstrate anything mapped/dax-only in a fixture
       (tests/odcs/fixtures/rule-coverage.odcs.yaml is the usual home)
     - cd python && pytest tests/odcs/test_loader.py tests/odcs/test_golden.py

  3. On a new PQL.Assert release:
     - Replace the vendored copy under python/tests/odcs/fixtures/pql-assert-<version>/
     - cd python && pytest tests/odcs/test_function_matrix.py tests/odcs/test_library_conformance.py
     - Every failure names an unclassified function: add it to
       pql_test/odcs/catalog/pql_assert_functions.yaml (mapped / dax / none; see that
       file's header for what each means) and, if it fixes a known gap, update a catalog
       in pql_test/odcs/catalog/pql_assert_*.yaml per docs/pql-assert-gap-plan.md
     - A genuinely new PQL.Assert minor version (not a patch) may need a new
       pql_assert_0_X.yaml catalog: see docs/contracts.md's "PQL.Assert 0.8" section
       for the shape an adoption like this takes

  4. Either way, close the loop:
     cd python && pytest tests/odcs/test_docs_contracts_agreement.py
     // Fixes a docs/contracts.md mapping table that fell behind the code, or a code
     // reason string that drifted from what docs promised it says.

  5. Report: which release(s) were checked, what (if anything) changed, and the test
     run that proves it's closed.
}
```

## Constraints

```sudolang
Constraints {
  A test failure always means "classify this", never "widen the test" — the matrices
    exist to force a decision on every new value, not to be worked around.
  A new fixture addition that changes golden output needs
    `PQL_TEST_UPDATE_GOLDEN=1 pytest tests/odcs/test_golden.py`, reviewed like any diff.
  Classifying something `dax-only` or `out-of-scope` is a decision about the mapping,
    not busywork: when unsure, say so and ask rather than guess a reason.
  This is read-only discovery until a gap is found; don't touch catalogs or fixtures
    speculatively ahead of an actual new release or a real test failure.
}
```
