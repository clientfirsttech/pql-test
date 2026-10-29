# SPDX-License-Identifier: AGPL-3.0-only
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
    "summarize_xmla_exception",
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
    catalog_part = f";Initial Catalog={_conn_value(conn.catalog)}" if conn.catalog else ""
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
        parts.append(f"Roles={_conn_value(conn.roles)};")
    elif conn.effective_user_name:
        parts.append(f"EffectiveUserName={_conn_value(conn.effective_user_name)};")

    return "".join(parts)


def _conn_value(value: str) -> str:
    """A connection-string value that cannot add or override keys.

    Catalog, role, and user names come from the model (annotations) and the workspace, so
    a value such as ``x;Data Source=evil`` must stay one value: per the OLE DB connection
    string rules it is wrapped in double quotes, with embedded double quotes doubled.
    """
    if any(c in value for c in (";", '"', "'")) or value != value.strip():
        return '"' + value.replace('"', '""') + '"'
    return value


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


# Power BI / ADOMD.NET error codes that mean something actionable but are
# buried several lines into a multi-line .NET exception message -- e.g.
# AdomdConnectionException's own message is just "PowerBI Request Failed.",
# with the actual REST error code (and the one-line fix) further down in
# the "Description: {...}" JSON blob.  First-line-only truncation throws
# this away, so these are matched anywhere in the full message text.
_KNOWN_XMLA_ERROR_HINTS = {
    "PowerBINotLicensedException": (
        "workspace lacks Premium/Fabric capacity -- XMLA and INFO DAX "
        "functions require Premium-per-capacity or Fabric, not Pro-only. "
        "Check the capacity assignment in the Fabric/Power BI admin portal."
    ),
    "PowerBINotProvisionedException": (
        "workspace or capacity is not yet provisioned/activated. Wait for "
        "provisioning to finish or check the capacity's status."
    ),
}


def summarize_xmla_exception(exc: Exception, *, max_len: int = 300) -> str:
    """One-line, actionable summary of an XMLA/ADOMD exception.

    Checks the full exception text for a known Power BI error code first
    (see ``_KNOWN_XMLA_ERROR_HINTS``) and returns an actionable hint when
    found; otherwise falls back to the previous behavior of the first line,
    truncated to *max_len* characters.
    """
    text = str(exc)
    for code, hint in _KNOWN_XMLA_ERROR_HINTS.items():
        if code in text:
            return f"{type(exc).__name__}: {code} -- {hint}"
    first_line = (text.splitlines() or [""])[0][:max_len]
    return f"{type(exc).__name__}: {first_line}"
