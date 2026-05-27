"""
Credential factory for creating azure.identity credential objects.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

try:
    from azure.identity import (
        AuthenticationRecord,
        CertificateCredential,
        ClientAssertionCredential,
        ClientSecretCredential,
        InteractiveBrowserCredential,
        ManagedIdentityCredential,
        TokenCachePersistenceOptions,
    )
    from azure.core.credentials import TokenCredential
    HAS_AZURE_IDENTITY = True
except ImportError:
    HAS_AZURE_IDENTITY = False
    AuthenticationRecord = None  # type: ignore[assignment,misc]
    TokenCachePersistenceOptions = None  # type: ignore[assignment,misc]
    if TYPE_CHECKING:
        from azure.core.credentials import TokenCredential

from pql_test.auth.cloud_config import CloudConfig
from pql_test.auth.exceptions import CredentialConfigError
from pql_test.auth.models import AuthMethod, CredentialConfig


def _persistent_token_cache_options():  # type: ignore[no-untyped-def]
    """Build ``TokenCachePersistenceOptions`` so MSAL writes tokens to the
    platform's secure store (Windows DPAPI / macOS Keychain / Linux
    libsecret).  Without this, every CLI invocation builds a fresh credential
    with a cold cache and triggers a new interactive sign-in — the user
    sees a browser tab pop on every ``pql-test`` command.

    Defaults to encrypted-only storage.  Set
    ``PQL_TEST_ALLOW_UNENCRYPTED_TOKEN_CACHE=1`` on headless Linux without
    libsecret to opt into unencrypted file-backed caching.

    Returns ``None`` if azure-identity is missing — the caller treats that
    as "no persistence configured" which falls back to azure-identity's
    default in-memory cache.
    """
    if TokenCachePersistenceOptions is None:
        return None
    allow_unencrypted = os.environ.get(
        "PQL_TEST_ALLOW_UNENCRYPTED_TOKEN_CACHE", ""
    ).lower() in ("1", "true", "yes")
    return TokenCachePersistenceOptions(
        name="pql-test",
        allow_unencrypted_storage=allow_unencrypted,
    )


class CredentialFactory:
    """Factory for creating azure.identity credential objects from configuration."""

    def create(
        self, config: CredentialConfig, cloud_config: CloudConfig
    ) -> TokenCredential:
        """
        Create TokenCredential from configuration.

        Args:
            config: Credential configuration
            cloud_config: Cloud environment configuration

        Returns:
            TokenCredential instance

        Raises:
            CredentialConfigError: If azure-identity not installed or config is invalid
        """
        if not HAS_AZURE_IDENTITY:
            raise CredentialConfigError(
                "azure-identity is required for authentication. "
                "Install with: pip install azure-identity"
            )

        authority = cloud_config.get_authority(config.environment)
        cache_opts = _persistent_token_cache_options()

        if config.method == AuthMethod.INTERACTIVE:
            # Replay the AuthenticationRecord captured on first sign-in so
            # azure-identity can look up the cached token by homeAccountId
            # instead of triggering a fresh browser flow.  Without this,
            # cache_persistence_options writes a cache that's never read.
            record = None
            if config.authentication_record_json and AuthenticationRecord is not None:
                try:
                    record = AuthenticationRecord.deserialize(
                        config.authentication_record_json
                    )
                except Exception:  # noqa: BLE001
                    # Corrupted record — fall through to interactive prompt.
                    record = None

            # When a record is supplied, azure-identity reads tenant_id,
            # authority, and client_id from it directly — passing those
            # kwargs ALSO causes a "got multiple values for keyword argument"
            # TypeError inside MsalCredential.__init__.  Only pass them on
            # the first-login path where we have no record.
            if record is not None:
                return InteractiveBrowserCredential(
                    cache_persistence_options=cache_opts,
                    authentication_record=record,
                )
            return InteractiveBrowserCredential(
                tenant_id=config.tenant_id,
                authority=authority,
                cache_persistence_options=cache_opts,
            )

        elif config.method == AuthMethod.SERVICE_PRINCIPAL_SECRET:
            if not all([config.tenant_id, config.client_id, config.client_secret]):
                raise CredentialConfigError(
                    "Service principal with secret requires tenant_id, client_id, and client_secret"
                )
            return ClientSecretCredential(
                tenant_id=config.tenant_id,
                client_id=config.client_id,
                client_secret=config.client_secret,
                authority=authority,
                cache_persistence_options=cache_opts,
            )

        elif config.method == AuthMethod.SERVICE_PRINCIPAL_CERT:
            if not all([config.tenant_id, config.client_id, config.certificate_path]):
                raise CredentialConfigError(
                    "Service principal with certificate requires tenant_id, client_id, and certificate_path"
                )
            return CertificateCredential(
                tenant_id=config.tenant_id,
                client_id=config.client_id,
                certificate_path=config.certificate_path,
                password=config.certificate_password,
                authority=authority,
                cache_persistence_options=cache_opts,
            )

        elif config.method == AuthMethod.SERVICE_PRINCIPAL_FEDERATED:
            if not all([config.tenant_id, config.client_id, config.federated_token]):
                raise CredentialConfigError(
                    "Federated credential requires tenant_id, client_id, and federated_token"
                )

            # Note: azure-identity uses ClientAssertionCredential for federated tokens
            def token_provider() -> str:
                return config.federated_token or ""

            return ClientAssertionCredential(
                tenant_id=config.tenant_id,
                client_id=config.client_id,
                func=token_provider,
                authority=authority,
                cache_persistence_options=cache_opts,
            )

        elif config.method == AuthMethod.MANAGED_IDENTITY:
            if config.use_system_assigned_identity:
                return ManagedIdentityCredential()
            else:
                if not config.client_id:
                    raise CredentialConfigError(
                        "User-assigned managed identity requires client_id"
                    )
                return ManagedIdentityCredential(client_id=config.client_id)

        else:
            raise CredentialConfigError(
                f"Unsupported authentication method: {config.method}"
            )
