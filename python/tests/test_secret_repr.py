# SPDX-License-Identifier: AGPL-3.0-only
"""Secrets never appear in the repr() of the objects that carry them (logs, tracebacks, --verbose)."""

from __future__ import annotations

from pql_test.auth.models import AuthMethod, CredentialConfig
from pql_test.runner import ResolvedXmlaConnection, XmlaConnectionOptions

SECRET = "s3cr3t-value"


def test_secrets_are_left_out_of_repr():
    given = "credential and connection objects holding a client secret, token, and certificate password"
    should = "keep every secret out of repr(), while still holding it"
    objects = [
        CredentialConfig(
            method=AuthMethod.SERVICE_PRINCIPAL_SECRET,
            client_secret=SECRET,
            certificate_password=SECRET,
            federated_token=SECRET,
            authentication_record_json=SECRET,
        ),
        XmlaConnectionOptions(client_secret=SECRET, access_token=SECRET),
        ResolvedXmlaConnection(server="s", catalog="c", client_secret=SECRET, access_token=SECRET),
    ]

    assert ([SECRET in repr(o) for o in objects], objects[2].access_token) == ([False, False, False], SECRET), (
        f"{given}: {should}"
    )
