# Unified Auth Runtime Epic

**Status**: 🚧 IN PROGRESS (2026-05-26)
**Goal**: `pql-test run-tests` and `retrieve-tests` consume whichever authentication method the user chose with `pql-test auth login` — interactive, service principal (secret/cert/federated), or managed identity — so the runtime identity matches the stored choice. The actual XMLA query still runs through ADOMD.NET / pyadomd; only the bearer-token source changes.

## Overview

Today the project has two parallel auth subsystems that don't connect end-to-end:

- **Modern path** (`pql-test auth login`): builds an `azure-identity` credential (`InteractiveBrowserCredential`, `ClientSecretCredential`, `CertificateCredential`, `ClientAssertionCredential`, or `ManagedIdentityCredential`), acquires a token, and stores the config in the platform keyring via `CredentialStore`.
- **Runtime path** (`run-tests` / `retrieve-tests` execution): reads CLI flags or `PQL_*` env vars and calls MSAL's `ConfidentialClientApplication.acquire_token_for_client` — service-principal-with-secret only.

The bridge at [runner.py:898 `_resolve_authentication_with_stored_credentials`](python/pql_test/runner.py#L898) only forwards `SERVICE_PRINCIPAL_SECRET` stored configs into the runtime path. Stored `INTERACTIVE`, `SERVICE_PRINCIPAL_CERT`, `SERVICE_PRINCIPAL_FEDERATED`, and `MANAGED_IDENTITY` configs are silently ignored by the runtime — so users who run `pql-test auth login` interactively and then `pql-test run-tests` find that their stored login does nothing.

This epic closes the gap by acquiring a bearer token via `AuthenticationManager.get_access_token(scope)` (which already handles all five auth methods) when stored creds exist with a non-secret method, then handing that token to ADOMD via the existing `Password=<bearer>;` connection-string segment. No change to ADOMD/pyadomd usage — only the token source changes.

---

## Stored Authentication Methods Drive Runtime Identity

**Requirements**:
- Given a user runs `pql-test auth login` (interactive browser) and then `pql-test run-tests <workspace>.<model>`, should acquire a bearer for the logged-in user via `InteractiveBrowserCredential` and execute the DAX query as that user
- Given a user runs `pql-test auth login -u <client-id> -p <secret> --tenant <tenant-id>` and then `pql-test run-tests <workspace>.<model>`, should continue to authenticate as the service principal (regression — must not break the current happy path)
- Given a user runs `pql-test auth login -u <client-id> --certificate cert.pem --tenant <tenant-id>` and then `pql-test run-tests <workspace>.<model>`, should acquire a bearer via `CertificateCredential` and execute as the service principal identity
- Given a user runs `pql-test auth login --identity` on an Azure VM and then `pql-test run-tests <workspace>.<model>`, should acquire a bearer via `ManagedIdentityCredential` and execute as the managed identity
- Given a user runs `pql-test auth login --federated-token <token> --user <client-id> --tenant <tenant-id>` and then `pql-test run-tests`, should acquire a bearer via `ClientAssertionCredential` and execute as the federated identity
- Given the bearer token has been acquired by any method, should be passed to ADOMD/pyadomd via the MSOLAP `Password=<bearer>;` connection-string segment exactly as today (no change to XMLA execution path)

## CLI Flags and Env Vars Continue to Take Precedence

**Requirements**:
- Given a user provides `--tenant-id` / `--client-id` / `--client-secret` flags directly, should use those credentials via MSAL regardless of any stored login
- Given the user sets `PQL_TENANT_ID` / `PQL_CLIENT_ID` / `PQL_CLIENT_SECRET` env vars, should use those credentials via MSAL regardless of any stored login
- Given neither flags nor env vars are set but stored credentials exist, should use the stored method
- Given neither flags, env vars, nor stored credentials are present, should fall back to local Power BI Desktop detection (current behavior)

## Fail Fast Instead of Hanging on Interactive Prompts in CI

**Requirements**:
- Given stored credentials have method `INTERACTIVE` and the runtime detects a non-TTY stdin or the `CI` env var is set, should fail with a clear error message ("Stored interactive credentials cannot be used in a non-interactive environment; run pql-test auth login with --user/--password or --identity for CI") instead of hanging on a browser prompt that no one is there to complete
- Given stored credentials have method `INTERACTIVE` and the runtime is in a TTY (developer machine), should launch the browser prompt as expected

---

## Epic Vision (Definition of Done)

### Quality Gates (All Must Pass)

✅ **Ruff Check**: All code passes `ruff check python/` with zero violations

✅ **Code Review**: 
- All 5 auth methods (interactive, SPN secret/cert/federated, managed identity) flow correctly
- Priority order (CLI flags → env vars → stored creds → local fallback) is clear
- CI failure mode is fast and explicit (no hangs)
- Bearer token handling is secure

✅ **Test Coverage**: 
- Overall test coverage ≥ 80% (`pytest --cov=pql_test --cov-fail-under=80`)
- All auth method scenarios have dedicated tests
- Interactive CI failure mode tested
- Priority order verified in tests
- All existing tests continue to pass

✅ **Documentation**: 
- README.md "Authentication" section updated with all 5 methods
- Auth flow priority documented
- CONTRIBUTING.md includes auth testing guidance
- Inline code comments explain bridge logic
