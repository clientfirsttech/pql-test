"""
Exceptions for authentication operations.
"""

from __future__ import annotations


class AuthenticationError(Exception):
    """Base class for authentication errors."""



class CredentialStorageError(AuthenticationError):
    """Error storing or retrieving credentials from keyring."""



class TokenAcquisitionError(AuthenticationError):
    """Error acquiring access token from Azure AD."""



class CredentialConfigError(AuthenticationError):
    """Invalid credential configuration."""

