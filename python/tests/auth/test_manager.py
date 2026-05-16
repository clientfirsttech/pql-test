"""
Tests for pql_test.auth.manager — Authentication manager orchestration.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import keyring
import pytest

from pql_test.auth.manager import AuthenticationManager
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
