# SPDX-License-Identifier: BUSL-1.1
"""
Tests for the ``pql-test auth`` CLI subcommands — branch coverage.

Focus: the routing branches in [python/pql_test/cli.py](../pql_test/cli.py)
for ``auth login``, ``auth logout``, and ``auth status`` that were not
already covered by [python/tests/auth/test_auth_login_cmd.py](test_auth_login_cmd.py).

These tests are pure unit tests — no keyring backend, no MSAL calls, no
browser.  Every credential factory / manager touchpoint is mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import keyring
import pytest
from click.testing import CliRunner

from pql_test import cli as cli_module
from pql_test.auth.manager import AuthenticationManager
from pql_test.auth.models import AuthMethod, AuthStatus, CredentialConfig
from tests.auth.test_store import MockKeyring


@pytest.fixture(autouse=True)
def use_mock_keyring():
    """In-memory keyring for every test in this module."""
    original = keyring.get_keyring()
    keyring.set_keyring(MockKeyring())
    yield
    keyring.set_keyring(original)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# auth login — flag-driven routing branches
# ---------------------------------------------------------------------------


class TestAuthLoginRouting:
    """Cover the elif ladder in cmd_auth_login that picks a CredentialConfig."""

    def test_federated_without_user_or_tenant_errors_and_exits_1(self, runner):
        result = runner.invoke(
            cli_module.cli,
            ["auth", "login", "--federated-token", "tok"],
        )
        assert result.exit_code == 1
        assert "Federated credential requires --user" in result.output

    def test_certificate_without_user_or_tenant_errors_and_exits_1(self, runner, tmp_path):
        cert = tmp_path / "cert.pem"
        cert.write_text("-----BEGIN CERTIFICATE-----\nnot real\n-----END CERTIFICATE-----\n")
        result = runner.invoke(
            cli_module.cli,
            ["auth", "login", "--certificate", str(cert)],
        )
        assert result.exit_code == 1
        assert "Certificate auth requires --user" in result.output

    def test_spn_secret_without_tenant_errors_and_exits_1(self, runner):
        result = runner.invoke(
            cli_module.cli,
            ["auth", "login", "-u", "client-id", "-p", "secret"],
        )
        assert result.exit_code == 1
        assert "Service principal auth requires --tenant" in result.output

    def test_managed_identity_system_assigned_saves_credential(self, runner):
        fake_credential = MagicMock(spec=["get_token"])
        fake_credential.get_token.return_value = MagicMock(token="tok")
        with patch(
            "pql_test.auth.factory.CredentialFactory.create",
            return_value=fake_credential,
        ):
            result = runner.invoke(cli_module.cli, ["auth", "login", "--identity"])
        assert result.exit_code == 0, result.output
        saved = AuthenticationManager()._store.load()
        assert saved is not None
        assert saved.method == AuthMethod.MANAGED_IDENTITY
        assert saved.use_system_assigned_identity is True
        assert saved.client_id is None

    def test_managed_identity_user_assigned_uses_supplied_client_id(self, runner):
        fake_credential = MagicMock(spec=["get_token"])
        fake_credential.get_token.return_value = MagicMock(token="tok")
        with patch(
            "pql_test.auth.factory.CredentialFactory.create",
            return_value=fake_credential,
        ):
            result = runner.invoke(
                cli_module.cli,
                ["auth", "login", "--identity", "-u", "user-mi-client-id"],
            )
        assert result.exit_code == 0, result.output
        saved = AuthenticationManager()._store.load()
        assert saved is not None
        assert saved.method == AuthMethod.MANAGED_IDENTITY
        assert saved.client_id == "user-mi-client-id"
        assert saved.use_system_assigned_identity is False

    def test_federated_happy_path_saves_credential(self, runner):
        fake_credential = MagicMock(spec=["get_token"])
        fake_credential.get_token.return_value = MagicMock(token="tok")
        with patch(
            "pql_test.auth.factory.CredentialFactory.create",
            return_value=fake_credential,
        ):
            result = runner.invoke(
                cli_module.cli,
                [
                    "auth", "login",
                    "-u", "fed-client-id",
                    "--tenant", "fed-tenant",
                    "--federated-token", "eyJraWQ.fake",
                ],
            )
        assert result.exit_code == 0, result.output
        saved = AuthenticationManager()._store.load()
        assert saved is not None
        assert saved.method == AuthMethod.SERVICE_PRINCIPAL_FEDERATED
        assert saved.federated_token == "eyJraWQ.fake"

    def test_certificate_happy_path_saves_credential(self, runner, tmp_path):
        cert = tmp_path / "cert.pem"
        cert.write_text("-----BEGIN CERTIFICATE-----\nx\n-----END CERTIFICATE-----\n")
        fake_credential = MagicMock(spec=["get_token"])
        fake_credential.get_token.return_value = MagicMock(token="tok")
        with patch(
            "pql_test.auth.factory.CredentialFactory.create",
            return_value=fake_credential,
        ):
            result = runner.invoke(
                cli_module.cli,
                [
                    "auth", "login",
                    "-u", "cert-client-id",
                    "--tenant", "cert-tenant",
                    "--certificate", str(cert),
                    "-p", "cert-password",
                ],
            )
        assert result.exit_code == 0, result.output
        saved = AuthenticationManager()._store.load()
        assert saved is not None
        assert saved.method == AuthMethod.SERVICE_PRINCIPAL_CERT
        assert saved.certificate_path == str(cert)
        assert saved.certificate_password == "cert-password"

    def test_menu_option_2_prompts_for_spn_details(self, runner):
        """Fully-interactive menu, choose option 2 → prompt tenant, client, secret."""
        fake_credential = MagicMock(spec=["get_token"])
        fake_credential.get_token.return_value = MagicMock(token="tok")
        with patch(
            "pql_test.auth.factory.CredentialFactory.create",
            return_value=fake_credential,
        ):
            # Feed: menu=2, tenant, client, secret
            result = runner.invoke(
                cli_module.cli,
                ["auth", "login"],
                input="2\nprompted-tenant\nprompted-client\nprompted-secret\n",
            )
        assert result.exit_code == 0, result.output
        saved = AuthenticationManager()._store.load()
        assert saved is not None
        assert saved.method == AuthMethod.SERVICE_PRINCIPAL_SECRET
        assert saved.tenant_id == "prompted-tenant"
        assert saved.client_id == "prompted-client"
        assert saved.client_secret == "prompted-secret"

    def test_partial_flags_fall_through_to_interactive_browser(self, runner):
        """When -u is provided but neither -p nor --certificate/--federated-token,
        the branch falls through to the interactive-browser fallback (no menu)."""
        fake_credential = MagicMock(spec=["get_token"])
        # No `authenticate` attr → matches the non-INTERACTIVE hasattr branch,
        # even though method is INTERACTIVE — this is the corner the cli hits
        # when the credential type doesn't support authenticate().
        fake_credential.get_token.return_value = MagicMock(token="tok")
        with patch(
            "pql_test.auth.factory.CredentialFactory.create",
            return_value=fake_credential,
        ):
            result = runner.invoke(
                cli_module.cli,
                ["auth", "login", "-u", "some-user"],
            )
        assert result.exit_code == 0, result.output
        saved = AuthenticationManager()._store.load()
        assert saved is not None
        assert saved.method == AuthMethod.INTERACTIVE

    def test_authentication_exception_prints_error_and_exits_1(self, runner):
        """Any exception from credential.get_token() / authenticate() is caught
        and reported with exit code 1 (not a raw traceback)."""
        fake_credential = MagicMock(spec=["get_token"])
        fake_credential.get_token.side_effect = RuntimeError("AADSTS7000215: bad secret")
        with patch(
            "pql_test.auth.factory.CredentialFactory.create",
            return_value=fake_credential,
        ):
            result = runner.invoke(
                cli_module.cli,
                [
                    "auth", "login",
                    "-u", "c", "-p", "s", "--tenant", "t",
                ],
            )
        assert result.exit_code == 1
        assert "Authentication failed" in result.output
        assert "AADSTS7000215" in result.output


# ---------------------------------------------------------------------------
# auth logout
# ---------------------------------------------------------------------------


class TestAuthLogout:
    def test_logout_when_not_authenticated_reports_and_returns(self, runner):
        with patch(
            "pql_test.auth.manager.AuthenticationManager.get_status",
            return_value=AuthStatus(authenticated=False),
        ):
            result = runner.invoke(cli_module.cli, ["auth", "logout"])
        assert result.exit_code == 0
        assert "Not currently authenticated" in result.output

    def test_logout_when_authenticated_clears_and_confirms(self, runner):
        status = AuthStatus(
            authenticated=True,
            method=AuthMethod.SERVICE_PRINCIPAL_SECRET,
            account_name="SP c",
        )
        with (
            patch(
                "pql_test.auth.manager.AuthenticationManager.get_status",
                return_value=status,
            ),
            patch(
                "pql_test.auth.manager.AuthenticationManager.clear_credential",
            ) as clear,
        ):
            result = runner.invoke(cli_module.cli, ["auth", "logout"])
        assert result.exit_code == 0
        clear.assert_called_once()
        assert "Successfully logged out" in result.output


# ---------------------------------------------------------------------------
# auth status
# ---------------------------------------------------------------------------


class TestAuthStatus:
    def test_status_not_authenticated_prints_hint(self, runner):
        with patch(
            "pql_test.auth.manager.AuthenticationManager.get_status",
            return_value=AuthStatus(authenticated=False),
        ):
            result = runner.invoke(cli_module.cli, ["auth", "status"])
        assert result.exit_code == 0
        assert "Not authenticated" in result.output
        assert "pql-test auth login" in result.output

    def test_status_authenticated_prints_all_fields(self, runner):
        status = AuthStatus(
            authenticated=True,
            method=AuthMethod.SERVICE_PRINCIPAL_SECRET,
            account_name="SP alice",
            tenant_id="tenant-guid",
            client_id="client-guid",
            environment="Public",
        )
        with patch(
            "pql_test.auth.manager.AuthenticationManager.get_status",
            return_value=status,
        ):
            result = runner.invoke(cli_module.cli, ["auth", "status"])
        assert result.exit_code == 0
        assert "Status: Authenticated" in result.output
        assert "service_principal_secret" in result.output
        assert "SP alice" in result.output
        assert "tenant-guid" in result.output
        assert "client-guid" in result.output
        assert "Public" in result.output

    def test_status_authenticated_no_optional_fields(self, runner):
        """Only method + authenticated=True; account/tenant/client all None."""
        status = AuthStatus(
            authenticated=True,
            method=AuthMethod.MANAGED_IDENTITY,
        )
        with patch(
            "pql_test.auth.manager.AuthenticationManager.get_status",
            return_value=status,
        ):
            result = runner.invoke(cli_module.cli, ["auth", "status"])
        assert result.exit_code == 0
        assert "Status: Authenticated" in result.output
        assert "managed_identity" in result.output
        # Fields with `if status.<field>:` guards must be omitted when None
        assert "Account:" not in result.output
        assert "Tenant:" not in result.output
        assert "Client ID:" not in result.output

    def test_status_authenticated_no_method_shows_unknown(self, runner):
        """AuthStatus.method is Optional; the cli falls back to 'Unknown'."""
        status = AuthStatus(authenticated=True, method=None)
        with patch(
            "pql_test.auth.manager.AuthenticationManager.get_status",
            return_value=status,
        ):
            result = runner.invoke(cli_module.cli, ["auth", "status"])
        assert result.exit_code == 0
        assert "Method: Unknown" in result.output
