# Fail CLI When No Tests Executed Epic

**Status**: 🚧 IN PROGRESS (2026-05-23)
**Goal**: `pql-test run-tests` exits non-zero when tests were discovered but none actually ran (all skipped due to a missing/broken connection), so CI catches misconfigured matrix entries instead of reporting them as passing

## Overview

When a CI matrix entry points at a `.SemanticModel` directory whose name does not match any deployed dataset in the workspace (e.g. `TestShouldFailToFindInService.SemanticModel`), `_verify_dataset_exists_in_workspace` correctly raises a `ValueError`. The service→local fallback in `resolve_xmla_connection` catches that, tries local Power BI Desktop detection, and — because CI runners have no PBI Desktop — returns `None`. The CLI then marks every discovered test suite as SKIPPED and exits 0, which makes the matrix job report green even though no tests actually executed against the model.

The fallback is still the right behavior for local dev (stale `.env` + an open PBI Desktop should keep working). The fix is to make the exit code surface "we discovered tests but couldn't execute any of them" as a failure.

---

## Exit Non-Zero When All Discovered Tests Are Skipped

**Requirements**:
- Given a run where tests were discovered but every result was skipped (no XMLA connection), should exit with a non-zero status so CI marks the job as failed
- Given a run with at least one passing or failing test result, should preserve today's exit-code logic (1 if any failed, 0 otherwise)
- Given a run where zero tests were discovered (model legitimately has no tests), should exit 0 — that's not a misconfiguration, just an empty model
- Given a partial run (some passed, some skipped because individual tests had no impersonation context), should still respect the pass/fail signal and not over-trigger the new exit code

---

## Epic Vision (Definition of Done)

### Quality Gates (All Must Pass)

✅ **Ruff Check**: All code passes `ruff check python/` with zero violations

✅ **Code Review**: 
- Exit code logic is clear and well-documented
- Edge cases (no tests, partial skip, full skip) are handled correctly
- Error messages guide users to the root cause

✅ **Test Coverage**: 
- Overall test coverage ≥ 80% (`pytest --cov=pql_test --cov-fail-under=80`)
- Exit code scenarios have dedicated tests
- All existing tests continue to pass

✅ **Documentation**: 
- README.md "Exit Codes" section updated with new behavior
- CONTRIBUTING.md includes exit code testing guidance
- Inline code comments explain the skip-detection logic
