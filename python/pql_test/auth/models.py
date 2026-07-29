"""
Data models for authentication configuration and status.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class AuthMethod(Enum):
    """Supported authentication methods."""

    INTERACTIVE = "interactive"
    SERVICE_PRINCIPAL_SECRET = "service_principal_secret"
    SERVICE_PRINCIPAL_CERT = "service_principal_cert"
    SERVICE_PRINCIPAL_FEDERATED = "service_principal_federated"
    MANAGED_IDENTITY = "managed_identity"


@dataclass
class CredentialConfig:
    """
    Credential configuration stored in keyring.

    Attributes:
        method: Authentication method
        tenant_id: Azure AD tenant ID (optional for some methods)
        client_id: Client/application ID
        client_secret: Client secret (service principal with secret only)
        certificate_path: Path to certificate file (certificate auth only)
        certificate_password: Certificate password (encrypted cert only)
        federated_token: Federated credential token (federated auth only)
        use_system_assigned_identity: Use system-assigned managed identity
        environment: Cloud environment (Public, USGov, etc.)
        account_name: Display name for status output
    """

    method: AuthMethod
    tenant_id: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    certificate_path: Optional[str] = None
    certificate_password: Optional[str] = None
    federated_token: Optional[str] = None
    use_system_assigned_identity: bool = False
    environment: str = "Public"
    account_name: Optional[str] = None
    # Serialized azure-identity AuthenticationRecord (JSON) — captured on
    # interactive sign-in and replayed on subsequent runs so the persistent
    # MSAL token cache can be looked up silently instead of triggering a
    # fresh browser flow. Only populated for AuthMethod.INTERACTIVE.
    authentication_record_json: Optional[str] = None

    def to_dict(self) -> dict:
        """
        Serialize to dictionary.

        Returns:
            Dictionary representation with AuthMethod converted to string
        """
        data = asdict(self)
        data["method"] = self.method.value
        return data

    def to_json(self) -> str:
        """
        Serialize to JSON string.

        Returns:
            JSON string representation
        """
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict) -> CredentialConfig:
        """
        Deserialize from dictionary.

        Args:
            data: Dictionary representation

        Returns:
            CredentialConfig instance
        """
        # Convert method string to enum
        if "method" in data and isinstance(data["method"], str):
            data = data.copy()
            data["method"] = AuthMethod(data["method"])
        return cls(**data)

    @classmethod
    def from_json(cls, json_str: str) -> CredentialConfig:
        """
        Deserialize from JSON string.

        Args:
            json_str: JSON string representation

        Returns:
            CredentialConfig instance
        """
        data = json.loads(json_str)
        return cls.from_dict(data)


@dataclass
class AuthStatus:
    """
    Current authentication status.

    Attributes:
        authenticated: Whether user is authenticated
        method: Authentication method used (if authenticated)
        account_name: Display name of authenticated account
        tenant_id: Azure AD tenant ID
        client_id: Client/application ID
        environment: Cloud environment
        token_expires_at: Token expiration timestamp
        token_is_valid: Whether token is currently valid (not expired)
    """

    authenticated: bool
    method: Optional[AuthMethod] = None
    account_name: Optional[str] = None
    tenant_id: Optional[str] = None
    client_id: Optional[str] = None
    environment: str = "Public"
    token_expires_at: Optional[datetime] = None
    token_is_valid: bool = False
