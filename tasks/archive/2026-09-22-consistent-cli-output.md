# Consistent CLI Output Epic

**Status**: ✅ COMPLETED (2026-09-22)
**Goal**: Give every `pql-test` command a single shared output style — connection diagnostics, banners, tables, and color — instead of each command inventing its own presentation, so users get a predictable CLI instead of two different tools glued together.

## Overview

`run-tests` and `code-coverage` report on the same model through the same XMLA connection, but they look like they came from different projects: `run-tests` prints a "Local XMLA connection: ..." diagnostic line, a pytest-style `===== test session starts =====` banner, and a color-coded box-drawing table (PASS green / FAIL red / SKIP yellow); `code-coverage` prints none of that — no connection line even though it resolves the same connection object, no banner, and its category breakdown is a flat indented text list with no color and no table borders. This was allowed to drift because there is no shared rendering module and no written CLI output contract — each command's presentation logic was implemented ad hoc inside `cli.py` next to that command's business logic (`_print_results` at [cli.py:233](../python/pql_test/cli.py#L233) vs. `_print_coverage_report` at [cli.py:1143](../python/pql_test/cli.py#L1143)). This epic extracts the shared primitives, retrofits both commands onto them, and writes down the contract so the next command (and the next AI agent) can't silently reintroduce a third style.

---

## Extract a Shared CLI Presentation Module

**Requirements**:
- Given `_sep()` (banner/separator rendering), the box-table renderer (`_hline`/`_row`/`_pad`/`_trunc` in `_print_results`), and the status-tag color map (`{"PASS": "green", "FAIL": "red", "SKIP": "yellow"}`) currently live as closures/locals inside `_print_results`, should extract them into a new `python/pql_test/runner/cli_format.py` module as standalone, independently unit-testable functions with no Click dependency beyond `click.style` for color
- Given the new module exists, should have `run-tests`' `_print_results` and `code-coverage`'s `_print_coverage_report` both import and call it — no duplicated separator/table/color logic left in `cli.py`
- Given a future command wants a status table or a session banner, should be able to reuse `cli_format.py` without copy-pasting from `_print_results`

## Surface the XMLA Connection Line on `code-coverage`

**Requirements**:
- Given `run-tests` prints `Local XMLA connection: <server> / catalog: <catalog>` (or `XMLA connection: ...` for service connections) after resolving, and `code-coverage`'s `collect_coverage()` ([coverage_collector.py:124](../python/pql_test/runner/coverage_collector.py#L124)) resolves the identical `ResolvedXmlaConnection` object but never surfaces it, should print the same connection-line format from `cmd_code_coverage` before the coverage report — same wording, same local/service branching as `run-tests`
- Given `collect_coverage()` currently only returns `CoverageReport | None` and discards the resolved connection, should thread the resolved connection (or its server/catalog) back to the caller so `cmd_code_coverage` can print it without re-resolving
- Given `--format json` output, should not gain the connection line in the JSON payload (text-mode diagnostic only) — matches how `run-tests` keeps `--output` JSON free of session-banner text

## Add a Session Banner to `code-coverage`

**Requirements**:
- Given `run-tests` opens with `_sep("test session starts")` + `model: <path>`, should give `code-coverage` an equivalent opening banner (e.g. `_sep("coverage session starts")` + `model: <path>`) using the shared `cli_format.py` separator function, replacing the current bare `Direct Test-UDF Coverage: <path>` first line
- Given `Tests discovered: N` currently follows immediately, should keep that line directly under the banner, matching `run-tests`' `model:` → blank line → content rhythm

## Render the Category Breakdown as a Bordered, Color-Coded Table

**Requirements**:
- Given `run-tests` renders its per-suite Pass/Fail/Skip breakdown as a bordered table with a colored Stat column, and `code-coverage`'s "By category" section ([cli.py:1156-1167](../python/pql_test/cli.py#L1156-L1167)) renders the same shape of data (category name, covered/eligible counts, percent) as plain indented lines, should render it through the same `cli_format.py` table renderer with columns `Category | Covered | Eligible | %`
- Given a category is fully covered (100%, eligible > 0), should color that row's percent green; given a category has 0% coverage (eligible > 0), should color it red; given a category is partially covered, should color it yellow — mirroring the PASS/FAIL/SKIP color semantics from `run-tests` rather than inventing new thresholds
- Given a category is `excluded` (e.g. PARTITION) or has `0/0`, should render as a neutral (uncolored) row rather than being silently dropped from the table, so the table's row count still matches "all categories seen"

## Write Down the CLI Output Contract

**Requirements**:
- Given this drift happened once already with no one noticing until a user compared two command outputs side by side, should add a short "CLI Output Conventions" section to `CONTRIBUTING.md` documenting: (1) all multi-command presentation logic lives in `cli_format.py`, not per-command closures in `cli.py`; (2) every model-targeting command opens with a connection-diagnostic line and a session banner in text mode; (3) the PASS/green, FAIL/red, SKIP-or-partial/yellow color convention is the only status-color vocabulary in the CLI
- Given `ai/` skills/rules are consulted by AI agents before writing CLI code (per `AGENTS.md`'s Progressive Discovery), should add or update the relevant `ai/` rule/skill file so an agent implementing a new `pql-test` command is pointed at `cli_format.py` and the CONTRIBUTING.md section before inventing new output code
- Given `skills/code-coverage/SKILL.md`'s sample output block (lines 77-79 of this epic's evidence, i.e. the README/SKILL usage examples) currently shows the *old* plain-text format, should update those documented sample outputs to match the new banner/table/connection-line format once implemented, so the skill's behavioral contract stays byte-consistent with real CLI output

---

## Epic Vision (Definition of Done)

### Quality Gates (All Must Pass)

✅ **Ruff Check**: All code passes `ruff check python/` with zero violations

✅ **Code Review**:
- No banner/table/color rendering logic remains duplicated between `_print_results` and `_print_coverage_report`
- `code-coverage` text output shows a connection line and session banner before any report content
- Category table uses real borders and the shared PASS/FAIL/SKIP color vocabulary — no new color meanings introduced
- `--format json` output for `code-coverage` is unaffected by any of the above (still the stable, presentation-free shape)

✅ **Test Coverage**:
- `cli_format.py` has direct unit tests for the separator, table renderer, and color-tag helpers, independent of both commands
- `code-coverage` text-mode output is snapshot/string-asserted to include the connection line, banner, and bordered category table
- `run-tests` existing output tests continue to pass unchanged (refactor must be behavior-preserving for `run-tests`)
- Overall test coverage ≥ 80% (`pytest --cov=pql_test --cov-fail-under=80`)

✅ **Documentation**:
- `CONTRIBUTING.md` has the new "CLI Output Conventions" section
- `README.md`'s `code-coverage` example output block matches the new format exactly
- `skills/code-coverage/SKILL.md` and its packaged copy (`python/pql_test/skills/code-coverage/SKILL.md`) sample outputs updated and kept byte-identical to each other, per the existing skill-distribution contract
