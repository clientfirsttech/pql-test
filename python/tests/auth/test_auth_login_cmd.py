# SPDX-License-Identifier: AGPL-3.0-only
"""
Tests for ``pql-test auth login`` — specifically the
``AuthenticationRecord`` capture-and-store path added by
tasks/surface-silent-test-discovery-failures-epic.md.

Without these tests, a future refactor could quietly stop saving the
record after a successful interactive sign-in, returning the project to
the "browser pop on every CLI invocation" UX failure that triggered the
unified-auth iteration.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import keyring
import pytest
from click.testing import CliRunner

from pql_test.auth.manager import AuthenticationManager
from pql_test.auth.models import AuthMethod, CredentialConfig
from tests.auth.test_store import MockKeyring


@pytest.fixture(autouse=True)
def use_mock_keyring():
    """In-memory keyring for these tests."""
    original = keyring.get_keyring()
    keyring.set_keyring(MockKeyring())
    yield
    keyring.set_keyring(original)


def test_cmd_auth_login_interactive_stores_authentication_record(monkeypatch):
    """Given a successful interactive sign-in, cmd_auth_login must call
    credential.authenticate(scopes=[...]) to capture an AuthenticationRecord,
    serialize it, and store it on the saved CredentialConfig.

    Without this, the factory's record-replay path never finds anything
    to replay and we're back to "browser pop on every CLI invocation."
    """
    from azure.identity import AuthenticationRecord
    from pql_test import cli as cli_module

    real_record = AuthenticationRecord(
        tenant_id="t-from-record",
        client_id="c-from-record",
        authority="login.microsoftonline.com",
        home_account_id="home.acct",
        username="captured-user@example.com",
    )

    fake_credential = MagicMock()
    fake_credential.authenticate.return_value = real_record

    with patch(
        "pql_test.auth.factory.CredentialFactory.create",
        return_value=fake_credential,
    ):
            runner = CliRunner()
            # Choose menu option 1 (interactive) — feed via stdin.
            result = runner.invoke(cli_module.cli, ["auth", "login"], input="1\n")

    assert result.exit_code == 0, f"auth login failed: {result.output}"

    # The factory must have been told to use INTERACTIVE auth.
    fake_credential.authenticate.assert_called_once()
    # And the saved config must carry the serialized record.
    saved = AuthenticationManager()._store.load()
    assert saved is not None
    assert saved.method == AuthMethod.INTERACTIVE
    assert saved.authentication_record_json is not None, (
        "cmd_auth_login must serialize the captured AuthenticationRecord "
        "into config.authentication_record_json so subsequent runs can "
        "replay it through the factory and reuse the cached token. See "
        "tasks/surface-silent-test-discovery-failures-epic.md."
    )
    # And the record should round-trip.
    replayed = AuthenticationRecord.deserialize(saved.authentication_record_json)
    assert replayed.username == "captured-user@example.com"
    assert replayed.home_account_id == "home.acct"


def test_cmd_auth_login_interactive_updates_account_name_from_record():
    """The placeholder "Interactive User" account name from the menu prompt
    must be replaced with the real username from the AuthenticationRecord.
    This is how `pql-test auth status` shows the user's real identity."""
    from azure.identity import AuthenticationRecord
    from pql_test import cli as cli_module

    real_record = AuthenticationRecord(
        tenant_id="t",
        client_id="c",
        authority="login.microsoftonline.com",
        home_account_id="home.acct",
        username="alice@contoso.com",
    )
    fake_credential = MagicMock()
    fake_credential.authenticate.return_value = real_record

    with patch(
        "pql_test.auth.factory.CredentialFactory.create",
        return_value=fake_credential,
    ):
        runner = CliRunner()
        result = runner.invoke(cli_module.cli, ["auth", "login"], input="1\n")

    assert result.exit_code == 0
    saved = AuthenticationManager()._store.load()
    assert saved is not None
    assert saved.account_name == "alice@contoso.com", (
        "account_name should be derived from AuthenticationRecord.username, "
        f"not the 'Interactive User' placeholder; got {saved.account_name!r}"
    )


def test_cmd_auth_login_non_interactive_does_not_call_authenticate():
    """SPN-secret and other non-interactive flows must use get_token(),
    not authenticate() — authenticate() is specific to
    InteractiveBrowserCredential and would pop a browser if it existed
    on a confidential credential.

    Regression guard: prevents a future refactor from blindly applying the
    authenticate() path to all credential types.
    """
    from pql_test import cli as cli_module

    # SPN-secret credential has get_token() but historically lacks
    # authenticate().  We assert authenticate() is NOT called.
    fake_credential = MagicMock(spec=["get_token"])  # no `authenticate` attr
    fake_token = MagicMock(token="fake-spn-bearer")
    fake_credential.get_token.return_value = fake_token

    with patch(
        "pql_test.auth.factory.CredentialFactory.create",
        return_value=fake_credential,
    ):
        runner = CliRunner()
        result = runner.invoke(
            cli_module.cli,
            [
                "auth", "login",
                "-u", "00000000-0000-0000-0000-000000000001",
                "-p", "secret",
                "--tenant", "00000000-0000-0000-0000-000000000002",
            ],
        )

    assert result.exit_code == 0, f"auth login failed: {result.output}"
    # get_token was called…
    fake_credential.get_token.assert_called_once()
    # …and the saved config is SPN-secret, NOT interactive — so no record.
    saved = AuthenticationManager()._store.load()
    assert saved is not None
    assert saved.method == AuthMethod.SERVICE_PRINCIPAL_SECRET
    assert saved.authentication_record_json is None, (
        "SPN-secret flow must not store an authentication_record_json — "
        "that field is only meaningful for InteractiveBrowserCredential."
    )


def test_cmd_auth_login_handles_record_serialize_failure(monkeypatch):
    """If the captured AuthenticationRecord can't be serialized for any
    reason (azure-identity version mismatch, etc.), the login itself must
    still succeed — we lose the silent-replay optimization but the user
    is signed in for THIS invocation."""
    from pql_test import cli as cli_module

    bad_record = MagicMock()
    bad_record.serialize.side_effect = RuntimeError("serialize broke")
    bad_record.username = "fallback@example.com"

    fake_credential = MagicMock()
    fake_credential.authenticate.return_value = bad_record

    with patch(
        "pql_test.auth.factory.CredentialFactory.create",
        return_value=fake_credential,
    ):
        runner = CliRunner()
        result = runner.invoke(cli_module.cli, ["auth", "login"], input="1\n")

    assert result.exit_code == 0, (
        f"auth login must not crash when record.serialize() fails. Output:\n{result.output}"
    )
    saved = AuthenticationManager()._store.load()
    assert saved is not None
    # Record JSON is absent — but the login was saved.
    assert saved.authentication_record_json is None
    assert saved.method == AuthMethod.INTERACTIVE
