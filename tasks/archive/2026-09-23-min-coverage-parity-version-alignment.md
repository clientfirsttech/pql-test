# `--min-coverage` Parity, Threshold-Aware Colors, Version Alignment Epic

**Status**: ✅ COMPLETED (2026-09-23)
**Goal**: Make `code-coverage`'s `--min-coverage` gate match the semantics developers already expect from `pytest-cov`/Istanbul/Jest, replace its hard-coded 100%/0%/partial coloring with threshold-aware grading, and stop `plugin.json` from silently drifting out of sync with `pyproject.toml` and the SKILL.md manifests.

## Overview

`plugin.json`'s version had been hand-edited once, to `0.1.0`, and never touched again while `pyproject.toml` and every `SKILL.md` moved on to `0.1.18` — nothing enforced that the four locations carrying a version (`pyproject.toml`, `plugin.json`, `skills/*/SKILL.md`, `python/pql_test/skills/*/SKILL.md`) actually agreed. Separately, `--min-coverage`'s pass/fail exit code was already correct, but the percentage it graded against rounded a near-miss (e.g. 99,999/100,000) up to a misleading 100%, and the report's coloring used hard-coded 100%/0%/else buckets instead of grading against the threshold the user actually asked for.

---

## `coverage_percent()` Rounding Parity with `coverage.py`

**Requirements**:
- Given `coverage.py`'s `fail_under` guard never lets 99.99% register as 100%, should add `coverage_percent()` in [coverage_report.py](../python/pql_test/runner/coverage_report.py) that only rounds to 100.0 when `covered == eligible`, reporting 99.99 otherwise even when the 2-decimal rounding would naturally land on 100.0
- Given `summarize_coverage()` previously computed its own inline percentage, should route it through `coverage_percent()` so there is one rounding rule, not two

## Threshold-Aware Status Coloring

**Requirements**:
- Given the report previously colored 100% green, 0% red, and everything else yellow regardless of `--min-coverage`, should add `coverage_status()` grading `"PASS" | "SKIP" | "FAIL"` against `DEFAULT_WATERMARKS = (50.0, 80.0)` (Istanbul/nyc/Jest convention) when no threshold is set
- Given `--min-coverage N` is set, should grade binary — PASS at/above `N`, FAIL below — so the color always agrees with the exit code, with no yellow "partial" band
- Given the overall summary line previously printed uncolored, should color it the same way as each category row

## `Required coverage of N% reached` CI Line

**Requirements**:
- Given `pytest-cov` prints a confirmation line when a coverage gate passes, so CI logs show the gate was evaluated (not just silently absent on success), should print `Required coverage of N% reached. Total coverage: X%` when `--min-coverage` passes
- Given `--format json --output FILE` keeps stdout parseable, should send this line to stderr whenever JSON is going to stdout directly (`output_format == "json" and not output`), and to stdout otherwise

## Version Alignment Guard

**Requirements**:
- Given `plugin.json` had silently drifted to `0.1.0` while every other manifest moved to `0.1.18`, should bump it back in line and document every file that carries the version in a new `aidd-custom/skills/pql-test-version-bump/SKILL.md`
- Given nothing previously caught this class of drift, should add `python/tests/test_version_alignment.py` asserting `plugin.json` and every `skills/*/SKILL.md` / `python/pql_test/skills/*/SKILL.md` matches `pyproject.toml`'s `[project].version`
- Given local pytest runs don't gate a merge, should add a "Versions aligned with pyproject.toml" step to `.github/workflows/validate-plugin.yml` so CI fails on the same drift

## Docs and Evals

**Requirements**:
- Given the color rules, exit codes, and threshold semantics were undocumented, should document them in `skills/code-coverage/SKILL.md` (and its packaged copy) and in `README.md`, including a GitHub Actions coverage-gate example
- Given `code-coverage` had no promptfoo eval, should add one under `tests/promptfoo/tests/code-coverage.yaml`

---

## Epic Vision (Definition of Done)

### Quality Gates (All Must Pass)

✅ **Code Review**:
- `coverage_percent()` and `coverage_status()` are pure functions in `coverage_report.py`, independent of Click/CLI wiring
- No path colors or exits on a hard-coded 100/0 bucket anymore — every color and exit decision routes through `coverage_status()`

✅ **Test Coverage**:
- `coverage_percent()` covered for the zero-eligible, full-coverage, near-100-rounds-down, and general-rounding cases
- `coverage_status()` covered for both the default-watermark and threshold-binary grading paths, including the `--min-coverage 0` edge case
- `test_version_alignment.py` parametrized over every `SKILL.md` found under `skills/` and `python/pql_test/skills/`
- 573 passed / 2 skipped under `pytest -m "not live"`

✅ **Documentation**:
- `skills/code-coverage/SKILL.md` and its packaged copy document the color rules and threshold semantics identically
- `README.md` includes a coverage-gate CI example
- `plan.md` records the change under Completed Work

### Follow-ups (not blocking, tracked separately)

- The version-extraction regex/awk in `test_version_alignment.py` and `validate-plugin.yml` originally scanned the whole `pyproject.toml` for the first `^version = "..."` line rather than scoping to the `[project]` table — hardened in a later pass to bound the match to the `[project]` table specifically.
- `pql-test-version-bump/SKILL.md` originally didn't document PEP 440 pre-release suffixes (e.g. `0.1.18b1`) or how to promote a beta back to a stable release — added in a later pass.
