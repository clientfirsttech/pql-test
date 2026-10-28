# SPDX-License-Identifier: AGPL-3.0-only
"""Tests that XMLA impersonation parameters compose with bearer-token auth.

Symptom this guards against: ``pql-test run-tests`` against a service XMLA
endpoint (CI / Fabric workspace) silently dropped any ``EffectiveUserName=``
or ``Roles=`` connection-string parameter when a bearer access token was set
on the resolved connection.  As a result, ``PQL.Assert.OLS.*`` and
``PQL.Assert.RLS.*`` assertions evaluated against the unfiltered model and
reported ``Actual: VISIBLE (OLS not working)`` despite the test functions
carrying ``PQLAssert_RoleName`` / ``PQLAssert_ImpersonatedUserName``
annotations — even though the same tests passed locally against Power BI
Desktop (where no bearer token is involved).

The connection string must compose the auth segment AND the impersonation
segment regardless of which auth path is taken.
"""

from __future__ import annotations

from pql_test.runner import ResolvedXmlaConnection, _build_connection_string


def test_bearer_token_and_effective_user_name_compose():
    """SPN bearer token + EffectiveUserName -> both must appear in the connection string."""
    conn = ResolvedXmlaConnection(
        server="powerbi://api.powerbi.com/v1.0/myorg/WS",
        catalog="OLS_Model",
        access_token="bearer-abc",
        effective_user_name="atlas.kerski@cftechnologiesllc.com",
    )
    cs = _build_connection_string(conn)
    assert "Password=bearer-abc;" in cs
    assert "EffectiveUserName=atlas.kerski@cftechnologiesllc.com;" in cs


def test_bearer_token_and_roles_compose():
    """SPN bearer token + Roles -> both must appear in the connection string."""
    conn = ResolvedXmlaConnection(
        server="powerbi://api.powerbi.com/v1.0/myorg/WS",
        catalog="OLS_Model",
        access_token="bearer-xyz",
        roles="West",
    )
    cs = _build_connection_string(conn)
    assert "Password=bearer-xyz;" in cs
    assert "Roles=West;" in cs


def test_service_principal_creds_and_roles_compose():
    """SPN client-creds auth (no pre-acquired token) + Roles -> both appear."""
    conn = ResolvedXmlaConnection(
        server="powerbi://api.powerbi.com/v1.0/myorg/WS",
        catalog="OLS_Model",
        tenant_id="t",
        client_id="c",
        client_secret="s",
        roles="Admin",
    )
    cs = _build_connection_string(conn)
    assert "User ID=app:c@t;" in cs
    assert "Roles=Admin;" in cs


def test_local_connection_with_no_impersonation_has_no_impersonation_params():
    """A local connection with no Roles/EUN must not invent either param."""
    conn = ResolvedXmlaConnection(server="localhost:50001", catalog="RLS_Model")
    cs = _build_connection_string(conn)
    assert "Roles=" not in cs
    assert "EffectiveUserName" not in cs


def test_roles_takes_priority_when_both_set_with_bearer_token():
    """When both Roles and EUN are set alongside a bearer token, Roles wins."""
    conn = ResolvedXmlaConnection(
        server="powerbi://api.powerbi.com/v1.0/myorg/WS",
        catalog="OLS_Model",
        access_token="tok",
        roles="West",
        effective_user_name="west@contoso.com",
    )
    cs = _build_connection_string(conn)
    assert "Roles=West;" in cs
    assert "EffectiveUserName" not in cs
