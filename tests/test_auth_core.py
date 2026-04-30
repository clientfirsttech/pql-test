"""Tests for the core auth module."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from pql_test.core import constants as con
from pql_test.core.auth import AuthError, PqlAuth


class TestPqlAuthInit:
    """Tests for PqlAuth initialization."""

    def test_creates_instance_with_default_config_dir(self):
        auth = PqlAuth()
        expected = os.path.join(os.path.expanduser("~"), ".pql-test")
        assert auth._config_dir == expected

    def test_creates_instance_with_custom_config_dir(self, tmp_config_dir):
        auth = PqlAuth(config_dir=tmp_config_dir)
        assert auth._config_dir == tmp_config_dir

    def test_loads_existing_auth_file(self, tmp_config_dir):
        auth_data = {
            con.IDENTITY_TYPE: con.IDENTITY_TYPE_USER,
            con.TENANT_ID: "test-tenant",
        }
        auth_file = os.path.join(tmp_config_dir, "auth.json")
        with open(auth_file, "w") as f:
            json.dump(auth_data, f)

        auth = PqlAuth(config_dir=tmp_config_dir)
        assert auth.identity_type == con.IDENTITY_TYPE_USER
        assert auth.is_logged_in is True

    def test_handles_empty_auth_file(self, tmp_config_dir):
        auth_file = os.path.join(tmp_config_dir, "auth.json")
        with open(auth_file, "w") as f:
            pass  # create empty file

        auth = PqlAuth(config_dir=tmp_config_dir)
        assert auth.is_logged_in is False

    def test_handles_missing_auth_file(self, tmp_config_dir):
        auth = PqlAuth(config_dir=tmp_config_dir)
        assert auth.is_logged_in is False


class TestLoginUser:
    """Tests for interactive user login."""

    @patch("pql_test.core.auth.msal.PublicClientApplication")
    def test_login_user_success(self, mock_app_class, auth):
        mock_app = MagicMock()
        mock_app.acquire_token_interactive.return_value = {
            "access_token": "test-token",
            "id_token_claims": {"tid": "discovered-tenant"},
        }
        mock_app_class.return_value = mock_app

        result = auth.login_user()

        assert result["access_token"] == "test-token"
        assert auth.is_logged_in is True
        assert auth.identity_type == con.IDENTITY_TYPE_USER
        mock_app.acquire_token_interactive.assert_called_once_with(
            scopes=con.SCOPE_FABRIC_DEFAULT,
        )

    @patch("pql_test.core.auth.msal.PublicClientApplication")
    def test_login_user_with_tenant(self, mock_app_class, auth):
        mock_app = MagicMock()
        mock_app.acquire_token_interactive.return_value = {
            "access_token": "test-token",
            "id_token_claims": {"tid": "my-tenant"},
        }
        mock_app_class.return_value = mock_app

        auth.login_user(tenant="my-tenant")

        mock_app_class.assert_called_once_with(
            con.AUTH_DEFAULT_CLIENT_ID,
            authority=con.AUTH_TENANT_AUTHORITY + "my-tenant",
        )

    @patch("pql_test.core.auth.msal.PublicClientApplication")
    def test_login_user_uses_common_authority_when_no_tenant(self, mock_app_class, auth):
        mock_app = MagicMock()
        mock_app.acquire_token_interactive.return_value = {
            "access_token": "test-token",
            "id_token_claims": {},
        }
        mock_app_class.return_value = mock_app

        auth.login_user()

        mock_app_class.assert_called_once_with(
            con.AUTH_DEFAULT_CLIENT_ID,
            authority=con.AUTH_DEFAULT_AUTHORITY,
        )

    @patch("pql_test.core.auth.msal.PublicClientApplication")
    def test_login_user_failure_raises_auth_error(self, mock_app_class, auth):
        mock_app = MagicMock()
        mock_app.acquire_token_interactive.return_value = {
            "error": "access_denied",
            "error_description": "User cancelled",
        }
        mock_app_class.return_value = mock_app

        with pytest.raises(AuthError, match="Interactive login failed"):
            auth.login_user()

    @patch("pql_test.core.auth.msal.PublicClientApplication")
    def test_login_user_persists_auth_state(self, mock_app_class, auth):
        mock_app = MagicMock()
        mock_app.acquire_token_interactive.return_value = {
            "access_token": "persisted-token",
            "id_token_claims": {"tid": "persisted-tenant"},
        }
        mock_app_class.return_value = mock_app

        auth.login_user(tenant="persisted-tenant")

        # Reload from disk
        auth2 = PqlAuth(config_dir=auth._config_dir)
        assert auth2.is_logged_in is True
        assert auth2.identity_type == con.IDENTITY_TYPE_USER


class TestLoginServicePrincipal:
    """Tests for service principal login."""

    @patch("pql_test.core.auth.msal.ConfidentialClientApplication")
    def test_login_spn_success(self, mock_app_class, auth):
        mock_app = MagicMock()
        mock_app.acquire_token_for_client.return_value = {
            "access_token": "spn-token",
        }
        mock_app_class.return_value = mock_app

        result = auth.login_service_principal(
            client_id="app-id",
            client_secret="app-secret",
            tenant="tenant-id",
        )

        assert result["access_token"] == "spn-token"
        assert auth.identity_type == con.IDENTITY_TYPE_SERVICE_PRINCIPAL
        assert auth.status()["tenant_id"] == "tenant-id"
        assert auth.status()["client_id"] == "app-id"

    @patch("pql_test.core.auth.msal.ConfidentialClientApplication")
    def test_login_spn_creates_correct_app(self, mock_app_class, auth):
        mock_app = MagicMock()
        mock_app.acquire_token_for_client.return_value = {
            "access_token": "spn-token",
        }
        mock_app_class.return_value = mock_app

        auth.login_service_principal("app-id", "secret", "tenant-123")

        mock_app_class.assert_called_once_with(
            "app-id",
            authority=con.AUTH_TENANT_AUTHORITY + "tenant-123",
            client_credential="secret",
        )

    def test_login_spn_missing_client_id_raises(self, auth):
        with pytest.raises(AuthError, match="client_id.*required"):
            auth.login_service_principal("", "secret", "tenant")

    def test_login_spn_missing_secret_raises(self, auth):
        with pytest.raises(AuthError, match="client_secret.*required"):
            auth.login_service_principal("app-id", "", "tenant")

    def test_login_spn_missing_tenant_raises(self, auth):
        with pytest.raises(AuthError, match="tenant.*required"):
            auth.login_service_principal("app-id", "secret", "")

    @patch("pql_test.core.auth.msal.ConfidentialClientApplication")
    def test_login_spn_failure_raises_auth_error(self, mock_app_class, auth):
        mock_app = MagicMock()
        mock_app.acquire_token_for_client.return_value = {
            "error": "unauthorized_client",
            "error_description": "Bad credentials",
        }
        mock_app_class.return_value = mock_app

        with pytest.raises(AuthError, match="Service principal login failed"):
            auth.login_service_principal("app-id", "secret", "tenant")

    @patch("pql_test.core.auth.msal.ConfidentialClientApplication")
    def test_login_spn_persists_auth_state(self, mock_app_class, auth):
        mock_app = MagicMock()
        mock_app.acquire_token_for_client.return_value = {
            "access_token": "spn-token",
        }
        mock_app_class.return_value = mock_app

        auth.login_service_principal("app-id", "secret", "tenant-id")

        auth2 = PqlAuth(config_dir=auth._config_dir)
        assert auth2.is_logged_in is True
        assert auth2.identity_type == con.IDENTITY_TYPE_SERVICE_PRINCIPAL
        assert auth2.status()["client_id"] == "app-id"


class TestLoginManagedIdentity:
    """Tests for managed identity login."""

    @patch("pql_test.core.auth.msal.ManagedIdentityClient")
    @patch("pql_test.core.auth.msal.SystemAssignedManagedIdentity")
    def test_login_system_assigned_success(self, mock_sys_mi, mock_mi_client, auth):
        mock_client = MagicMock()
        mock_client.acquire_token_for_client.return_value = {
            "access_token": "mi-token",
        }
        mock_mi_client.return_value = mock_client

        result = auth.login_managed_identity()

        assert result["access_token"] == "mi-token"
        assert auth.identity_type == con.IDENTITY_TYPE_MANAGED_IDENTITY
        mock_sys_mi.assert_called_once()

    @patch("pql_test.core.auth.msal.ManagedIdentityClient")
    @patch("pql_test.core.auth.msal.UserAssignedManagedIdentity")
    def test_login_user_assigned_success(self, mock_user_mi, mock_mi_client, auth):
        mock_client = MagicMock()
        mock_client.acquire_token_for_client.return_value = {
            "access_token": "user-mi-token",
        }
        mock_mi_client.return_value = mock_client

        result = auth.login_managed_identity(client_id="user-mi-id")

        assert result["access_token"] == "user-mi-token"
        assert auth.status()["client_id"] == "user-mi-id"
        mock_user_mi.assert_called_once_with(client_id="user-mi-id")

    @patch("pql_test.core.auth.msal.ManagedIdentityClient")
    @patch("pql_test.core.auth.msal.SystemAssignedManagedIdentity")
    def test_login_managed_identity_failure(self, mock_sys_mi, mock_mi_client, auth):
        mock_client = MagicMock()
        mock_client.acquire_token_for_client.return_value = {
            "error": "failed",
            "error_description": "Not in Azure",
        }
        mock_mi_client.return_value = mock_client

        with pytest.raises(AuthError, match="Managed identity login failed"):
            auth.login_managed_identity()


class TestLogout:
    """Tests for logout."""

    def test_logout_clears_state(self, auth, tmp_config_dir):
        # Set up logged-in state
        auth._auth_info = {con.IDENTITY_TYPE: con.IDENTITY_TYPE_USER}
        auth._save_auth()
        assert auth.is_logged_in is True

        auth.logout()

        assert auth.is_logged_in is False
        assert not os.path.exists(auth._auth_file)

    def test_logout_when_not_logged_in(self, auth):
        auth.logout()
        assert auth.is_logged_in is False

    def test_logout_removes_auth_file(self, auth, tmp_config_dir):
        auth._auth_info = {con.IDENTITY_TYPE: con.IDENTITY_TYPE_USER}
        auth._save_auth()
        assert os.path.exists(auth._auth_file)

        auth.logout()
        assert not os.path.exists(auth._auth_file)


class TestStatus:
    """Tests for auth status."""

    def test_status_not_logged_in(self, auth):
        status = auth.status()
        assert status["logged_in"] is False
        assert status["identity_type"] is None

    def test_status_logged_in_as_user(self, auth):
        auth._auth_info = {
            con.IDENTITY_TYPE: con.IDENTITY_TYPE_USER,
            con.TENANT_ID: "my-tenant",
        }

        status = auth.status()
        assert status["logged_in"] is True
        assert status["identity_type"] == con.IDENTITY_TYPE_USER
        assert status["tenant_id"] == "my-tenant"

    def test_status_logged_in_as_spn(self, auth):
        auth._auth_info = {
            con.IDENTITY_TYPE: con.IDENTITY_TYPE_SERVICE_PRINCIPAL,
            con.TENANT_ID: "spn-tenant",
            con.CLIENT_ID: "spn-client",
        }

        status = auth.status()
        assert status["logged_in"] is True
        assert status["identity_type"] == con.IDENTITY_TYPE_SERVICE_PRINCIPAL
        assert status["tenant_id"] == "spn-tenant"
        assert status["client_id"] == "spn-client"

    def test_status_logged_in_as_managed_identity(self, auth):
        auth._auth_info = {
            con.IDENTITY_TYPE: con.IDENTITY_TYPE_MANAGED_IDENTITY,
            con.CLIENT_ID: "mi-client",
        }

        status = auth.status()
        assert status["logged_in"] is True
        assert status["identity_type"] == con.IDENTITY_TYPE_MANAGED_IDENTITY
        assert status["client_id"] == "mi-client"
