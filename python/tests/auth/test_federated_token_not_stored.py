# SPDX-License-Identifier: AGPL-3.0-only
"""The federated token is never stored: it is short-lived and larger than Windows Credential Manager allows."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import pql_test.cli as cli_module
from pql_test.auth.cloud_config import CloudConfig
from pql_test.auth.exceptions import CredentialConfigError
from pql_test.auth.factory import CredentialFactory
from pql_test.auth.models import AuthMethod, CredentialConfig

_CONFIG = dict(method=AuthMethod.SERVICE_PRINCIPAL_FEDERATED, tenant_id="t", client_id="c", environment="Public")


def _assertion_provider(config: CredentialConfig):
    captured = {}

    def fake_constructor(self, **kwargs):
        captured.update(kwargs)

    from azure.identity import ClientAssertionCredential

    with patch.object(ClientAssertionCredential, "__init__", fake_constructor):
        CredentialFactory().create(config, CloudConfig())
    return captured["func"]


def test_login_saves_a_config_without_the_token(monkeypatch):
    given = "auth login with a (long) federated token"
    should = "hand the credential the token but save a config that holds none"
    from click.testing import CliRunner

    long_token = "eyJ" + "a" * 4000  # over the 2560-byte Credential Manager limit
    saved = []
    fake_credential = MagicMock(spec=["get_token"])
    fake_credential.get_token.return_value = MagicMock(token="tok")
    created = []

    def create(self, config, cloud):
        created.append(config.federated_token)
        return fake_credential

    with patch("pql_test.auth.factory.CredentialFactory.create", create), patch(
        "pql_test.auth.manager.AuthenticationManager.save_credential", lambda self, cfg: saved.append(cfg)
    ):
        result = CliRunner().invoke(
            cli_module.cli,
            ["auth", "login", "-u", "c", "--tenant", "t"],
            env={"PQL_FEDERATED_TOKEN": long_token},
        )

    assert (result.exit_code, created, [c.federated_token for c in saved]) == (0, [long_token], [None]), (
        f"{given}: {should}\n{result.output}"
    )


def test_credential_reads_the_token_from_the_environment_when_none_is_stored(monkeypatch):
    given = "a stored config with no token and PQL_FEDERATED_TOKEN set"
    should = "use the environment's token as the client assertion"
    monkeypatch.setenv("PQL_FEDERATED_TOKEN", "from-env")

    assert _assertion_provider(CredentialConfig(**_CONFIG))() == "from-env", f"{given}: {should}"


def test_credential_without_any_token_explains_what_to_set(monkeypatch):
    given = "a stored config with no token and no PQL_FEDERATED_TOKEN"
    should = "raise an error that names PQL_FEDERATED_TOKEN"
    monkeypatch.delenv("PQL_FEDERATED_TOKEN", raising=False)
    provider = _assertion_provider(CredentialConfig(**_CONFIG))

    with pytest.raises(CredentialConfigError, match="PQL_FEDERATED_TOKEN"):
        provider()
