# SPDX-License-Identifier: AGPL-3.0-only
"""
Tests for pql_test.auth.factory — Credential factory for azure.identity.
"""

from __future__ import annotations

import pytest

from azure.identity import (
    ClientSecretCredential,
    InteractiveBrowserCredential,
)

from pql_test.auth.cloud_config import CloudConfig
from pql_test.auth.exceptions import CredentialConfigError
from pql_test.auth.factory import CredentialFactory
from pql_test.auth.models import AuthMethod, CredentialConfig


def test_credential_factory_interactive():
    """CredentialFactory: should create InteractiveBrowserCredential."""
    factory = CredentialFactory()
    cloud_config = CloudConfig()

    config = CredentialConfig(
        method=AuthMethod.INTERACTIVE,
        tenant_id="tenant-123",
        environment="Public",
    )

    credential = factory.create(config, cloud_config)

    assert isinstance(credential, InteractiveBrowserCredential)


# ---------------------------------------------------------------------------
# Persistent token cache — every CLI invocation must NOT open a browser tab.
# See tasks/surface-silent-test-discovery-failures-epic.md.
# ---------------------------------------------------------------------------


def test_interactive_credential_enables_persistent_token_cache(monkeypatch):
    """InteractiveBrowserCredential must be constructed with
    cache_persistence_options so MSAL writes tokens to the platform's
    secure store and subsequent CLI invocations reuse them silently."""
    from unittest.mock import patch as mock_patch

    captured = {}

    def fake_constructor(self, **kwargs):  # type: ignore[no-untyped-def]
        captured["kwargs"] = kwargs

    with mock_patch.object(
        InteractiveBrowserCredential, "__init__", fake_constructor
    ):
        factory = CredentialFactory()
        cloud_config = CloudConfig()
        factory.create(
            CredentialConfig(
                method=AuthMethod.INTERACTIVE,
                tenant_id=None,
                client_id=None,
                environment="Public",
            ),
            cloud_config,
        )

    opts = captured["kwargs"].get("cache_persistence_options")
    assert opts is not None, (
        "InteractiveBrowserCredential must be passed cache_persistence_options "
        "so tokens persist across CLI invocations and the user isn't prompted "
        "to sign in on every command. See "
        "tasks/surface-silent-test-discovery-failures-epic.md."
    )


def test_spn_secret_credential_enables_persistent_token_cache():
    """SPN flows also benefit from cache persistence — saves a round-trip to
    AAD on every CLI invocation."""
    from unittest.mock import patch as mock_patch

    captured = {}

    def fake_constructor(self, **kwargs):  # type: ignore[no-untyped-def]
        captured["kwargs"] = kwargs

    with mock_patch.object(
        ClientSecretCredential, "__init__", fake_constructor
    ):
        factory = CredentialFactory()
        cloud_config = CloudConfig()
        factory.create(
            CredentialConfig(
                method=AuthMethod.SERVICE_PRINCIPAL_SECRET,
                tenant_id="t",
                client_id="c",
                client_secret="s",
                environment="Public",
            ),
            cloud_config,
        )

    assert captured["kwargs"].get("cache_persistence_options") is not None


def test_persistent_cache_respects_unencrypted_storage_env_var(monkeypatch):
    """Headless Linux without libsecret needs an opt-in escape hatch.  When
    PQL_TEST_ALLOW_UNENCRYPTED_TOKEN_CACHE=1, the persistence options must
    permit unencrypted file storage."""
    monkeypatch.setenv("PQL_TEST_ALLOW_UNENCRYPTED_TOKEN_CACHE", "1")

    from unittest.mock import patch as mock_patch

    captured = {}

    def fake_constructor(self, **kwargs):  # type: ignore[no-untyped-def]
        captured["kwargs"] = kwargs

    with mock_patch.object(
        InteractiveBrowserCredential, "__init__", fake_constructor
    ):
        factory = CredentialFactory()
        cloud_config = CloudConfig()
        factory.create(
            CredentialConfig(
                method=AuthMethod.INTERACTIVE,
                tenant_id=None,
                client_id=None,
                environment="Public",
            ),
            cloud_config,
        )

    opts = captured["kwargs"].get("cache_persistence_options")
    assert opts is not None
    assert getattr(opts, "allow_unencrypted_storage", False) is True, (
        "PQL_TEST_ALLOW_UNENCRYPTED_TOKEN_CACHE=1 must propagate to "
        "TokenCachePersistenceOptions so headless Linux without libsecret "
        "can still use cache persistence."
    )


def test_interactive_credential_replays_stored_authentication_record():
    """A stored AuthenticationRecord JSON must be deserialised and passed
    back to InteractiveBrowserCredential as ``authentication_record``.

    Without this, ``cache_persistence_options`` writes a cache that
    ``azure-identity`` cannot look up on subsequent runs (no homeAccountId
    to key by) — so the user gets a browser popup despite the cache file
    sitting right there on disk.  See
    tasks/surface-silent-test-discovery-failures-epic.md.
    """
    from unittest.mock import patch as mock_patch
    from azure.identity import AuthenticationRecord

    # Build a real AuthenticationRecord and serialize it to the canonical
    # JSON shape azure-identity produces — this is what cmd_auth_login
    # stores after a successful interactive sign-in.
    real_record = AuthenticationRecord(
        tenant_id="7d022805",
        client_id="795808c6",
        authority="login.microsoftonline.com",
        home_account_id="abc.def",
        username="u@x.com",
    )
    record_json = real_record.serialize()

    captured = {}

    def fake_constructor(self, **kwargs):  # type: ignore[no-untyped-def]
        captured["kwargs"] = kwargs

    with mock_patch.object(
        InteractiveBrowserCredential, "__init__", fake_constructor
    ):
        factory = CredentialFactory()
        cloud_config = CloudConfig()
        factory.create(
            CredentialConfig(
                method=AuthMethod.INTERACTIVE,
                tenant_id=None,
                client_id=None,
                environment="Public",
                authentication_record_json=record_json,
            ),
            cloud_config,
        )

    record = captured["kwargs"].get("authentication_record")
    assert record is not None, (
        "Stored authentication_record_json must be deserialised and passed "
        "to InteractiveBrowserCredential so subsequent CLI invocations can "
        "look up the cached token silently."
    )
    assert isinstance(record, AuthenticationRecord)
    assert record.username == "u@x.com"
    assert record.home_account_id == "abc.def"


def test_interactive_credential_handles_corrupt_authentication_record():
    """Garbage JSON in authentication_record_json must not crash the factory —
    fall through to a fresh interactive prompt instead."""
    from unittest.mock import patch as mock_patch

    captured = {}

    def fake_constructor(self, **kwargs):  # type: ignore[no-untyped-def]
        captured["kwargs"] = kwargs

    with mock_patch.object(
        InteractiveBrowserCredential, "__init__", fake_constructor
    ):
        factory = CredentialFactory()
        cloud_config = CloudConfig()
        factory.create(
            CredentialConfig(
                method=AuthMethod.INTERACTIVE,
                tenant_id=None,
                client_id=None,
                environment="Public",
                authentication_record_json="this-is-not-valid-json-at-all",
            ),
            cloud_config,
        )

    # Factory must not raise.  authentication_record should be None
    # (fall back to fresh interactive auth).
    assert captured["kwargs"].get("authentication_record") is None


# ---------------------------------------------------------------------------
# Real-constructor smoke tests — catch kwarg-collision-class bugs that
# mocked-__init__ tests miss because azure-identity's actual constructor
# never runs in those.  See the 2026-05-27 "got multiple values for keyword
# argument 'authority'" incident.
# ---------------------------------------------------------------------------


def test_interactive_credential_with_record_constructs_without_raising():
    """Construct InteractiveBrowserCredential through the factory with a
    REAL stored AuthenticationRecord.  No mocks on __init__ — we want
    azure-identity's actual constructor to run.

    This catches the kwarg-collision bug where passing both
    ``authentication_record`` and ``authority`` / ``tenant_id`` / ``client_id``
    to ``MsalCredential.__init__`` raises a TypeError because the parent
    class extracts authority etc. from the record AND from explicit kwargs.
    """
    from azure.identity import AuthenticationRecord

    record = AuthenticationRecord(
        tenant_id="00000000-0000-0000-0000-000000000001",
        client_id="00000000-0000-0000-0000-000000000002",
        authority="login.microsoftonline.com",
        home_account_id="x.y",
        username="u@example.com",
    )

    factory = CredentialFactory()
    cloud_config = CloudConfig()
    config = CredentialConfig(
        method=AuthMethod.INTERACTIVE,
        # Explicitly set tenant/client too — even if they're set on the
        # config, the factory must not double-pass them when a record is
        # also being passed.
        tenant_id="should-be-ignored-because-record-wins",
        client_id="also-should-be-ignored",
        environment="Public",
        authentication_record_json=record.serialize(),
    )

    # If the factory passes conflicting kwargs to InteractiveBrowserCredential,
    # this will raise TypeError("got multiple values for keyword argument ...").
    credential = factory.create(config, cloud_config)
    assert isinstance(credential, InteractiveBrowserCredential)


def test_interactive_credential_without_record_constructs_without_raising():
    """Same smoke test for the first-login path (no stored record yet).
    Catches breaks in the OTHER branch of the factory's if/else."""
    factory = CredentialFactory()
    cloud_config = CloudConfig()
    config = CredentialConfig(
        method=AuthMethod.INTERACTIVE,
        tenant_id="00000000-0000-0000-0000-000000000001",
        client_id=None,
        environment="Public",
        authentication_record_json=None,
    )
    credential = factory.create(config, cloud_config)
    assert isinstance(credential, InteractiveBrowserCredential)


# ---------------------------------------------------------------------------
# Cert / federated / managed-identity cache-persistence coverage.
# Earlier tests only covered INTERACTIVE and SPN-SECRET — gap noted in the
# audit, closing it here.
# ---------------------------------------------------------------------------


def test_spn_cert_credential_enables_persistent_token_cache():
    """SERVICE_PRINCIPAL_CERT must also receive cache_persistence_options
    so subsequent CLI invocations skip the AAD round-trip."""
    from unittest.mock import patch as mock_patch
    from azure.identity import CertificateCredential

    captured = {}

    def fake_constructor(self, **kwargs):  # type: ignore[no-untyped-def]
        captured["kwargs"] = kwargs

    with mock_patch.object(CertificateCredential, "__init__", fake_constructor):
        factory = CredentialFactory()
        cloud_config = CloudConfig()
        factory.create(
            CredentialConfig(
                method=AuthMethod.SERVICE_PRINCIPAL_CERT,
                tenant_id="t",
                client_id="c",
                certificate_path="/tmp/cert.pem",
                environment="Public",
            ),
            cloud_config,
        )

    assert captured["kwargs"].get("cache_persistence_options") is not None


def test_spn_federated_credential_enables_persistent_token_cache():
    """SERVICE_PRINCIPAL_FEDERATED (ClientAssertionCredential) must also
    receive cache_persistence_options."""
    from unittest.mock import patch as mock_patch
    from azure.identity import ClientAssertionCredential

    captured = {}

    def fake_constructor(self, **kwargs):  # type: ignore[no-untyped-def]
        captured["kwargs"] = kwargs

    with mock_patch.object(ClientAssertionCredential, "__init__", fake_constructor):
        factory = CredentialFactory()
        cloud_config = CloudConfig()
        factory.create(
            CredentialConfig(
                method=AuthMethod.SERVICE_PRINCIPAL_FEDERATED,
                tenant_id="t",
                client_id="c",
                federated_token="some-token",
                environment="Public",
            ),
            cloud_config,
        )

    assert captured["kwargs"].get("cache_persistence_options") is not None


def test_managed_identity_credential_does_not_receive_cache_persistence_options():
    """ManagedIdentityCredential intentionally does NOT accept
    cache_persistence_options — passing it would raise TypeError.  The
    factory must skip the kwarg for the MI branch.  Token caching is handled
    by the underlying IMDS endpoint."""
    from unittest.mock import patch as mock_patch
    from azure.identity import ManagedIdentityCredential

    captured = {}

    def fake_constructor(self, **kwargs):  # type: ignore[no-untyped-def]
        captured["kwargs"] = kwargs

    with mock_patch.object(ManagedIdentityCredential, "__init__", fake_constructor):
        factory = CredentialFactory()
        cloud_config = CloudConfig()
        factory.create(
            CredentialConfig(
                method=AuthMethod.MANAGED_IDENTITY,
                use_system_assigned_identity=True,
                environment="Public",
            ),
            cloud_config,
        )

    assert "cache_persistence_options" not in captured["kwargs"], (
        "ManagedIdentityCredential doesn't accept cache_persistence_options; "
        "passing it would raise TypeError at runtime."
    )


def test_credential_factory_service_principal_secret():
    """CredentialFactory: should create ClientSecretCredential."""
    factory = CredentialFactory()
    cloud_config = CloudConfig()
    
    config = CredentialConfig(
        method=AuthMethod.SERVICE_PRINCIPAL_SECRET,
        tenant_id="tenant-123",
        client_id="client-456",
        client_secret="secret-789",
        environment="Public",
    )
    
    credential = factory.create(config, cloud_config)
    
    assert isinstance(credential, ClientSecretCredential)


def test_credential_factory_service_principal_secret_missing_fields():
    """CredentialFactory: should raise error when required fields missing for service principal secret."""
    factory = CredentialFactory()
    cloud_config = CloudConfig()
    
    config = CredentialConfig(
        method=AuthMethod.SERVICE_PRINCIPAL_SECRET,
        tenant_id="tenant-123",
        # Missing client_id and client_secret
    )
    
    with pytest.raises(CredentialConfigError) as exc_info:
        factory.create(config, cloud_config)
    
    assert "requires tenant_id, client_id, and client_secret" in str(exc_info.value)


def test_credential_factory_unsupported_method():
    """CredentialFactory: should raise error for unsupported authentication method."""
    factory = CredentialFactory()
    cloud_config = CloudConfig()
    
    # Create config with valid method, then hack it to invalid value
    config = CredentialConfig(
        method=AuthMethod.INTERACTIVE,
        tenant_id="tenant-123",
    )
    # Simulate an unknown method by modifying the enum
    config.method = "unknown_method"  # type: ignore
    
    with pytest.raises(CredentialConfigError):
        factory.create(config, cloud_config)
