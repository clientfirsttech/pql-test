"""
XMLA connection resolution - coordinates auth, local PBI, and service connections.

This module provides the central resolve_xmla_connection() function that:
1. Resolves credentials (CLI flags → env vars → stored credentials)
2. Determines connection type (local/<name>, service, or filesystem path)
3. Returns a ResolvedXmlaConnection with server, catalog, and auth details
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from pql_test.runner.auth import _resolve_authentication_with_stored_credentials
    from pql_test.runner.local_pbi import (
        _detect_local_pbi_desktop_port,
        get_pbi_files_opened,
    )
    from pql_test.runner.pbi_rest import (
        _acquire_service_principal_token,
        _resolve_pbi_workspace_and_dataset_names,
        _resolve_pbi_workspace_name,
        _verify_dataset_exists_in_workspace,
    )
else:
    # Import at runtime through runner package to enable test mocking
    from pql_test import runner
    _resolve_authentication_with_stored_credentials = lambda *args: runner._resolve_authentication_with_stored_credentials(*args)
    get_pbi_files_opened = lambda *args: runner.get_pbi_files_opened(*args)
    _detect_local_pbi_desktop_port = lambda *args: runner._detect_local_pbi_desktop_port(*args)
    _acquire_service_principal_token = lambda *args, **kw: runner._acquire_service_principal_token(*args, **kw)
    _resolve_pbi_workspace_and_dataset_names = lambda *args, **kw: runner._resolve_pbi_workspace_and_dataset_names(*args, **kw)
    _resolve_pbi_workspace_name = lambda *args, **kw: runner._resolve_pbi_workspace_name(*args, **kw)
    _verify_dataset_exists_in_workspace = lambda *args, **kw: runner._verify_dataset_exists_in_workspace(*args, **kw)

from pql_test.runner.model_path import parse_model_identifier
from pql_test.runner.models import (
    ResolvedXmlaConnection,
    XmlaConnectionOptions,
    get_api_endpoints,
)

__all__ = [
    "_resolve_service_xmla_connection",
    "resolve_local_xmla_connection_by_name",
    "resolve_service_xmla_connection_by_name",
    "resolve_xmla_connection",
]


def resolve_xmla_connection(
    model_path: str,
    opts: XmlaConnectionOptions,
) -> Optional[ResolvedXmlaConnection]:
    """
    Resolve which XMLA endpoint to use for test execution.

    Priority:
      1. ``local/<model_name>`` identifier — strict name-based local
         detection.  Never falls back to a remote service connection
         (even if PQL_* credentials are present in the environment) and
         never falls back to an arbitrary running PBI Desktop instance.
         When the named instance isn't open, returns None so the caller
         can surface a clear "instance not found" error instead of
         silently running tests against the deployed dataset.
      2. Remote Power BI Premium / Fabric workspace (when tenant_id,
         workspace_id, dataset_id are all provided), matching Invoke-DQVTesting.
      3. Filesystem path — process-based local detection via
         ``resolve_local_xmla_connection``.

    Returns None when no connection can be established.
    """
    # Try to resolve credentials from stored config if not provided
    opts = _resolve_authentication_with_stored_credentials(opts)

    # Hermetic test mode disables auto-detection paths (stored
    # credentials, local PBI Desktop) so tests don't pick up developer-
    # machine state.  Explicit credentials passed on the command line
    # are still honored — tests that exercise the remote path supply
    # --tenant-id / --workspace-id / --dataset-id directly.
    hermetic = bool(os.environ.get("PQL_TEST_HERMETIC"))

    # Option 1 — local/<model_name> identifier (strict).
    # Short-circuit before any remote-service path so credentials in the
    # environment can't silently redirect a user's "run against my open
    # PBI Desktop instance" request to the deployed dataset.
    ident = parse_model_identifier(model_path)
    if ident.kind == "local":
        if hermetic:
            return None
        # Route through the runner package so tests can patch
        # ``pql_test.runner.resolve_local_xmla_connection_by_name``.
        return runner.resolve_local_xmla_connection_by_name(ident.model_name)

    if ident.kind == "service":
        if hermetic:
            return None
        # Canonical <workspace>.Workspace/<model>.SemanticModel path —
        # resolve by display name via REST, same as cmd_run_tests.  Short-
        # circuits like the local branch above: a caller who names a
        # specific workspace/model should never silently fall back to an
        # unrelated local PBI Desktop instance or GUID-based resolution.
        return runner.resolve_service_xmla_connection_by_name(
            ident.workspace_name, ident.model_name, opts,
        )

    # Option 2 — remote workspace (service principal).
    # If the service path raises (bad creds, dead workspace, unreachable
    # endpoint, etc.) we fall through to local detection instead of letting
    # the exception propagate or returning None silently.  Stale `.env`
    # files would otherwise mask "no connection" when a perfectly good
    # local Power BI Desktop session was sitting right there.
    #
    # The dataset can be identified either by GUID (opts.dataset_id) or by
    # display name (opts.dataset_name).  Name-based resolution lets callers
    # avoid storing dataset GUIDs as secrets — the CLI derives the name
    # from the `.SemanticModel` directory stem and the resolver verifies
    # the dataset exists in the workspace via REST.
    if opts.tenant_id and opts.workspace_id and (opts.dataset_id or opts.dataset_name):
        try:
            return _resolve_service_xmla_connection(opts)
        except Exception as exc:  # noqa: BLE001 — log + fall through to local
            print(
                f"Warning: remote XMLA connection failed ({type(exc).__name__}: "
                f"{exc}). Falling back to local Power BI Desktop detection.",
                file=sys.stderr,
            )
            # Fall through to local detection below.

    # Option 3 — local Power BI Desktop (filesystem path).  Skipped in
    # hermetic test mode so a running PBI Desktop instance on the
    # developer's machine doesn't leak into test subprocess results.
    if hermetic:
        return None
    
    # Import here to avoid circular dependency, and use through runner namespace for test mocking
    if TYPE_CHECKING:
        from pql_test.runner.local_pbi import resolve_local_xmla_connection
        return resolve_local_xmla_connection(model_path)
    else:
        return runner.resolve_local_xmla_connection(model_path)


def _resolve_service_xmla_connection(
    opts: XmlaConnectionOptions,
) -> ResolvedXmlaConnection:
    """Build a service-XMLA connection from *opts*; raises on any failure.

    Extracted from ``resolve_xmla_connection`` so the caller can wrap the
    whole service path in a single try/except and fall back to local
    detection when something goes wrong.

    The dataset can be identified by either:
      * ``opts.dataset_id`` — GUID.  Both workspace and dataset display
        names are resolved via REST (the legacy ``Invoke-DQVTesting`` flow).
      * ``opts.dataset_name`` — display name.  Only the workspace display
        name is resolved via REST; the dataset name is used directly and
        merely verified to exist in the workspace.  This lets callers stop
        storing dataset GUIDs as secrets.
    """
    endpoints = get_api_endpoints(opts.environment)

    # If a bearer has already been acquired by the auth subsystem (interactive
    # / cert / federated / managed identity flows), use it directly.  Only
    # call MSAL when we genuinely have an SPN-secret triple.
    if opts.access_token:
        token = opts.access_token
    else:
        token = _acquire_service_principal_token(
            opts.tenant_id,
            opts.client_id,
            opts.client_secret,
            login_url=endpoints.login_url,
            resource_url=endpoints.resource_url,
        )

    if opts.dataset_id:
        workspace_name, dataset_name = _resolve_pbi_workspace_and_dataset_names(
            workspace_id=opts.workspace_id,
            dataset_id=opts.dataset_id,
            access_token=token,
            api_prefix=endpoints.api_prefix,
        )
    else:
        workspace_name = _resolve_pbi_workspace_name(
            workspace_id=opts.workspace_id,
            access_token=token,
            api_prefix=endpoints.api_prefix,
        )
        dataset_name = opts.dataset_name
        _verify_dataset_exists_in_workspace(
            workspace_id=opts.workspace_id,
            dataset_name=dataset_name,
            access_token=token,
            api_prefix=endpoints.api_prefix,
        )

    # Derive the XMLA scheme prefix from the REST API prefix.
    # e.g. https://api.powerbi.com → powerbi://api.powerbi.com
    xmla_prefix = endpoints.api_prefix.replace("https://", "powerbi://")
    server = f"{xmla_prefix}/v1.0/myorg/{workspace_name}"
    return ResolvedXmlaConnection(
        server=server,
        catalog=dataset_name,
        tenant_id=opts.tenant_id,
        client_id=opts.client_id,
        client_secret=opts.client_secret,
        access_token=token,
    )


def resolve_service_xmla_connection_by_name(
    workspace_name: str,
    semantic_model_name: str,
    opts: XmlaConnectionOptions,
) -> Optional[ResolvedXmlaConnection]:
    """
    Resolve a remote XMLA connection using workspace and semantic-model
    **display names** directly, skipping the GUID-based REST API resolution.

    This mirrors the Fabric CLI ``fab run <workspace>.<semantic_model>`` flow
    where display names are supplied by the caller instead of GUIDs.

    Authentication is resolved from (in priority order): explicit *opts*
    fields, ``PQL_*`` environment variables, or a stored credential from
    ``pql-test auth login`` (any method — interactive, SPN-secret,
    SPN-cert, federated, or managed identity).  When the stored method is
    non-secret-based, the bearer token is acquired via ``azure-identity``
    and surfaced on ``opts.access_token``; this function passes it through
    to ADOMD via the existing MSOLAP ``Password=<bearer>;`` segment.
    """
    # Resolve credentials from CLI flags / env vars / stored config.
    opts = _resolve_authentication_with_stored_credentials(opts)

    endpoints = get_api_endpoints(opts.environment)

    if opts.access_token:
        # Pre-acquired bearer from a non-secret auth flow (interactive /
        # cert / federated / managed identity).
        token = opts.access_token
    elif opts.tenant_id and opts.client_id and opts.client_secret:
        # Legacy SPN-secret path — acquire via MSAL client-credentials.
        token = _acquire_service_principal_token(
            opts.tenant_id,
            opts.client_id,
            opts.client_secret,
            login_url=endpoints.login_url,
            resource_url=endpoints.resource_url,
        )
    else:
        # No usable credentials.
        return None

    xmla_prefix = endpoints.api_prefix.replace("https://", "powerbi://")
    server = f"{xmla_prefix}/v1.0/myorg/{workspace_name}"
    return ResolvedXmlaConnection(
        server=server,
        catalog=semantic_model_name,
        tenant_id=opts.tenant_id,
        client_id=opts.client_id,
        client_secret=opts.client_secret,
        access_token=token,
    )


def resolve_local_xmla_connection_by_name(
    model_name: str,
    instances: list | None = None,
) -> Optional[ResolvedXmlaConnection]:
    """
    Resolve a local XMLA connection by matching *model_name* against
    running Power BI Desktop instances (case-insensitive).

    Used by the ``local/<model_name>`` model-identifier format where no
    local filesystem path is available.

    When *instances* is provided, it is used directly and
    ``get_pbi_files_opened`` is not called — this lets callers enumerate
    once and share the result across the resolver, verbose printouts, and
    miss-diagnostics.  When *instances* is ``None`` (default), the
    resolver enumerates itself, preserving the original single-argument
    call signature.
    """
    if instances is None:
        try:
            instances = get_pbi_files_opened()
        except ImportError:
            port = _detect_local_pbi_desktop_port()
            if port:
                return ResolvedXmlaConnection(server=port, catalog="")
            return None

    if not instances:
        port_str = _detect_local_pbi_desktop_port()
        if port_str:
            return ResolvedXmlaConnection(server=port_str, catalog="")
        return None

    needle = model_name.lower()
    for inst in instances:
        # Use a substring (``in``) match against the detected name so this
        # works for both window-title formats: newer builds show just the
        # model name (``OLS_Model``) while older builds appended a suffix
        # (``OLS_Model - Power BI Desktop``).  We keep suffix-stripping in
        # the title parser so the displayed name stays clean, but a fall-
        # back substring check here means callers also resolve correctly
        # if the suffix-strip ever misses an unusual variant.
        if needle and needle in inst.model_name.lower():
            return ResolvedXmlaConnection(
                server=inst.server,
                catalog=inst.catalog,
            )

    # No name match.  The user typed a specific model name via
    # ``local/<name>`` — we MUST honor it strictly.  The previous
    # unnamed-instance fallback (when window-title detection failed) caused
    # silent connections to the wrong model — e.g. ``local/SampleModel``
    # silently connecting to an open RLS_Model and running its tests under
    # SampleModel's name.  See tasks/surface-silent-test-discovery-failures-epic.md.
    #
    # If window-title detection is unreliable on your machine (Microsoft Store
    # packaging, UAC mismatch), open Power BI Desktop from an elevated
    # terminal or use the filesystem-path form instead.
    return None
