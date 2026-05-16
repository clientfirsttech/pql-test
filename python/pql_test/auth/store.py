"""
Secure credential storage using platform keyring.
"""

from __future__ import annotations

from typing import Optional

try:
    import keyring
    import keyring.errors
    HAS_KEYRING = True
except ImportError:
    HAS_KEYRING = False

from pql_test.auth.exceptions import CredentialStorageError
from pql_test.auth.models import CredentialConfig


class CredentialStore:
    """
    Secure credential storage using platform keyring.

    Stores credential configuration as JSON in the system keyring:
    - Windows: Windows Credential Manager
    - macOS: Keychain
    - Linux: Secret Service API (GNOME Keyring, KWallet, etc.)
    """

    def __init__(self, namespace: str = "pql-test"):
        """
        Initialize credential store.

        Args:
            namespace: Keyring namespace for credential isolation

        Raises:
            CredentialStorageError: If keyring is not available
        """
        if not HAS_KEYRING:
            raise CredentialStorageError(
                "keyring is required for credential storage. "
                "Install with: pip install keyring"
            )
        self._namespace = namespace
        self._service_name = f"pql-test-{namespace}"

    def save(self, config: CredentialConfig) -> None:
        """
        Save credential configuration to keyring.

        Args:
            config: Credential configuration to store

        Raises:
            CredentialStorageError: If save fails
        """
        try:
            config_json = config.to_json()
            keyring.set_password(self._service_name, "default", config_json)
        except Exception as e:
            raise CredentialStorageError(
                f"Failed to save credential to keyring: {e}"
            ) from e

    def load(self) -> Optional[CredentialConfig]:
        """
        Load credential configuration from keyring.

        Returns:
            CredentialConfig if found, None if no credential stored

        Raises:
            CredentialStorageError: If load fails or config is invalid
        """
        try:
            config_json = keyring.get_password(self._service_name, "default")
            if config_json is None:
                return None
            return CredentialConfig.from_json(config_json)
        except Exception as e:
            raise CredentialStorageError(
                f"Failed to load credential from keyring: {e}"
            ) from e

    def delete(self) -> None:
        """
        Delete stored credential configuration.

        Raises:
            CredentialStorageError: If delete fails (other than not found)
        """
        try:
            keyring.delete_password(self._service_name, "default")
        except keyring.errors.PasswordDeleteError:
            # Credential not found — this is fine
            pass
        except Exception as e:
            raise CredentialStorageError(
                f"Failed to delete credential from keyring: {e}"
            ) from e
