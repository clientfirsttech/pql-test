# Remove `--local` CLI Flag Epic

**Status**: 🚧 IN PROGRESS (2026-05-26)
**Goal**: Drop the `--local` boolean option from `pql-test run-tests` and `pql-test retrieve-tests`. The `local/<model_name>` model-path syntax already provides local Power BI Desktop discovery — `--local` is redundant and offers a strictly worse UX (it requires both a filesystem path AND the flag, while `local/<name>` needs neither).

## Overview

The CLI currently supports two ways to target a locally-open Power BI Desktop instance:

1. `pql-test run-tests local/SampleModel` — routes through `resolve_local_xmla_connection_by_name()` and matches the model by window-title name. No filesystem path required.
2. `pql-test run-tests ./examples/SampleModel.SemanticModel --local` — routes through `resolve_local_xmla_connection()` and matches by the `.pbip` filename stem inside the given path.

Both end up at the same Analysis Services server on the local machine. The `local/<name>` form is cleaner (one argument vs. path-plus-flag), works without a checked-out repo, and aligns with the Fabric-CLI dot notation (`<workspace>.<semantic_model>`) we already adopted for service connections. Keeping `--local` adds a second way to do the same thing, which clutters help text and creates contradictory documentation (some examples show `local/<name>`, others show `--local`).

---

## Reject `--local` and Document `local/<name>` as the Sole Local Path

**Requirements**:
- Given a user invokes `pql-test run-tests <path> --local` or `pql-test retrieve-tests <path> --local`, should exit non-zero with Click's standard "No such option: --local" error
- Given a user invokes `pql-test run-tests local/<model_name>`, should continue to resolve the local Power BI Desktop instance by name and behave identically to today
- Given a user runs `pql-test run-tests --help` or `pql-test retrieve-tests --help`, should not list `--local` and should describe `local/<model_name>` as the only documented way to target a local instance
- Given a user runs `pql-test doctor`, should not mention `--local` in the psutil requirement string
- Given documentation (`README.md`, `skills/run-tests/SKILL.md`, `skills/check-prereqs/SKILL.md`), should describe `local/<name>` exclusively — no `--local` references anywhere

---

## Epic Vision (Definition of Done)

### Quality Gates (All Must Pass)

✅ **Ruff Check**: All code passes `ruff check python/` with zero violations

✅ **Code Review**: 
- `--local` flag removed cleanly with no orphaned code
- `local/<model_name>` syntax remains fully functional
- Help text is clear and unambiguous

✅ **Test Coverage**: 
- Overall test coverage ≥ 80% (`pytest --cov=pql_test --cov-fail-under=80`)
- All `local/<model_name>` scenarios have tests
- Tests verify `--local` is rejected
- All existing tests continue to pass

✅ **Documentation**: 
- README.md uses `local/<name>` exclusively
- CLI help text updated
- All skill files updated (run-tests, retrieve-tests, check-prereqs)
- UPGRADING.md documents removal of `--local` flag
