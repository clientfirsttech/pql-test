# Surface Silent Test Discovery Failures Epic

**Status**: ✅ COMPLETED (2026-08-31)
**Goal**: Eliminate two classes of confusing "0 passed, 0 failed, 0 total" / wrong-results output produced by silent failure paths in the discovery layer:

1. `_retrieve_tests_via_dax` silently swallows every exception from the discovery DAX calls and returns `None`, hiding auth/permission/connectivity errors from the user — so a no-access bearer renders identically to an empty model.
2. `resolve_local_xmla_connection_by_name` falls back to *any* unnamed local Power BI Desktop instance when an exact name match isn't found, so `local/SampleModel` silently runs against whichever model happens to be open (e.g., RLS_Model), producing accurate-looking but misleading results.

---

## Surface Discovery Errors to the User

**Requirements**:
- Given `_retrieve_tests_via_dax(connection)` is invoked and both `PQL.Assert.RetrieveTestsV2()` and `PQL.Assert.RetrieveTests()` raise exceptions, should emit a one-line stderr warning that includes the verbatim exception type and message from the last failure so the user can distinguish "PQL.Assert isn't installed" (legitimate fallback) from "auth/permission/connectivity error" (real problem)
- Given V2 succeeds but V1 isn't called, should not emit any warning (clean path)
- Given V2 fails but V1 succeeds (older model without V2), should not emit any warning (legitimate fallback path)
- Given the warning fires, should write to stderr only — never stdout — so JSON output remains parseable
- Given the last discovery exception's `str(exc)` spans multiple lines (e.g. an ADOMD.NET exception whose message embeds a full .NET stack trace), the warning should include only the first line of that message so the warning itself stays a single line as intended, instead of truncating the raw multi-line string to 300 characters
- Given `code-coverage`'s per-category `_safe_query` helper in `coverage_collector.py` catches an exception whose `str(exc)` spans multiple lines, the recorded `UnavailableCategory.reason` should likewise include only the first line, so the "Unavailable categories" section of the coverage report never prints an embedded stack trace

## Make `local/<model_name>` Strict — No Silent Fallback to Wrong Instance

**Requirements**:
- Given `local/<model_name>` is supplied and `get_pbi_files_opened` returns at least one Power BI Desktop instance whose `model_name` matches case-insensitively, should connect to that instance (current happy path, no change)
- Given `local/<model_name>` is supplied and no detected instance matches the requested name, should return `None` regardless of how many unnamed instances are running. The previous "if exactly one unnamed instance, use it" rule must not apply to name-based requests because the user has explicitly stated which model they want.
- Given the CLI's `local/<model_name>` branch sees `conn is None`, should print a clear warning ("No matching Power BI Desktop instance found for model '<name>'. Open the model in Power BI Desktop and verify the window title matches.") and continue to skip-message behavior — unchanged from today.
- Given the model name match is case-insensitive but otherwise must be exact, this preserves the documented behavior in the README's Model Path Formats section.

## Replace "0 passed, 0 failed, 0 total" with a Clearer Empty-Result Line

**Requirements**:
- Given `_print_results` is called with a `TestSuite` where `total == 0` and at least one connection was attempted, should print "No tests found." instead of the bare counts summary, while still printing the counts on a subsequent line for compatibility with CI parsers
- Given `total > 0` (any actual results), should keep today's "N passed, N failed, N total" summary line unchanged
- Given the JSON-output `--output` path, should not be affected — JSON content is for machine consumption

## Exit Non-Zero on Discovery Failure (CI Misconfig Guard, Extension of Earlier Epic)

**Requirements**:
- Given `run-tests` ran a discovery DAX query that failed AND produced 0 test results, should exit with non-zero status so CI marks the job as failed (extends `tasks/fail-cli-when-no-tests-executed-epic.md`)
- Given `run-tests` produced 0 test results because the model legitimately has no tests (no discovery error, no test files), should exit 0 — an empty model is not a misconfiguration

## Persist Interactive Tokens Across CLI Invocations

**Requirements**:
- Given a user has run `pql-test auth login` interactively and successfully signed in, subsequent `pql-test` invocations (within the token's refresh-token TTL — typically ~24 hours) should reuse the cached token from the platform's secure store (Windows DPAPI / macOS Keychain / Linux libsecret) instead of opening a new browser tab
- Given `azure.identity` is being used to build an `InteractiveBrowserCredential`, `ClientSecretCredential`, `CertificateCredential`, or `ClientAssertionCredential`, the factory must pass `cache_persistence_options=TokenCachePersistenceOptions(name="pql-test")` so the underlying MSAL token cache is written to disk encrypted by the OS keystore
- Given `ManagedIdentityCredential` is used, no cache configuration is required because the IMDS endpoint provides its own caching
- Given the platform lacks an encrypted secure store (typically headless Linux without `libsecret`), should respect the `PQL_TEST_ALLOW_UNENCRYPTED_TOKEN_CACHE=1` environment variable as an opt-in escape hatch; default behaviour is secure-by-default (error rather than write unencrypted tokens)
- Given a user runs five `pql-test run-tests` commands in succession after a single `pql-test auth login`, should observe exactly zero browser tabs opening (today's behavior: five tabs)

---

## Epic Vision (Definition of Done)

### Quality Gates (All Must Pass)

✅ **Ruff Check**: All code passes `ruff check python/` with zero violations

✅ **Code Review**: 
- Discovery error messages are clear and actionable
- `local/<model_name>` strict matching prevents wrong-instance fallback
- Empty result messages distinguish "no tests" from "discovery failed"
- Token persistence is secure-by-default

✅ **Test Coverage**: 
- Overall test coverage ≥ 80% (`pytest --cov=pql_test --cov-fail-under=80`)
- Discovery error scenarios have dedicated tests
- `local/<model_name>` strict matching verified
- Token cache persistence tested
- All existing tests continue to pass

✅ **Documentation**: 
- README.md updated with discovery error troubleshooting
- `local/<model_name>` strict matching documented
- Token cache behavior documented
- CONTRIBUTING.md includes discovery debugging guidance
