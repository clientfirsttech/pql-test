"""Tests for the auth CLI commands."""

import argparse
from unittest.mock import MagicMock, patch

import pytest

from pql_test.commands.auth import add_auth_parser, handle_auth
from pql_test.core import constants as con
from pql_test.core.auth import AuthError, PqlAuth


def _make_args(**kwargs) -> argparse.Namespace:
    """Helper to build a Namespace with defaults."""
    defaults = {
        "command": "auth",
        "auth_command": None,
        "username": None,
        "password": None,
        "tenant": None,
        "identity": False,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


class TestAddAuthParser:
    """Tests for CLI parser registration."""

    def test_auth_subcommand_is_registered(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        add_auth_parser(subparsers)

        args = parser.parse_args(["auth", "login"])
        assert args.command == "auth"
        assert args.auth_command == "login"

    def test_login_accepts_username_password_tenant(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        add_auth_parser(subparsers)

        args = parser.parse_args([
            "auth", "login",
            "-u", "my-client-id",
            "-p", "my-secret",
            "-t", "my-tenant",
        ])
        assert args.username == "my-client-id"
        assert args.password == "my-secret"
        assert args.tenant == "my-tenant"

    def test_login_accepts_identity_flag(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        add_auth_parser(subparsers)

        args = parser.parse_args(["auth", "login", "--identity"])
        assert args.identity is True

    def test_logout_subcommand(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        add_auth_parser(subparsers)

        args = parser.parse_args(["auth", "logout"])
        assert args.auth_command == "logout"

    def test_status_subcommand(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        add_auth_parser(subparsers)

        args = parser.parse_args(["auth", "status"])
        assert args.auth_command == "status"


class TestHandleAuthLogin:
    """Tests for the login command handler."""

    def test_interactive_login_success(self, auth):
        with patch.object(auth, "login_user") as mock_login:
            mock_login.return_value = {"access_token": "tok"}
            args = _make_args(auth_command="login")
            exit_code = handle_auth(args, auth=auth)

        assert exit_code == 0
        mock_login.assert_called_once_with(tenant=None)

    def test_interactive_login_with_tenant(self, auth):
        with patch.object(auth, "login_user") as mock_login:
            mock_login.return_value = {"access_token": "tok"}
            args = _make_args(auth_command="login", tenant="my-tenant")
            exit_code = handle_auth(args, auth=auth)

        assert exit_code == 0
        mock_login.assert_called_once_with(tenant="my-tenant")

    def test_spn_login_success(self, auth):
        with patch.object(auth, "login_service_principal") as mock_login:
            mock_login.return_value = {"access_token": "tok"}
            args = _make_args(
                auth_command="login",
                username="client-id",
                password="secret",
                tenant="tenant-id",
            )
            exit_code = handle_auth(args, auth=auth)

        assert exit_code == 0
        mock_login.assert_called_once_with(
            client_id="client-id",
            client_secret="secret",
            tenant="tenant-id",
        )

    def test_spn_login_missing_tenant(self, auth, capsys):
        args = _make_args(
            auth_command="login",
            username="client-id",
            password="secret",
            tenant=None,
        )
        exit_code = handle_auth(args, auth=auth)

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "--tenant/-t is required" in captured.err

    def test_username_without_password(self, auth, capsys):
        args = _make_args(
            auth_command="login",
            username="client-id",
            password=None,
        )
        exit_code = handle_auth(args, auth=auth)

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "--password/-p is required" in captured.err

    def test_managed_identity_login_success(self, auth):
        with patch.object(auth, "login_managed_identity") as mock_login:
            mock_login.return_value = {"access_token": "mi-tok"}
            args = _make_args(auth_command="login", identity=True)
            exit_code = handle_auth(args, auth=auth)

        assert exit_code == 0
        mock_login.assert_called_once_with(client_id=None)

    def test_managed_identity_with_client_id(self, auth):
        with patch.object(auth, "login_managed_identity") as mock_login:
            mock_login.return_value = {"access_token": "mi-tok"}
            args = _make_args(
                auth_command="login",
                identity=True,
                username="user-mi-id",
            )
            exit_code = handle_auth(args, auth=auth)

        assert exit_code == 0
        mock_login.assert_called_once_with(client_id="user-mi-id")

    def test_login_auth_error(self, auth, capsys):
        with patch.object(auth, "login_user") as mock_login:
            mock_login.side_effect = AuthError("Token expired")
            args = _make_args(auth_command="login")
            exit_code = handle_auth(args, auth=auth)

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "Token expired" in captured.err


class TestHandleAuthLogout:
    """Tests for the logout command handler."""

    def test_logout_success(self, auth, capsys):
        with patch.object(auth, "logout") as mock_logout:
            args = _make_args(auth_command="logout")
            exit_code = handle_auth(args, auth=auth)

        assert exit_code == 0
        mock_logout.assert_called_once()
        captured = capsys.readouterr()
        assert "Logged out" in captured.out


class TestHandleAuthStatus:
    """Tests for the status command handler."""

    def test_status_not_logged_in(self, auth, capsys):
        args = _make_args(auth_command="status")
        exit_code = handle_auth(args, auth=auth)

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Not logged in" in captured.out

    def test_status_logged_in_user(self, auth, capsys):
        auth._auth_info = {
            con.IDENTITY_TYPE: con.IDENTITY_TYPE_USER,
            con.TENANT_ID: "t-123",
        }

        args = _make_args(auth_command="status")
        exit_code = handle_auth(args, auth=auth)

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Logged in: Yes" in captured.out
        assert "user" in captured.out
        assert "t-123" in captured.out

    def test_status_logged_in_spn(self, auth, capsys):
        auth._auth_info = {
            con.IDENTITY_TYPE: con.IDENTITY_TYPE_SERVICE_PRINCIPAL,
            con.TENANT_ID: "spn-tenant",
            con.CLIENT_ID: "spn-client-id",
        }

        args = _make_args(auth_command="status")
        exit_code = handle_auth(args, auth=auth)

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "service_principal" in captured.out
        assert "spn-client-id" in captured.out

    def test_status_logged_in_managed_identity(self, auth, capsys):
        auth._auth_info = {
            con.IDENTITY_TYPE: con.IDENTITY_TYPE_MANAGED_IDENTITY,
            con.CLIENT_ID: "mi-id",
        }

        args = _make_args(auth_command="status")
        exit_code = handle_auth(args, auth=auth)

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "managed_identity" in captured.out


class TestHandleAuthNoSubcommand:
    """Tests for auth with missing subcommand."""

    def test_no_subcommand_shows_usage(self, auth, capsys):
        args = _make_args(auth_command=None)
        exit_code = handle_auth(args, auth=auth)

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "Usage:" in captured.err


class TestMainCli:
    """Tests for the top-level CLI entry point."""

    def test_version_flag(self, capsys):
        from pql_test.main import main

        with pytest.raises(SystemExit) as exc_info:
            main(["--version"])
        assert exc_info.value.code == 0

    def test_no_args_shows_help(self, capsys):
        from pql_test.main import main

        exit_code = main([])
        assert exit_code == 0

    def test_auth_command_dispatches(self):
        from pql_test.main import main

        with patch("pql_test.main.handle_auth", return_value=0) as mock:
            exit_code = main(["auth", "logout"])
        assert exit_code == 0
        mock.assert_called_once()
