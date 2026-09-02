"""
XMLA query execution via ADOMD.NET - connection strings and DAX execution.

This module provides low-level functions for:
- Building ADOMD.NET connection strings with auth and impersonation
- Executing DAX queries and returning results as dictionaries
- Column name lookup with case-insensitivity and bracket notation support
"""

from __future__ import annotations

from pql_test.runner.adomd import get_adomd_connection_class, has_pyadomd
from pql_test.runner.models import ResolvedXmlaConnection
from pql_test.runner.pbi_rest import _acquire_service_principal_token

__all__ = [
    "_build_connection_string",
    "_execute_dax_query",
    "_get_col",
]


def _build_connection_string(conn: ResolvedXmlaConnection) -> str:
    """
    Build an ADOMD.NET connection string for the given resolved connection.

    The auth segment and the impersonation segment compose: e.g. a
    service-principal bearer token MUST coexist with ``Roles=`` /
    ``EffectiveUserName=`` so OLS/RLS rules are evaluated against the
    impersonated identity in CI.  Earlier the function returned at the
    first auth branch and silently dropped impersonation, which caused
    ``PQL.Assert.OLS.*`` tests to report ``Actual: VISIBLE (OLS not working)``
    against deployed datasets even when the test functions carried
    ``PQLAssert_RoleName`` / ``PQLAssert_ImpersonatedUserName`` annotations.

    Auth priority (highest to lowest):
      1. Bearer token (access_token) — preferred, acquired via MSAL.
      2. Service principal direct credentials (app:{clientId}@{tenantId}).
      3. Local / integrated auth — no extra parameters.

    Impersonation priority when both are set:
      1. Roles= (named role).  AS applies that role's rules directly.
      2. EffectiveUserName= (AAD UPN).  AS applies whatever roles the
         user is a member of.
    """
    catalog_part = f";Initial Catalog={conn.catalog}" if conn.catalog else ""
    parts: list[str] = [f"Provider=MSOLAP;Data Source={conn.server}{catalog_part};"]

    if conn.access_token:
        parts.append(f"Password={conn.access_token};")
    elif conn.client_id and conn.client_secret and conn.tenant_id:
        parts.append(
            f"User ID=app:{conn.client_id}@{conn.tenant_id};"
            f"Password={conn.client_secret};"
            "Integrated Security=ClaimsToken;"
        )

    if conn.roles:
        parts.append(f"Roles={conn.roles};")
    elif conn.effective_user_name:
        parts.append(f"EffectiveUserName={conn.effective_user_name};")

    return "".join(parts)


def _get_col(row: dict[str, object], key: str) -> str:
    """
    Case-insensitive column lookup for ADOMD.NET result rows.

    DAX/ADOMD.NET may return column names with a table prefix
    (e.g. "Calculations[TestName]") so we match by substring to handle
    both plain column names ("TestName") and bracket notation.
    """
    key_lower = key.lower()
    for k, v in row.items():
        k_lower = k.lower()
        # Exact match or bracket-notation prefix: "testname" or "table[testname]"
        if k_lower == key_lower or k_lower.endswith(f"[{key_lower}]"):
            return str(v) if v is not None else ""
    return ""


def _execute_dax_query(
    conn: ResolvedXmlaConnection,
    dax_query: str,
) -> list[dict[str, object]]:
    """
    Execute a DAX query via ADOMD.NET (pyadomd) and return rows as dicts.

    For service-principal connections an OAuth2 bearer token is acquired
    via MSAL when raw credentials are supplied without a pre-existing token.
    Token-based auth is preferred because it supports row-level security
    evaluation with service principals — the primary use-case for build agents.
    """
    if not has_pyadomd():
        raise ImportError(
            "pyadomd is required for XMLA query execution. "
            "Install with: pip install pyadomd"
        )

    _AdomdConnection = get_adomd_connection_class()
    if _AdomdConnection is None:
        raise ImportError("ADOMD.NET not loaded")

    # Acquire bearer token for service principal if credentials supplied
    if (
        conn.client_id
        and conn.client_secret
        and conn.tenant_id
        and not conn.access_token
    ):
        conn.access_token = _acquire_service_principal_token(
            conn.tenant_id, conn.client_id, conn.client_secret
        )

    conn_str = _build_connection_string(conn)

    adomd_conn = _AdomdConnection(conn_str)  # type: ignore[misc]
    adomd_conn.Open()
    try:
        cmd = adomd_conn.CreateCommand()
        cmd.CommandText = dax_query
        reader = cmd.ExecuteReader()
        try:
            field_count = reader.FieldCount
            if field_count == 0:
                return []
            columns = [reader.GetName(i) for i in range(field_count)]
            rows: list[dict[str, object]] = []
            while reader.Read():
                rows.append({col: reader[i] for i, col in enumerate(columns)})
            return rows
        finally:
            reader.Close()
    finally:
        adomd_conn.Close()
