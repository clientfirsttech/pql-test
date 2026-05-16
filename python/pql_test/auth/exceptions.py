"""
Exceptions for authentication operations.
"""

from __future__ import annotations


class AuthenticationError(Exception):
    """Base class for authentication errors."""

    pass


class CredentialStorageError(AuthenticationError):
    """Error storing or retrieving credentials from keyring."""

    pass


class TokenAcquisitionError(AuthenticationError):
    """Error acquiring access token from Azure AD."""

    pass


class CredentialConfigError(AuthenticationError):
    """Invalid credential configuration."""

    pass
