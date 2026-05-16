"""
pql_test.auth package — Authentication management for pql-test.

This package provides:
- Secure credential storage using platform keyring
- Token acquisition via azure.identity
- Support for multiple authentication methods (interactive, service principal, managed identity)
- Backward compatibility with environment variables and CLI flags
"""

from __future__ import annotations

from pql_test.auth.cloud_config import CloudConfig
from pql_test.auth.exceptions import (
    AuthenticationError,
    CredentialConfigError,
    CredentialStorageError,
    TokenAcquisitionError,
)
from pql_test.auth.factory import CredentialFactory
from pql_test.auth.manager import AuthenticationManager
from pql_test.auth.models import AuthMethod, AuthStatus, CredentialConfig
from pql_test.auth.store import CredentialStore

__all__ = [
    "AuthenticationManager",
    "CredentialConfig",
    "AuthStatus",
    "AuthMethod",
    "CloudConfig",
    "CredentialStore",
    "CredentialFactory",
    "AuthenticationError",
    "CredentialStorageError",
    "TokenAcquisitionError",
    "CredentialConfigError",
]
