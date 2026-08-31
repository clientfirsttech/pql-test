"""
Tests for pql_test.auth.manager — Authentication manager orchestration.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import keyring
import pytest

from pql_test.auth.manager import AuthenticationManager, _decode_jwt_expiry
from pql_test.auth.models import AuthMethod, CredentialConfig
from pql_test.auth.exceptions import TokenAcquisitionError
from tests.auth.test_store import MockKeyring


@pytest.fixture(autouse=True)
def use_mock_keyring():
    """Use mock keyring backend for all tests."""
    original_keyring = keyring.get_keyring()
    keyring.set_keyring(MockKeyring())
    yield
    keyring.set_keyring(original_keyring)


def test_authentication_manager_save_and_load_config():
    """AuthenticationManager: should save and load credential configuration."""
    manager = AuthenticationManager(namespace="test-save")
    
    config = CredentialConfig(
        method=AuthMethod.SERVICE_PRINCIPAL_SECRET,
        tenant_id="tenant-123",
        client_id="client-456",
        client_secret="secret-789",
    )
    
    manager.save_credential(config)
    
    status = manager.get_status()
    assert status.authenticated is True
    assert status.method == AuthMethod.SERVICE_PRINCIPAL_SECRET
    assert status.tenant_id == "tenant-123"
    assert status.client_id == "client-456"


def test_authentication_manager_clear_credential():
    """AuthenticationManager: should clear stored credential."""
    manager = AuthenticationManager(namespace="test-clear")
    
    config = CredentialConfig(
        method=AuthMethod.INTERACTIVE,
        tenant_id="tenant-123",
    )
    
    manager.save_credential(config)
    assert manager.get_status().authenticated is True
    
    manager.clear_credential()
    assert manager.get_status().authenticated is False


def test_authentication_manager_get_credential():
    """AuthenticationManager: should create credential from stored config."""
    manager = AuthenticationManager(namespace="test-get-cred")
    
    config = CredentialConfig(
        method=AuthMethod.SERVICE_PRINCIPAL_SECRET,
        tenant_id="tenant-123",
        client_id="client-456",
        client_secret="secret-789",
    )
    
    manager.save_credential(config)
    credential = manager.get_credential()
    
    assert credential is not None


def test_authentication_manager_get_credential_when_not_authenticated():
    """AuthenticationManager: should return None when no credential stored."""
    manager = AuthenticationManager(namespace="test-no-cred")
    
    credential = manager.get_credential()
    assert credential is None


def test_authentication_manager_get_access_token():
    """AuthenticationManager: should acquire access token from credential."""
    manager = AuthenticationManager(namespace="test-token")
    
    config = CredentialConfig(
        method=AuthMethod.SERVICE_PRINCIPAL_SECRET,
        tenant_id="tenant-123",
        client_id="client-456",
        client_secret="secret-789",
    )
    
    manager.save_credential(config)
    
    # Mock the credential's get_token method
    with patch.object(manager, 'get_credential') as mock_get_credential:
        mock_credential = Mock()
        mock_credential.get_token.return_value = Mock(token="access-token-123")
        mock_get_credential.return_value = mock_credential
        
        token = manager.get_access_token()
        
        assert token == "access-token-123"
        mock_credential.get_token.assert_called_once()


def test_authentication_manager_get_access_token_when_not_authenticated():
    """AuthenticationManager: should return None when not authenticated."""
    manager = AuthenticationManager(namespace="test-no-token")
    
    token = manager.get_access_token()
    assert token is None


def test_authentication_manager_status_not_authenticated():
    """AuthenticationManager: should return not authenticated status when no credential stored."""
    manager = AuthenticationManager(namespace="test-status-none")
    
    status = manager.get_status()
    
    assert status.authenticated is False
    assert status.method is None
    assert status.account_name is None


# ---------------------------------------------------------------------------
# JWT Token Validation Tests (OWASP A07: Authentication Failures)
# ---------------------------------------------------------------------------

def _create_test_jwt(expires_in_seconds: int = 3600) -> str:
    """
    Create a test JWT token with specified expiry.

    Args:
        expires_in_seconds: Seconds until expiry (can be negative for expired tokens)

    Returns:
        JWT token string (header.payload.signature format)
    """
    now = datetime.now(timezone.utc)
    exp_time = now + timedelta(seconds=expires_in_seconds)
    exp_timestamp = int(exp_time.timestamp())

    # JWT header (typ and alg claims)
    header = {"typ": "JWT", "alg": "RS256"}
    header_b64 = base64.urlsafe_b64encode(
        json.dumps(header).encode()
    ).decode().rstrip("=")

    # JWT payload with exp claim
    payload = {
        "aud": "https://analysis.windows.net/powerbi/api",
        "iss": "https://sts.windows.net/tenant-123/",
        "exp": exp_timestamp,
        "nbf": int(now.timestamp()),
    }
    payload_b64 = base64.urlsafe_b64encode(
        json.dumps(payload).encode()
    ).decode().rstrip("=")

    # Fake signature (we don't verify it)
    signature_b64 = base64.urlsafe_b64encode(b"fake-signature").decode().rstrip("=")

    return f"{header_b64}.{payload_b64}.{signature_b64}"


def test_decode_jwt_expiry_with_valid_token():
    """_decode_jwt_expiry: should extract expiry from valid JWT token."""
    # Token expires in 1 hour
    token = _create_test_jwt(expires_in_seconds=3600)
    
    expiry = _decode_jwt_expiry(token)
    
    assert expiry is not None
    # Should be approximately 1 hour from now (allow 2 second tolerance)
    expected = datetime.now(timezone.utc) + timedelta(hours=1)
    assert abs((expiry - expected).total_seconds()) < 2


def test_decode_jwt_expiry_with_expired_token():
    """_decode_jwt_expiry: should extract expiry from expired JWT token."""
    # Token expired 1 hour ago
    token = _create_test_jwt(expires_in_seconds=-3600)
    
    expiry = _decode_jwt_expiry(token)
    
    assert expiry is not None
    # Should be approximately 1 hour in the past
    expected = datetime.now(timezone.utc) - timedelta(hours=1)
    assert abs((expiry - expected).total_seconds()) < 2


def test_decode_jwt_expiry_with_malformed_token():
    """_decode_jwt_expiry: should return None for malformed tokens."""
    # Not enough parts
    assert _decode_jwt_expiry("not.enough") is None
    
    # Too many parts
    assert _decode_jwt_expiry("too.many.parts.here") is None
    
    # Invalid base64
    assert _decode_jwt_expiry("invalid.!!!.base64") is None
    
    # Valid base64 but not JSON
    not_json = base64.urlsafe_b64encode(b"not json").decode()
    assert _decode_jwt_expiry(f"header.{not_json}.sig") is None


def test_decode_jwt_expiry_with_missing_exp_claim():
    """_decode_jwt_expiry: should return None when exp claim is missing."""
    # Create payload without 'exp' claim
    payload = {"aud": "https://analysis.windows.net/powerbi/api"}
    payload_b64 = base64.urlsafe_b64encode(
        json.dumps(payload).encode()
    ).decode().rstrip("=")
    
    token = f"header.{payload_b64}.signature"
    
    assert _decode_jwt_expiry(token) is None


def test_get_status_with_valid_token():
    """AuthenticationManager: should validate token and mark as valid."""
    manager = AuthenticationManager(namespace="test-valid-token")
    
    config = CredentialConfig(
        method=AuthMethod.SERVICE_PRINCIPAL_SECRET,
        tenant_id="tenant-123",
        client_id="client-456",
        client_secret="secret-789",
        account_name="Test Service Principal",
    )
    
    manager.save_credential(config)
    
    # Mock get_access_token to return a valid (non-expired) token
    valid_token = _create_test_jwt(expires_in_seconds=3600)  # Expires in 1 hour
    with patch.object(manager, 'get_access_token', return_value=valid_token):
        status = manager.get_status()
    
    assert status.authenticated is True
    assert status.method == AuthMethod.SERVICE_PRINCIPAL_SECRET
    assert status.account_name == "Test Service Principal"
    assert status.token_is_valid is True
    assert status.token_expires_at is not None
    # Token should expire approximately 1 hour from now
    expected_expiry = datetime.now(timezone.utc) + timedelta(hours=1)
    assert abs((status.token_expires_at - expected_expiry).total_seconds()) < 2


def test_get_status_with_expired_token():
    """AuthenticationManager: should detect expired token and mark as invalid."""
    manager = AuthenticationManager(namespace="test-expired-token")
    
    config = CredentialConfig(
        method=AuthMethod.INTERACTIVE,
        tenant_id="tenant-123",
        account_name="test@example.com",
    )
    
    manager.save_credential(config)
    
    # Mock get_access_token to return an expired token
    expired_token = _create_test_jwt(expires_in_seconds=-3600)  # Expired 1 hour ago
    with patch.object(manager, 'get_access_token', return_value=expired_token):
        status = manager.get_status()
    
    assert status.authenticated is True
    assert status.token_is_valid is False
    assert status.token_expires_at is not None
    # Expiry should be in the past
    assert status.token_expires_at < datetime.now(timezone.utc)


def test_get_status_when_token_acquisition_fails():
    """AuthenticationManager: should handle token acquisition failure gracefully."""
    manager = AuthenticationManager(namespace="test-token-fail")
    
    config = CredentialConfig(
        method=AuthMethod.SERVICE_PRINCIPAL_SECRET,
        tenant_id="tenant-123",
        client_id="client-456",
        client_secret="invalid-secret",
    )
    
    manager.save_credential(config)
    
    # Mock get_access_token to raise TokenAcquisitionError
    with patch.object(
        manager, 
        'get_access_token', 
        side_effect=TokenAcquisitionError("Auth failed")
    ):
        status = manager.get_status()
    
    # Should still show as authenticated (creds stored) but token invalid
    assert status.authenticated is True
    assert status.token_is_valid is False
    assert status.token_expires_at is None


def test_get_status_when_token_is_none():
    """AuthenticationManager: should handle None token gracefully."""
    manager = AuthenticationManager(namespace="test-none-token")
    
    config = CredentialConfig(
        method=AuthMethod.MANAGED_IDENTITY,
        use_system_assigned_identity=True,
    )
    
    manager.save_credential(config)
    
    # Mock get_access_token to return None
    with patch.object(manager, 'get_access_token', return_value=None):
        status = manager.get_status()
    
    assert status.authenticated is True
    assert status.token_is_valid is False
    assert status.token_expires_at is None
