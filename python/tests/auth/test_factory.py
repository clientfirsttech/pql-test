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


def test_credential_factory_interactive_uses_pql_test_default_client_id(monkeypatch):
    """Given no client_id on the config, the factory must pass pql-test's
    own registered multi-tenant client_id to InteractiveBrowserCredential —
    Azure-identity's default ("Azure development application") is rejected by
    Power BI XMLA.  See tasks/unified-auth-runtime-epic.md and the AAD app
    registration on the Power BI side."""
    monkeypatch.delenv("PQL_TEST_INTERACTIVE_CLIENT_ID", raising=False)

    from pql_test.auth.factory import PQL_TEST_DEFAULT_INTERACTIVE_CLIENT_ID

    factory = CredentialFactory()
    cloud_config = CloudConfig()
    config = CredentialConfig(
        method=AuthMethod.INTERACTIVE,
        tenant_id=None,
        client_id=None,
        environment="Public",
    )

    credential = factory.create(config, cloud_config)

    # InteractiveBrowserCredential exposes _client_id via its internal config
    # (azure-identity 1.15+).  Fall back to the public-ish attribute used
    # historically.
    actual = (
        getattr(credential, "_client_id", None)
        or getattr(credential, "client_id", None)
    )
    assert actual == PQL_TEST_DEFAULT_INTERACTIVE_CLIENT_ID, (
        f"Expected the factory to use the pql-test default client_id "
        f"({PQL_TEST_DEFAULT_INTERACTIVE_CLIENT_ID}) but got {actual!r}"
    )


def test_credential_factory_interactive_respects_explicit_client_id(monkeypatch):
    """When the user supplies their own client_id (their org's AAD app), the
    factory must use that value instead of the bundled default."""
    monkeypatch.delenv("PQL_TEST_INTERACTIVE_CLIENT_ID", raising=False)

    factory = CredentialFactory()
    cloud_config = CloudConfig()
    config = CredentialConfig(
        method=AuthMethod.INTERACTIVE,
        tenant_id="contoso-tenant",
        client_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        environment="Public",
    )

    credential = factory.create(config, cloud_config)

    actual = (
        getattr(credential, "_client_id", None)
        or getattr(credential, "client_id", None)
    )
    assert actual == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def test_credential_factory_interactive_respects_env_var_override(monkeypatch):
    """A maintainer-rebuilt fork can override the bundled client_id via the
    PQL_TEST_INTERACTIVE_CLIENT_ID env var without forking the code."""
    monkeypatch.setenv(
        "PQL_TEST_INTERACTIVE_CLIENT_ID",
        "11111111-2222-3333-4444-555555555555",
    )

    factory = CredentialFactory()
    cloud_config = CloudConfig()
    config = CredentialConfig(
        method=AuthMethod.INTERACTIVE,
        tenant_id=None,
        client_id=None,
        environment="Public",
    )

    credential = factory.create(config, cloud_config)

    actual = (
        getattr(credential, "_client_id", None)
        or getattr(credential, "client_id", None)
    )
    assert actual == "11111111-2222-3333-4444-555555555555"


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
