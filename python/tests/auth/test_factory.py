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
