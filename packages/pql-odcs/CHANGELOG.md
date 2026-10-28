# Changelog

All notable changes to pql-odcs are recorded here. pql-odcs is versioned
independently of pql-test and released from `pql-odcs-vX.Y.Z` tags.

## 0.1.0 — Unreleased

- Initial release: generates PQL.Assert `*.Tests.dax` suites from ODCS v3.0.x, v3.1.x, and v3.2.x contracts, with a coverage report and result tracing.
- `--pql-assert 0.8` (`generate`, `coverage`, `trace`) targets PQL.Assert 0.8.0. Rules that were approximated or skipped against 0.7.1 map to the new functions: exact null and key checks, null and duplicate ceilings, multi-column keys, `mustNotBeBetween`, simple anchored patterns, and `latency` freshness. The default stays `0.7`; its output is unchanged. The 0.8 catalog calls the released 0.8.0 functions (`Col.NonNullValuesShouldBeDistinct`, and `Col.ShouldStartWith` / `ShouldEndWith` / `ShouldContainString` with `matchCase`, so pattern rules are case-sensitive), and a test checks every catalog op against a vendored copy of the library.
- `doctor [MODEL_PATH]` checks the environment and reads a PBIP model's PQL.Assert library from its TMDL, then recommends a `--pql-assert` value. `generate --pql-assert auto` uses the same reading.
- `skill` prints the pql-odcs skill for AI coding agents, or installs it into a project for Claude, Copilot, Cursor, or Windsurf.
