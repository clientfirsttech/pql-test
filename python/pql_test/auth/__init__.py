"""
pql_test.auth package — Authentication management for pql-test.

This package provides:
- Secure credential storage using platform keyring
- Token acquisition via azure.identity
- Support for multiple authentication methods (interactive, service principal, managed identity)
- Backward compatibility with environment variables and CLI flags
"""

from __future__ import annotations

__all__ = [
    "AuthenticationManager",
    "CredentialConfig",
    "AuthStatus",
    "AuthMethod",
    "AuthenticationError",
    "CredentialStorageError",
    "TokenAcquisitionError",
    "CredentialConfigError",
]

# Imports will be added as modules are implemented
