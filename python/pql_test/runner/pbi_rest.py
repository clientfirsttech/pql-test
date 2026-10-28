# SPDX-License-Identifier: AGPL-3.0-only
"""
Power BI REST API helpers for workspace and dataset resolution.

This module provides functions to resolve workspace and dataset display names
from GUIDs using the Power BI REST API, and to verify dataset existence by name.
"""

from __future__ import annotations

import json
import urllib.request

__all__ = [
    "_acquire_service_principal_token",
    "_resolve_pbi_workspace_and_dataset_names",
    "_resolve_pbi_workspace_name",
    "_verify_dataset_exists_in_workspace",
]

# Runtime import handling for optional dependencies
HAS_MSAL = False
try:
    import msal  # type: ignore[import-untyped]

    HAS_MSAL = True
except ImportError:
    pass


def _resolve_pbi_workspace_and_dataset_names(
    workspace_id: str,
    dataset_id: str,
    access_token: str,
    *,
    api_prefix: str = "https://api.powerbi.com",
) -> tuple[str, str]:
    """
    Resolve the display names for a Power BI workspace (group) and dataset
    from their GUIDs using the Power BI REST API.

    The XMLA endpoint requires display names, not GUIDs:
      powerbi://<api_host>/v1.0/myorg/<WorkspaceName>
      Initial Catalog = <DatasetName>

    Returns (workspace_name, dataset_name).
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    base = f"{api_prefix}/v1.0/myorg"

    def _get(url: str) -> dict:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())

    workspace_data = _get(f"{base}/groups/{workspace_id}")
    workspace_name: str = workspace_data["name"]

    dataset_data = _get(f"{base}/groups/{workspace_id}/datasets/{dataset_id}")
    dataset_name: str = dataset_data["name"]

    return workspace_name, dataset_name


def _resolve_pbi_workspace_name(
    workspace_id: str,
    access_token: str,
    *,
    api_prefix: str = "https://api.powerbi.com",
) -> str:
    """Look up a Power BI workspace's display name from its GUID."""
    req = urllib.request.Request(
        f"{api_prefix}/v1.0/myorg/groups/{workspace_id}",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())["name"]


def _verify_dataset_exists_in_workspace(
    workspace_id: str,
    dataset_name: str,
    access_token: str,
    *,
    api_prefix: str = "https://api.powerbi.com",
) -> None:
    """
    Raise a clear ``ValueError`` if *dataset_name* is not present in the
    workspace's dataset list.  Lets the caller skip storing a GUID secret
    and rely on the deployed dataset's display name (case-insensitive)
    matching the local ``.SemanticModel`` directory stem.
    """
    req = urllib.request.Request(
        f"{api_prefix}/v1.0/myorg/groups/{workspace_id}/datasets",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    with urllib.request.urlopen(req) as resp:
        datasets = json.loads(resp.read().decode()).get("value", [])
    available = [d.get("name") for d in datasets]
    if not any((n or "").lower() == dataset_name.lower() for n in available):
        raise ValueError(
            f"Dataset {dataset_name!r} not found in workspace {workspace_id}. "
            f"Available datasets: {', '.join(repr(n) for n in available) or '<none>'}"
        )


def _acquire_service_principal_token(
    tenant_id: str,
    client_id: str,
    client_secret: str,
    *,
    login_url: str = "https://login.microsoftonline.com",
    resource_url: str = "https://analysis.windows.net/powerbi/api",
) -> str:
    """
    Acquire an OAuth2 access token for a service principal via MSAL.

    Uses the client-credentials flow targeting the Power BI / Analysis
    Services scope for the given cloud environment.
    This mirrors the authentication approach used by Invoke-DQVTesting
    for build-agent pipelines that require row-level security evaluation.
    """
    if not HAS_MSAL:
        raise ImportError(
            "msal is required for service principal authentication. "
            "Install with: pip install msal"
        )
    app = msal.ConfidentialClientApplication(
        client_id=client_id,
        client_credential=client_secret,
        authority=f"{login_url}/{tenant_id}",
    )
    result = app.acquire_token_for_client(scopes=[f"{resource_url}/.default"])
    if "access_token" in result:
        return result["access_token"]
    raise RuntimeError(
        "Failed to acquire access token: "
        + result.get("error_description", result.get("error", "Unknown error"))
    )
