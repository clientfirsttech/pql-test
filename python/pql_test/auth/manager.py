"""
Authentication manager — Main interface for authentication operations.
"""

from __future__ import annotations

from typing import Optional

try:
    from azure.core.credentials import TokenCredential
except ImportError:
    TokenCredential = None  # type: ignore

from pql_test.auth.cloud_config import CloudConfig
from pql_test.auth.exceptions import TokenAcquisitionError
from pql_test.auth.factory import CredentialFactory
from pql_test.auth.models import AuthStatus, CredentialConfig
from pql_test.auth.store import CredentialStore


class AuthenticationManager:
    """
    Manages authentication for pql-test.

    Handles credential storage, token acquisition, and authentication state.
    Provides a unified interface for all authentication methods.
    """

    def __init__(self, namespace: str = "pql-test"):
        """
        Initialize authentication manager.

        Args:
            namespace: Keyring namespace for credential storage
        """
        self._store = CredentialStore(namespace)
        self._factory = CredentialFactory()
        self._cloud_config = CloudConfig()

    def save_credential(self, config: CredentialConfig) -> None:
        """
        Save credential configuration to secure storage.

        Args:
            config: Credential configuration to store

        Raises:
            CredentialStorageError: If credential cannot be stored
        """
        self._store.save(config)

    def get_credential(self) -> Optional[TokenCredential]:
        """
        Get credential from stored configuration.

        Returns:
            TokenCredential instance or None if not authenticated

        Raises:
            CredentialConfigError: If stored config is invalid
        """
        config = self._store.load()
        if config is None:
            return None

        return self._factory.create(config, self._cloud_config)

    def get_access_token(
        self, scope: str = "https://analysis.windows.net/powerbi/api/.default"
    ) -> Optional[str]:
        """
        Get access token for the given scope.

        Args:
            scope: OAuth2 scope for the token

        Returns:
            Access token string or None if not authenticated

        Raises:
            TokenAcquisitionError: If token acquisition fails
        """
        credential = self.get_credential()
        if credential is None:
            return None

        try:
            token_result = credential.get_token(scope)
            return token_result.token
        except Exception as e:
            raise TokenAcquisitionError(
                f"Failed to acquire access token: {e}"
            ) from e

    def clear_credential(self) -> None:
        """
        Clear stored credential configuration.

        Raises:
            CredentialStorageError: If credential cannot be cleared
        """
        self._store.delete()

    def get_status(self) -> AuthStatus:
        """
        Get current authentication status.

        Returns:
            AuthStatus with current authentication state
        """
        config = self._store.load()

        if config is None:
            return AuthStatus(authenticated=False)

        return AuthStatus(
            authenticated=True,
            method=config.method,
            account_name=config.account_name,
            tenant_id=config.tenant_id,
            client_id=config.client_id,
            environment=config.environment,
            token_is_valid=False,  # TODO: Implement token validation
        )
