"""
Authentication credential resolution and stored credentials bridge.

This module handles authentication credential fallback in priority order:
1. CLI flags (explicit tenant_id, client_id, client_secret)
2. Environment variables (PQL_TENANT_ID, PQL_CLIENT_ID, PQL_CLIENT_SECRET)
3. Stored credentials (from `pql-test auth login`)

For stored credentials, behavior depends on auth method:
- SERVICE_PRINCIPAL_SECRET: forward secret → MSAL client-credentials flow
- INTERACTIVE/CERT/FEDERATED/MANAGED_IDENTITY: acquire token → attach to access_token
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

from pql_test.runner.models import Environment, XmlaConnectionOptions

if TYPE_CHECKING:
    from pql_test.auth import AuthenticationManager, AuthMethod

__all__ = [
    "_resolve_authentication_with_stored_credentials",
]

# Runtime imports for optional dependencies
HAS_MSAL = False
try:
    import msal  # type: ignore[import-untyped]

    HAS_MSAL = True
except ImportError:
    pass


def _resolve_authentication_with_stored_credentials(
    opts: XmlaConnectionOptions,
) -> XmlaConnectionOptions:
    """
    Resolve authentication credentials with fallback to stored credentials.

    Priority:
      1. CLI flags (opts.tenant_id, opts.client_id, opts.client_secret)
      2. Environment variables (PQL_TENANT_ID, PQL_CLIENT_ID, PQL_CLIENT_SECRET)
      3. Stored credentials (from ``pql-test auth login``)

    For stored credentials the behavior depends on the chosen auth method:

    * ``SERVICE_PRINCIPAL_SECRET`` — the secret is forwarded as
      ``client_secret`` so the downstream resolver runs MSAL's
      client-credentials flow (legacy code path, preserved bit-for-bit).
    * ``INTERACTIVE`` / ``SERVICE_PRINCIPAL_CERT`` /
      ``SERVICE_PRINCIPAL_FEDERATED`` / ``MANAGED_IDENTITY`` — a bearer token
      is acquired via ``AuthenticationManager.get_access_token`` (which uses
      the appropriate ``azure-identity`` credential class under the hood) and
      attached to ``opts.access_token``. The downstream resolver then hands
      that bearer to ADOMD via the existing MSOLAP ``Password=<bearer>;``
      connection-string segment.

    See tasks/unified-auth-runtime-epic.md.
    """
    # Hermetic test mode skips all developer-machine state: no .env, no
    # stored credentials, no token acquisition.  Tests that need a
    # connection mock it explicitly.
    if os.environ.get("PQL_TEST_HERMETIC"):
        return opts

    # If any credentials are already provided (even partial), return as-is
    # This preserves the existing validation behavior where partial credentials fail
    if opts.tenant_id or opts.client_id or opts.client_secret:
        return opts

    # Check if credentials are in environment variables
    env_tenant = os.getenv("PQL_TENANT_ID")
    env_client = os.getenv("PQL_CLIENT_ID")
    env_secret = os.getenv("PQL_CLIENT_SECRET")

    if env_tenant or env_client or env_secret:
        # Use environment variables (may be partial, but that's intentional)
        return XmlaConnectionOptions(
            tenant_id=env_tenant or opts.tenant_id,
            workspace_id=opts.workspace_id,
            dataset_id=opts.dataset_id,
            client_id=env_client or opts.client_id,
            client_secret=env_secret or opts.client_secret,
            environment=opts.environment,
        )

    # Fallback to stored credentials only when NO credentials provided at all
    try:
        from pql_test.auth import AuthenticationManager, AuthMethod

        manager = AuthenticationManager()
        status = manager.get_status()

        if not status.authenticated:
            return opts  # No stored credentials

        config = manager._store.load()
        if config is None:
            return opts

        # The stored credential records which cloud it was created for
        # (`pql-test auth login --environment`), so the credential and its
        # cloud travel together — a USGov login should never be aimed at
        # the Public endpoints.  Fall back to opts.environment when the
        # stored value doesn't parse.
        stored_env = opts.environment
        for e in Environment:
            if e.value.lower() == (config.environment or "").strip().lower():
                stored_env = e
                break

        # SPN-with-secret: forward the secret so MSAL acquires the token
        # downstream.  Keeps the legacy code path intact for the SPN happy
        # path (env-based CI workflows).
        if config.method == AuthMethod.SERVICE_PRINCIPAL_SECRET:
            return XmlaConnectionOptions(
                tenant_id=config.tenant_id or opts.tenant_id,
                workspace_id=opts.workspace_id,
                dataset_id=opts.dataset_id,
                client_id=config.client_id or opts.client_id,
                client_secret=config.client_secret or opts.client_secret,
                environment=stored_env,
            )

        # INTERACTIVE: refuse to launch the browser in non-interactive
        # environments (CI runners) where no one is there to complete the
        # OAuth dance.  We warn + return opts unchanged so the caller can
        # still fall back to local detection — and so generic runner-level
        # callers don't crash just because the user happens to have stored
        # interactive creds on their dev box.  CLI commands that NEED a
        # service connection (e.g. ``run-tests workspace.model``) surface a
        # dedicated error to the user; see cli.py.
        if config.method == AuthMethod.INTERACTIVE:
            in_ci = bool(os.getenv("CI"))
            no_tty = not (hasattr(sys.stdin, "isatty") and sys.stdin.isatty())
            if in_ci or no_tty:
                print(
                    "Warning: stored interactive credentials cannot be used in "
                    "a non-interactive environment (no TTY or CI=true). "
                    "Falling back to local detection. For CI, log in with "
                    "`pql-test auth login` using a service principal or "
                    "managed identity, or supply --tenant-id / --client-id / "
                    "--client-secret flags.",
                    file=sys.stderr,
                )
                return opts

        # All other azure-identity-backed methods (interactive in a TTY,
        # cert, federated, managed identity) — acquire a bearer via the
        # manager and surface it on opts.access_token.
        token = manager.get_access_token()
        if not token:
            return opts
        return XmlaConnectionOptions(
            tenant_id=config.tenant_id or opts.tenant_id,
            workspace_id=opts.workspace_id,
            dataset_id=opts.dataset_id,
            client_id=config.client_id or opts.client_id,
            client_secret=opts.client_secret,
            environment=stored_env,
            access_token=token,
        )

    except ImportError:
        # auth module not available
        return opts
    except Exception as exc:  # noqa: BLE001
        # Surface unexpected errors on stderr so the user can diagnose
        # why their stored credentials aren't being honored.  The bridge
        # still returns opts unchanged so the caller can fall back to
        # other code paths (file-based discovery, local PBI Desktop, etc.).
        # Without this, the run silently fails with the generic "Service
        # connection requires --tenant-id..." error, masking the real
        # cause (corrupt AuthenticationRecord, expired token, MSAL cache
        # access failure, etc.).
        print(
            f"Warning: failed to acquire token from stored credentials: "
            f"{type(exc).__name__}: {str(exc)[:300]}",
            file=sys.stderr,
        )
        return opts
