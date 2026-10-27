# Changelog

All notable changes to pql-odcs are recorded here. pql-odcs is versioned
independently of pql-test and released from `pql-odcs-vX.Y.Z` tags.

## 0.1.0 — Unreleased

- Initial release: generates PQL.Assert `*.Tests.dax` suites from ODCS v3.0.x, v3.1.x, and v3.2.x contracts, with a coverage report and result tracing.
- `--pql-assert 0.8` (`generate`, `coverage`, `trace`) targets PQL.Assert 0.8.0. Rules that were approximated or skipped against 0.7.1 map to the new functions: exact null and key checks, null and duplicate ceilings, multi-column keys, `mustNotBeBetween`, simple anchored patterns, and `latency` freshness. The default stays `0.7`; its output is unchanged.
