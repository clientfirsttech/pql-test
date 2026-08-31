# XMLA Connection String Impersonation Composition Epic

**Status**: 🚧 IN PROGRESS (2026-05-23)
**Goal**: Ensure XMLA impersonation parameters (`EffectiveUserName`, `Roles`) are appended to the connection string regardless of which authentication mechanism is in use, so OLS/RLS impersonation actually reaches Analysis Services in CI

## Overview

[`_build_connection_string` in python/pql_test/runner.py](../python/pql_test/runner.py) builds the ADOMD connection string with an `if/return … if/return …` chain that exits as soon as the first branch matches. When a bearer access token is present (the CI / service-principal path), the function returns immediately after appending `Password=<token>;`, so any `Roles=` or `EffectiveUserName=` that the test discovery layer set on the connection is silently dropped before reaching Analysis Services.

Locally we don't have a bearer token, so the function falls through to the `Roles=` branch and OLS/RLS impersonation is applied — which is why `pql-test run-tests ./examples/OLS_Model.SemanticModel` passes against the locally open Power BI Desktop instance but the CI matrix entry for OLS_Model fails with `Actual: VISIBLE (OLS not working)`.

---

## Compose Auth And Impersonation In The Connection String

Refactor the connection-string builder so the auth segment and the impersonation segment are appended independently.

**Requirements**:
- Given a service-principal connection with a bearer `access_token` and a `role_name` annotation, should emit a connection string that contains both `Password=<token>` and `Roles=<role>` so Analysis Services applies the role's OLS/RLS rules
- Given a service-principal connection with a bearer `access_token` and an `effective_user_name` annotation, should emit a connection string that contains both `Password=<token>` and `EffectiveUserName=<UPN>` so Analysis Services impersonates the user
- Given a local Power BI Desktop connection (no token, no SPN creds) with a `role_name`, should still emit `Roles=<role>` exactly as it does today
- Given a connection with no impersonation set, should emit only the auth segment with no spurious `Roles=` or `EffectiveUserName=` parameters

---

## Cover The Composition With Unit Tests

The connection string builder is the contract between the runner and ADOMD — broken composition is silent and only shows up as cross-environment test divergence. Test it directly.

**Requirements**:
- Given a connection with `access_token` and `roles`, the produced string contains both `Password=` and `Roles=`
- Given a connection with `access_token` and `effective_user_name`, the produced string contains both `Password=` and `EffectiveUserName=`
- Given a connection with SPN credentials and `roles`, the produced string contains both `User ID=app:` and `Roles=`
- Given a local connection (no token, no SPN, no impersonation), the produced string contains neither `Roles=` nor `EffectiveUserName=`

---

## Epic Vision (Definition of Done)

### Quality Gates (All Must Pass)

✅ **Ruff Check**: All code passes `ruff check python/` with zero violations

✅ **Code Review**: 
- Connection string builder composes auth and impersonation independently
- No conditional logic drops impersonation parameters
- Code is clear and maintainable

✅ **Test Coverage**: 
- Overall test coverage ≥ 80% (`pytest --cov=pql_test --cov-fail-under=80`)
- All auth+impersonation combinations have dedicated unit tests
- CI OLS/RLS tests pass
- All existing tests continue to pass

✅ **Documentation**: 
- Inline code comments explain connection string composition
- README.md documents OLS/RLS impersonation behavior
- CONTRIBUTING.md includes connection string testing guidance
