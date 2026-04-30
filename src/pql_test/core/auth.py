"""Core authentication module for pql-test.

Supports user (interactive), service principal, and managed identity authentication
following the same patterns as the Microsoft Fabric CLI.
"""

import json
import os
from typing import Any, Optional

import msal

from pql_test.core import constants as con


class AuthError(Exception):
    """Raised when authentication fails."""

    def __init__(self, message: str, error_code: str = con.ERROR_AUTHENTICATION_FAILED):
        self.message = message
        self.error_code = error_code
        super().__init__(self.message)


class PqlAuth:
    """Handles authentication for pql-test CLI.

    Supports three identity types:
    - user: Interactive browser-based login via MSAL
    - service_principal: Client ID + secret authentication
    - managed_identity: Azure managed identity authentication
    """

    def __init__(self, config_dir: Optional[str] = None):
        if config_dir is None:
            config_dir = os.path.join(os.path.expanduser("~"), ".pql-test")
        self._config_dir = config_dir
        self._auth_file = os.path.join(self._config_dir, "auth.json")
        self._auth_info: dict[str, Any] = {}
        self._app: Optional[msal.ClientApplication] = None
        self._load_auth()

    def _ensure_config_dir(self) -> None:
        os.makedirs(self._config_dir, exist_ok=True)

    def _save_auth(self) -> None:
        self._ensure_config_dir()
        with open(self._auth_file, "w") as f:
            json.dump(self._auth_info, f)

    def _load_auth(self) -> None:
        if os.path.exists(self._auth_file) and os.stat(self._auth_file).st_size != 0:
            with open(self._auth_file, "r") as f:
                self._auth_info = json.load(f)
        else:
            self._auth_info = {}

    @property
    def identity_type(self) -> Optional[str]:
        return self._auth_info.get(con.IDENTITY_TYPE)

    @property
    def is_logged_in(self) -> bool:
        return con.IDENTITY_TYPE in self._auth_info

    def login_user(self, tenant: Optional[str] = None) -> dict[str, Any]:
        """Perform interactive browser-based user login.

        Args:
            tenant: Optional tenant ID. If not provided, uses 'common'.

        Returns:
            Token result dict from MSAL.

        Raises:
            AuthError: If authentication fails.
        """
        authority = (
            con.AUTH_TENANT_AUTHORITY + tenant
            if tenant
            else con.AUTH_DEFAULT_AUTHORITY
        )

        app = msal.PublicClientApplication(
            con.AUTH_DEFAULT_CLIENT_ID,
            authority=authority,
        )
        self._app = app

        result = app.acquire_token_interactive(
            scopes=con.SCOPE_FABRIC_DEFAULT,
        )

        if "access_token" not in result:
            error_desc = result.get("error_description", "Unknown error")
            raise AuthError(
                f"Interactive login failed: {error_desc}",
                con.ERROR_AUTHENTICATION_FAILED,
            )

        self._auth_info = {
            con.IDENTITY_TYPE: con.IDENTITY_TYPE_USER,
            con.TENANT_ID: tenant or result.get("id_token_claims", {}).get("tid", ""),
        }
        self._save_auth()
        return result

    def login_service_principal(
        self, client_id: str, client_secret: str, tenant: str
    ) -> dict[str, Any]:
        """Authenticate using a service principal with a client secret.

        Args:
            client_id: The application (client) ID.
            client_secret: The client secret.
            tenant: The tenant ID.

        Returns:
            Token result dict from MSAL.

        Raises:
            AuthError: If any required parameter is missing or authentication fails.
        """
        if not client_id or not client_secret or not tenant:
            raise AuthError(
                "client_id, client_secret, and tenant are all required "
                "for service principal authentication.",
                con.ERROR_INVALID_INPUT,
            )

        authority = con.AUTH_TENANT_AUTHORITY + tenant

        app = msal.ConfidentialClientApplication(
            client_id,
            authority=authority,
            client_credential=client_secret,
        )
        self._app = app

        result = app.acquire_token_for_client(
            scopes=con.SCOPE_FABRIC_DEFAULT,
        )

        if "access_token" not in result:
            error_desc = result.get("error_description", "Unknown error")
            raise AuthError(
                f"Service principal login failed: {error_desc}",
                con.ERROR_AUTHENTICATION_FAILED,
            )

        self._auth_info = {
            con.IDENTITY_TYPE: con.IDENTITY_TYPE_SERVICE_PRINCIPAL,
            con.TENANT_ID: tenant,
            con.CLIENT_ID: client_id,
        }
        self._save_auth()
        return result

    def login_managed_identity(
        self, client_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Authenticate using a managed identity.

        Args:
            client_id: Optional client ID for user-assigned managed identity.
                If not provided, system-assigned managed identity is used.

        Returns:
            Token result dict from MSAL.

        Raises:
            AuthError: If authentication fails.
        """
        managed_identity: msal.ManagedIdentity
        if client_id:
            managed_identity = msal.UserAssignedManagedIdentity(
                client_id=client_id,
            )
        else:
            managed_identity = msal.SystemAssignedManagedIdentity()

        app = msal.ManagedIdentityClient(
            managed_identity,
            http_client=msal.ManagedIdentityClient.get_managed_identity_source(),
        )
        self._app = app

        result = app.acquire_token_for_client(
            resource="https://api.fabric.microsoft.com",
        )

        if "access_token" not in result:
            error_desc = result.get("error_description", "Unknown error")
            raise AuthError(
                f"Managed identity login failed: {error_desc}",
                con.ERROR_AUTHENTICATION_FAILED,
            )

        self._auth_info = {
            con.IDENTITY_TYPE: con.IDENTITY_TYPE_MANAGED_IDENTITY,
            con.CLIENT_ID: client_id or "",
        }
        self._save_auth()
        return result

    def logout(self) -> None:
        """Clear all auth state and remove persisted auth file."""
        self._auth_info = {}
        self._app = None
        if os.path.exists(self._auth_file):
            os.remove(self._auth_file)

    def status(self) -> dict[str, Any]:
        """Return current authentication status.

        Returns:
            Dict with login status, identity type, and related info.
        """
        if not self.is_logged_in:
            return {
                "logged_in": False,
                "identity_type": None,
                "tenant_id": None,
                "client_id": None,
            }

        return {
            "logged_in": True,
            "identity_type": self._auth_info.get(con.IDENTITY_TYPE),
            "tenant_id": self._auth_info.get(con.TENANT_ID),
            "client_id": self._auth_info.get(con.CLIENT_ID),
        }
