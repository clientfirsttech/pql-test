"""
Tests for pql_test.auth.store — Credential storage using keyring.
"""

from __future__ import annotations

import keyring
import pytest

from pql_test.auth.exceptions import CredentialStorageError
from pql_test.auth.models import AuthMethod, CredentialConfig
from pql_test.auth.store import CredentialStore


class MockKeyring(keyring.backend.KeyringBackend):
    """In-memory keyring for testing."""
    
    priority = 1
    
    def __init__(self):
        self._store = {}
    
    def set_password(self, servicename, username, password):
        key = f"{servicename}:{username}"
        self._store[key] = password
    
    def get_password(self, servicename, username):
        key = f"{servicename}:{username}"
        return self._store.get(key)
    
    def delete_password(self, servicename, username):
        key = f"{servicename}:{username}"
        if key in self._store:
            del self._store[key]
        else:
            raise keyring.errors.PasswordDeleteError("Password not found")


@pytest.fixture(autouse=True)
def use_mock_keyring():
    """Use mock keyring backend for all tests."""
    original_keyring = keyring.get_keyring()
    keyring.set_keyring(MockKeyring())
    yield
    keyring.set_keyring(original_keyring)


def test_credential_store_save_and_load():
    """CredentialStore: should save and load credential configuration."""
    store = CredentialStore(namespace="test")
    config = CredentialConfig(
        method=AuthMethod.SERVICE_PRINCIPAL_SECRET,
        tenant_id="tenant-123",
        client_id="client-456",
        client_secret="secret-789",
    )
    
    store.save(config)
    loaded = store.load()
    
    assert loaded is not None
    assert loaded.method == AuthMethod.SERVICE_PRINCIPAL_SECRET
    assert loaded.tenant_id == "tenant-123"
    assert loaded.client_id == "client-456"
    assert loaded.client_secret == "secret-789"


def test_credential_store_load_when_empty():
    """CredentialStore: should return None when no credential stored."""
    store = CredentialStore(namespace="test-empty")
    loaded = store.load()
    assert loaded is None


def test_credential_store_delete():
    """CredentialStore: should delete stored credential."""
    store = CredentialStore(namespace="test-delete")
    config = CredentialConfig(
        method=AuthMethod.INTERACTIVE,
        tenant_id="tenant-123",
    )
    
    store.save(config)
    assert store.load() is not None
    
    store.delete()
    assert store.load() is None


def test_credential_store_delete_when_empty():
    """CredentialStore: should not raise error when deleting non-existent credential."""
    store = CredentialStore(namespace="test-delete-empty")
    # Should not raise
    store.delete()


def test_credential_store_overwrites_existing():
    """CredentialStore: should overwrite existing credential on save."""
    store = CredentialStore(namespace="test-overwrite")
    
    config1 = CredentialConfig(
        method=AuthMethod.INTERACTIVE,
        tenant_id="tenant-old",
    )
    store.save(config1)
    
    config2 = CredentialConfig(
        method=AuthMethod.SERVICE_PRINCIPAL_SECRET,
        tenant_id="tenant-new",
        client_id="client-new",
        client_secret="secret-new",
    )
    store.save(config2)
    
    loaded = store.load()
    assert loaded.method == AuthMethod.SERVICE_PRINCIPAL_SECRET
    assert loaded.tenant_id == "tenant-new"


def test_credential_store_namespace_isolation():
    """CredentialStore: should isolate credentials by namespace."""
    store1 = CredentialStore(namespace="ns1")
    store2 = CredentialStore(namespace="ns2")
    
    config1 = CredentialConfig(
        method=AuthMethod.INTERACTIVE,
        tenant_id="tenant-ns1",
    )
    config2 = CredentialConfig(
        method=AuthMethod.SERVICE_PRINCIPAL_SECRET,
        tenant_id="tenant-ns2",
        client_id="client-ns2",
        client_secret="secret-ns2",
    )
    
    store1.save(config1)
    store2.save(config2)
    
    loaded1 = store1.load()
    loaded2 = store2.load()
    
    assert loaded1.tenant_id == "tenant-ns1"
    assert loaded2.tenant_id == "tenant-ns2"


def test_credential_store_raises_when_keyring_is_unavailable(monkeypatch):
    """CredentialStore should fail cleanly when keyring support is missing."""
    import pql_test.auth.store as store_module

    monkeypatch.setattr(store_module, "HAS_KEYRING", False)

    with pytest.raises(CredentialStorageError, match="keyring is required"):
        CredentialStore(namespace="missing-keyring")


def test_credential_store_save_raises_storage_error_on_save_failure(monkeypatch):
    """Storage failures in save() should be wrapped as CredentialStorageError."""
    store = CredentialStore(namespace="test-save-error")
    monkeypatch.setattr(keyring, "set_password", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    with pytest.raises(CredentialStorageError, match="Failed to save"):
        store.save(CredentialConfig(method=AuthMethod.INTERACTIVE, tenant_id="tenant-123"))


def test_credential_store_load_raises_storage_error_on_load_failure(monkeypatch):
    """Storage failures in load() should be wrapped as CredentialStorageError."""
    store = CredentialStore(namespace="test-load-error")
    monkeypatch.setattr(keyring, "get_password", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    with pytest.raises(CredentialStorageError, match="Failed to load"):
        store.load()


def test_credential_store_delete_raises_storage_error_on_generic_failure(monkeypatch):
    """Unexpected delete failures should propagate as CredentialStorageError."""
    store = CredentialStore(namespace="test-delete-error")
    monkeypatch.setattr(keyring, "delete_password", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    with pytest.raises(CredentialStorageError, match="Failed to delete"):
        store.delete()
