"""
Integration tests for the bridge between the auth subsystem
(`pql_test.auth.*`) and the runtime XMLA execution path
(`pql_test.runner._resolve_authentication_with_stored_credentials`, etc.).

These tests pin the behavior described in
tasks/unified-auth-runtime-epic.md: whichever method the user chose with
`pql-test auth login` must drive subsequent test execution, with the bearer
token funneled to ADOMD via the existing MSOLAP `Password=<bearer>;` segment.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from pql_test.auth.models import AuthMethod, AuthStatus, CredentialConfig
from pql_test.runner import (
    XmlaConnectionOptions,
    _resolve_authentication_with_stored_credentials,
)


# ---------------------------------------------------------------------------
# Stored-credentials → opts.access_token bridge
# ---------------------------------------------------------------------------


def _patch_manager_with_stored_config(
    config: CredentialConfig, fake_token: str
) -> MagicMock:
    """Build a MagicMock for AuthenticationManager that simulates a logged-in
    user with the supplied stored config + token."""
    manager = MagicMock()
    manager.get_status.return_value = AuthStatus(
        authenticated=True,
        method=config.method,
        tenant_id=config.tenant_id,
        client_id=config.client_id,
        environment=config.environment,
    )
    manager._store.load.return_value = config
    manager.get_access_token.return_value = fake_token
    return manager


def test_stored_interactive_creds_inject_bearer_into_opts(monkeypatch):
    """Given INTERACTIVE stored creds and no flags/env vars, the resolver must
    acquire a bearer via AuthenticationManager.get_access_token and surface
    it on opts.access_token."""
    # Make sure no PQL_* env var leaks
    for k in (
        "PQL_TENANT_ID", "PQL_CLIENT_ID", "PQL_CLIENT_SECRET",
        "PQL_WORKSPACE_ID", "PQL_DATASET_ID", "PQL_ENVIRONMENT",
        "CI",
    ):
        monkeypatch.delenv(k, raising=False)
    # Simulate an interactive TTY so the CI/TTY guard doesn't fire here.
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    stored = CredentialConfig(
        method=AuthMethod.INTERACTIVE,
        tenant_id="tenant-from-login",
        environment="Public",
        account_name="Alice@contoso.com",
    )
    fake_manager = _patch_manager_with_stored_config(stored, "interactive-bearer-xyz")

    with patch(
        "pql_test.auth.AuthenticationManager",
        return_value=fake_manager,
    ):
        empty_opts = XmlaConnectionOptions()
        resolved = _resolve_authentication_with_stored_credentials(empty_opts)

    assert getattr(resolved, "access_token", None) == "interactive-bearer-xyz", (
        "Stored INTERACTIVE creds must produce a bearer token on opts so the "
        "downstream service-XMLA resolver can use it. See "
        "tasks/unified-auth-runtime-epic.md."
    )
    assert resolved.tenant_id == "tenant-from-login"
    fake_manager.get_access_token.assert_called_once()


def test_stored_interactive_skipped_in_ci_environment(monkeypatch, capsys):
    """The runtime must NOT launch a browser when stdin isn't a TTY or CI=true.
    Instead it must warn on stderr and return opts unchanged so the caller
    falls back to local detection (or fails with a more specific message from
    the CLI layer).  Prevents hanging CI jobs.  See
    tasks/unified-auth-runtime-epic.md."""
    for k in (
        "PQL_TENANT_ID", "PQL_CLIENT_ID", "PQL_CLIENT_SECRET",
        "PQL_WORKSPACE_ID", "PQL_DATASET_ID", "PQL_ENVIRONMENT",
    ):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CI", "true")  # simulate a CI runner

    stored = CredentialConfig(
        method=AuthMethod.INTERACTIVE,
        tenant_id="tenant-from-login",
        environment="Public",
    )
    fake_manager = _patch_manager_with_stored_config(stored, "should-not-be-acquired")

    with patch(
        "pql_test.auth.AuthenticationManager",
        return_value=fake_manager,
    ):
        resolved = _resolve_authentication_with_stored_credentials(
            XmlaConnectionOptions()
        )

    # No bearer was acquired (no hang on browser prompt).
    assert getattr(resolved, "access_token", None) is None
    fake_manager.get_access_token.assert_not_called()

    # A clear diagnostic was emitted on stderr.
    captured = capsys.readouterr()
    assert "non-interactive environment" in captured.err.lower()
    assert "auth login" in captured.err


def test_stored_spn_cert_creds_inject_bearer_into_opts(monkeypatch):
    """SERVICE_PRINCIPAL_CERT must also produce a bearer (acquired via
    CertificateCredential under the hood) on opts.access_token."""
    for k in (
        "PQL_TENANT_ID", "PQL_CLIENT_ID", "PQL_CLIENT_SECRET",
        "PQL_WORKSPACE_ID", "PQL_DATASET_ID", "PQL_ENVIRONMENT",
    ):
        monkeypatch.delenv(k, raising=False)

    stored = CredentialConfig(
        method=AuthMethod.SERVICE_PRINCIPAL_CERT,
        tenant_id="tenant-cert",
        client_id="client-cert",
        certificate_path="/path/to/cert.pem",
        environment="Public",
    )
    fake_manager = _patch_manager_with_stored_config(stored, "cert-bearer-abc")

    with patch(
        "pql_test.auth.AuthenticationManager",
        return_value=fake_manager,
    ):
        resolved = _resolve_authentication_with_stored_credentials(
            XmlaConnectionOptions()
        )

    assert getattr(resolved, "access_token", None) == "cert-bearer-abc"
    assert resolved.tenant_id == "tenant-cert"
    assert resolved.client_id == "client-cert"


def test_stored_managed_identity_injects_bearer_into_opts(monkeypatch):
    """MANAGED_IDENTITY: same shape — bearer on opts."""
    for k in (
        "PQL_TENANT_ID", "PQL_CLIENT_ID", "PQL_CLIENT_SECRET",
        "PQL_WORKSPACE_ID", "PQL_DATASET_ID", "PQL_ENVIRONMENT",
    ):
        monkeypatch.delenv(k, raising=False)

    stored = CredentialConfig(
        method=AuthMethod.MANAGED_IDENTITY,
        use_system_assigned_identity=True,
        environment="Public",
    )
    fake_manager = _patch_manager_with_stored_config(stored, "mi-bearer-123")

    with patch(
        "pql_test.auth.AuthenticationManager",
        return_value=fake_manager,
    ):
        resolved = _resolve_authentication_with_stored_credentials(
            XmlaConnectionOptions()
        )

    assert getattr(resolved, "access_token", None) == "mi-bearer-123"


def test_stored_spn_secret_still_uses_legacy_msal_bridge(monkeypatch):
    """Regression guard — SPN-secret stored creds must still flow through as
    tenant/client/secret triple (not as a pre-acquired token) so the existing
    MSAL path keeps working.  Today's happy path must not regress."""
    for k in (
        "PQL_TENANT_ID", "PQL_CLIENT_ID", "PQL_CLIENT_SECRET",
        "PQL_WORKSPACE_ID", "PQL_DATASET_ID", "PQL_ENVIRONMENT",
    ):
        monkeypatch.delenv(k, raising=False)

    stored = CredentialConfig(
        method=AuthMethod.SERVICE_PRINCIPAL_SECRET,
        tenant_id="tenant-spn",
        client_id="client-spn",
        client_secret="secret-spn",
        environment="Public",
    )
    fake_manager = _patch_manager_with_stored_config(stored, "should-not-be-used")

    with patch(
        "pql_test.auth.AuthenticationManager",
        return_value=fake_manager,
    ):
        resolved = _resolve_authentication_with_stored_credentials(
            XmlaConnectionOptions()
        )

    # The secret is forwarded; the legacy MSAL acquire happens downstream.
    assert resolved.tenant_id == "tenant-spn"
    assert resolved.client_id == "client-spn"
    assert resolved.client_secret == "secret-spn"
    # And we must NOT pre-acquire a token for SPN-secret (downstream MSAL does it).
    assert getattr(resolved, "access_token", None) is None
    fake_manager.get_access_token.assert_not_called()


def test_cli_flags_take_precedence_over_stored_creds(monkeypatch):
    """CLI flags / env vars must override any stored login."""
    for k in (
        "PQL_TENANT_ID", "PQL_CLIENT_ID", "PQL_CLIENT_SECRET",
        "PQL_WORKSPACE_ID", "PQL_DATASET_ID", "PQL_ENVIRONMENT",
    ):
        monkeypatch.delenv(k, raising=False)

    stored = CredentialConfig(
        method=AuthMethod.INTERACTIVE,
        tenant_id="stored-tenant",
        environment="Public",
    )
    fake_manager = _patch_manager_with_stored_config(stored, "stored-token")

    opts_with_flags = XmlaConnectionOptions(
        tenant_id="flag-tenant",
        client_id="flag-client",
        client_secret="flag-secret",
    )

    with patch(
        "pql_test.auth.AuthenticationManager",
        return_value=fake_manager,
    ):
        resolved = _resolve_authentication_with_stored_credentials(opts_with_flags)

    # Flags win — stored config not consulted, no token acquired.
    assert resolved.tenant_id == "flag-tenant"
    assert resolved.client_id == "flag-client"
    assert resolved.client_secret == "flag-secret"
    assert getattr(resolved, "access_token", None) is None
    fake_manager.get_access_token.assert_not_called()


def test_no_stored_creds_no_flags_returns_opts_unchanged(monkeypatch):
    """When nothing is configured, the resolver must return opts unchanged so
    the caller falls back to local PBI Desktop detection."""
    for k in (
        "PQL_TENANT_ID", "PQL_CLIENT_ID", "PQL_CLIENT_SECRET",
        "PQL_WORKSPACE_ID", "PQL_DATASET_ID", "PQL_ENVIRONMENT",
    ):
        monkeypatch.delenv(k, raising=False)

    fake_manager = MagicMock()
    fake_manager.get_status.return_value = AuthStatus(authenticated=False)

    with patch(
        "pql_test.auth.AuthenticationManager",
        return_value=fake_manager,
    ):
        opts = XmlaConnectionOptions()
        resolved = _resolve_authentication_with_stored_credentials(opts)

    assert resolved.tenant_id is None
    assert resolved.client_id is None
    assert resolved.client_secret is None
    assert getattr(resolved, "access_token", None) is None


# ---------------------------------------------------------------------------
# Service-connection resolvers honor pre-acquired bearer
# ---------------------------------------------------------------------------


def test_service_resolver_uses_pretoken_skipping_msal(monkeypatch):
    """When opts already carries an access_token, _resolve_service_xmla_connection
    must use it directly and NOT call MSAL.  Otherwise interactive / cert / MI
    auth would silently re-acquire via SPN-client-credentials (and fail)."""
    from pql_test.runner import _resolve_service_xmla_connection

    opts = XmlaConnectionOptions(
        tenant_id="t",
        workspace_id="w",
        dataset_id="d",
        access_token="pre-acquired-bearer",
    )

    # Mock REST calls so we don't actually hit api.powerbi.com.
    monkeypatch.setattr(
        "pql_test.runner._resolve_pbi_workspace_and_dataset_names",
        lambda **kwargs: ("WorkspaceName", "DatasetName"),
    )
    spn_token_mock = MagicMock(return_value="should-not-be-called")
    monkeypatch.setattr(
        "pql_test.runner._acquire_service_principal_token", spn_token_mock
    )

    conn = _resolve_service_xmla_connection(opts)

    assert conn.access_token == "pre-acquired-bearer"
    spn_token_mock.assert_not_called()


def test_resolve_by_name_works_with_pretoken_no_secret(monkeypatch):
    """resolve_service_xmla_connection_by_name must accept a pre-acquired
    bearer (from stored interactive/cert/MI/federated auth) WITHOUT requiring
    client_secret.  This used to be SPN-only — the new code path lets any
    logged-in user use Fabric dot notation."""
    from pql_test.runner import resolve_service_xmla_connection_by_name

    for k in (
        "PQL_TENANT_ID", "PQL_CLIENT_ID", "PQL_CLIENT_SECRET",
        "PQL_WORKSPACE_ID", "PQL_DATASET_ID", "PQL_ENVIRONMENT",
        "CI",
    ):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    stored = CredentialConfig(
        method=AuthMethod.INTERACTIVE,
        tenant_id="user-tenant",
        environment="Public",
        account_name="alice@contoso.com",
    )
    fake_manager = _patch_manager_with_stored_config(stored, "alice-bearer")

    spn_token_mock = MagicMock(return_value="should-not-be-called")
    monkeypatch.setattr(
        "pql_test.runner._acquire_service_principal_token", spn_token_mock
    )

    with patch(
        "pql_test.auth.AuthenticationManager",
        return_value=fake_manager,
    ):
        conn = resolve_service_xmla_connection_by_name(
            "MyWorkspace", "MyModel", XmlaConnectionOptions()
        )

    assert conn is not None, (
        "Fabric dot notation must work for logged-in interactive users; "
        "the legacy SPN-only guard has been removed."
    )
    assert conn.access_token == "alice-bearer"
    assert conn.catalog == "MyModel"
    assert "MyWorkspace" in conn.server
    spn_token_mock.assert_not_called()


def test_resolve_by_name_still_works_with_spn_secret(monkeypatch):
    """Regression — SPN-with-secret happy path still produces a connection."""
    from pql_test.runner import resolve_service_xmla_connection_by_name

    for k in (
        "PQL_TENANT_ID", "PQL_CLIENT_ID", "PQL_CLIENT_SECRET",
        "PQL_WORKSPACE_ID", "PQL_DATASET_ID", "PQL_ENVIRONMENT",
    ):
        monkeypatch.delenv(k, raising=False)

    opts = XmlaConnectionOptions(
        tenant_id="t-spn",
        client_id="c-spn",
        client_secret="s-spn",
    )

    monkeypatch.setattr(
        "pql_test.runner._acquire_service_principal_token",
        lambda *a, **kw: "spn-bearer",
    )

    conn = resolve_service_xmla_connection_by_name("MyWs", "MyModel", opts)
    assert conn is not None
    assert conn.access_token == "spn-bearer"


def test_resolve_by_name_returns_none_without_any_credentials(monkeypatch):
    """When nothing is configured, must still return None so callers fall
    back gracefully."""
    from pql_test.runner import resolve_service_xmla_connection_by_name

    for k in (
        "PQL_TENANT_ID", "PQL_CLIENT_ID", "PQL_CLIENT_SECRET",
        "PQL_WORKSPACE_ID", "PQL_DATASET_ID", "PQL_ENVIRONMENT",
    ):
        monkeypatch.delenv(k, raising=False)

    fake_manager = MagicMock()
    fake_manager.get_status.return_value = AuthStatus(authenticated=False)

    with patch(
        "pql_test.auth.AuthenticationManager",
        return_value=fake_manager,
    ):
        conn = resolve_service_xmla_connection_by_name(
            "X", "Y", XmlaConnectionOptions()
        )

    assert conn is None
