# SPDX-License-Identifier: AGPL-3.0-only
"""
Tests for pql_test.auth.models — Data models for authentication configuration.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from pql_test.auth.models import AuthMethod, AuthStatus, CredentialConfig


def test_auth_method_enum():
    """AuthMethod: should define all supported authentication methods."""
    assert AuthMethod.INTERACTIVE.value == "interactive"
    assert AuthMethod.SERVICE_PRINCIPAL_SECRET.value == "service_principal_secret"
    assert AuthMethod.SERVICE_PRINCIPAL_CERT.value == "service_principal_cert"
    assert AuthMethod.SERVICE_PRINCIPAL_FEDERATED.value == "service_principal_federated"
    assert AuthMethod.MANAGED_IDENTITY.value == "managed_identity"


def test_credential_config_service_principal_secret():
    """CredentialConfig: should store service principal with secret configuration."""
    config = CredentialConfig(
        method=AuthMethod.SERVICE_PRINCIPAL_SECRET,
        tenant_id="tenant-123",
        client_id="client-456",
        client_secret="secret-789",
        environment="Public",
        account_name="SP App",
    )
    
    assert config.method == AuthMethod.SERVICE_PRINCIPAL_SECRET
    assert config.tenant_id == "tenant-123"
    assert config.client_id == "client-456"
    assert config.client_secret == "secret-789"
    assert config.environment == "Public"
    assert config.account_name == "SP App"


def test_credential_config_interactive():
    """CredentialConfig: should store interactive authentication configuration."""
    config = CredentialConfig(
        method=AuthMethod.INTERACTIVE,
        tenant_id="tenant-123",
        environment="Public",
        account_name="user@example.com",
    )
    
    assert config.method == AuthMethod.INTERACTIVE
    assert config.tenant_id == "tenant-123"
    assert config.client_secret is None
    assert config.certificate_path is None


def test_credential_config_managed_identity_system():
    """CredentialConfig: should store system-assigned managed identity configuration."""
    config = CredentialConfig(
        method=AuthMethod.MANAGED_IDENTITY,
        use_system_assigned_identity=True,
        environment="Public",
    )
    
    assert config.method == AuthMethod.MANAGED_IDENTITY
    assert config.use_system_assigned_identity is True
    assert config.client_id is None


def test_credential_config_managed_identity_user():
    """CredentialConfig: should store user-assigned managed identity configuration."""
    config = CredentialConfig(
        method=AuthMethod.MANAGED_IDENTITY,
        client_id="identity-client-id",
        use_system_assigned_identity=False,
        environment="Public",
    )
    
    assert config.method == AuthMethod.MANAGED_IDENTITY
    assert config.client_id == "identity-client-id"
    assert config.use_system_assigned_identity is False


def test_credential_config_certificate():
    """CredentialConfig: should store certificate authentication configuration."""
    config = CredentialConfig(
        method=AuthMethod.SERVICE_PRINCIPAL_CERT,
        tenant_id="tenant-123",
        client_id="client-456",
        certificate_path="/path/to/cert.pem",
        certificate_password="cert-password",
        environment="Public",
    )
    
    assert config.method == AuthMethod.SERVICE_PRINCIPAL_CERT
    assert config.certificate_path == "/path/to/cert.pem"
    assert config.certificate_password == "cert-password"


def test_credential_config_federated():
    """CredentialConfig: should store federated credential configuration."""
    config = CredentialConfig(
        method=AuthMethod.SERVICE_PRINCIPAL_FEDERATED,
        tenant_id="tenant-123",
        client_id="client-456",
        federated_token="eyJ...",
        environment="Public",
    )
    
    assert config.method == AuthMethod.SERVICE_PRINCIPAL_FEDERATED
    assert config.federated_token == "eyJ..."


def test_credential_config_to_dict():
    """CredentialConfig: should serialize to dictionary."""
    config = CredentialConfig(
        method=AuthMethod.SERVICE_PRINCIPAL_SECRET,
        tenant_id="tenant-123",
        client_id="client-456",
        client_secret="secret-789",
    )
    
    config_dict = config.to_dict()
    
    assert config_dict["method"] == "service_principal_secret"
    assert config_dict["tenant_id"] == "tenant-123"
    assert config_dict["client_id"] == "client-456"
    assert config_dict["client_secret"] == "secret-789"


def test_credential_config_to_json():
    """CredentialConfig: should serialize to JSON string."""
    config = CredentialConfig(
        method=AuthMethod.SERVICE_PRINCIPAL_SECRET,
        tenant_id="tenant-123",
        client_id="client-456",
        client_secret="secret-789",
    )
    
    config_json = config.to_json()
    parsed = json.loads(config_json)
    
    assert parsed["method"] == "service_principal_secret"
    assert parsed["tenant_id"] == "tenant-123"


def test_credential_config_from_dict():
    """CredentialConfig: should deserialize from dictionary."""
    config_dict = {
        "method": "service_principal_secret",
        "tenant_id": "tenant-123",
        "client_id": "client-456",
        "client_secret": "secret-789",
        "environment": "Public",
    }
    
    config = CredentialConfig.from_dict(config_dict)
    
    assert config.method == AuthMethod.SERVICE_PRINCIPAL_SECRET
    assert config.tenant_id == "tenant-123"
    assert config.client_id == "client-456"
    assert config.client_secret == "secret-789"


def test_credential_config_from_json():
    """CredentialConfig: should deserialize from JSON string."""
    config_json = json.dumps({
        "method": "interactive",
        "tenant_id": "tenant-123",
        "environment": "Public",
        "account_name": "user@example.com",
    })
    
    config = CredentialConfig.from_json(config_json)
    
    assert config.method == AuthMethod.INTERACTIVE
    assert config.account_name == "user@example.com"


def test_auth_status_authenticated():
    """AuthStatus: should represent authenticated state."""
    expires_at = datetime.now() + timedelta(hours=1)
    status = AuthStatus(
        authenticated=True,
        method=AuthMethod.SERVICE_PRINCIPAL_SECRET,
        account_name="SP App",
        tenant_id="tenant-123",
        client_id="client-456",
        environment="Public",
        token_expires_at=expires_at,
        token_is_valid=True,
    )
    
    assert status.authenticated is True
    assert status.method == AuthMethod.SERVICE_PRINCIPAL_SECRET
    assert status.account_name == "SP App"
    assert status.token_is_valid is True


def test_auth_status_not_authenticated():
    """AuthStatus: should represent not authenticated state."""
    status = AuthStatus(authenticated=False)
    
    assert status.authenticated is False
    assert status.method is None
    assert status.account_name is None
    assert status.token_is_valid is False


def test_auth_status_token_expired():
    """AuthStatus: should indicate expired token."""
    expires_at = datetime.now() - timedelta(hours=1)
    status = AuthStatus(
        authenticated=True,
        method=AuthMethod.INTERACTIVE,
        token_expires_at=expires_at,
        token_is_valid=False,
    )
    
    assert status.authenticated is True
    assert status.token_is_valid is False
