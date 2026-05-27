"""
Credential factory for creating azure.identity credential objects.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

try:
    from azure.identity import (
        CertificateCredential,
        ClientAssertionCredential,
        ClientSecretCredential,
        InteractiveBrowserCredential,
        ManagedIdentityCredential,
    )
    from azure.core.credentials import TokenCredential
    HAS_AZURE_IDENTITY = True
except ImportError:
    HAS_AZURE_IDENTITY = False
    if TYPE_CHECKING:
        from azure.core.credentials import TokenCredential

from pql_test.auth.cloud_config import CloudConfig
from pql_test.auth.exceptions import CredentialConfigError
from pql_test.auth.models import AuthMethod, CredentialConfig


# ---------------------------------------------------------------------------
# Default interactive client_id
# ---------------------------------------------------------------------------
#
# Power BI's XMLA endpoint only accepts bearer tokens whose `appid` claim
# matches a client app the gateway trusts.  azure-identity's
# InteractiveBrowserCredential defaults to the Azure development application
# (Azure CLI's public client `04b07795-…`), which Power BI XMLA rejects with
# `Authentication failed for all authenticators`.
#
# The pql-test project registers its own multi-tenant Azure AD application
# (public client, delegated Power BI permissions) and ships its client_id
# here as the default for the INTERACTIVE auth method.  End users grant
# consent on first sign-in and never have to register their own app.
#
# Forks / enterprises that have registered their own pql-test equivalent
# can override via the PQL_TEST_INTERACTIVE_CLIENT_ID env var without
# touching the source.
PQL_TEST_DEFAULT_INTERACTIVE_CLIENT_ID = "795808c6-1180-4f93-b875-98e1e157863c"


def _resolve_interactive_client_id(config_client_id: str | None) -> str:
    """Resolution order: explicit config > env-var override > bundled default."""
    if config_client_id:
        return config_client_id
    return (
        os.environ.get("PQL_TEST_INTERACTIVE_CLIENT_ID")
        or PQL_TEST_DEFAULT_INTERACTIVE_CLIENT_ID
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

        if config.method == AuthMethod.INTERACTIVE:
            return InteractiveBrowserCredential(
                tenant_id=config.tenant_id,
                authority=authority,
                client_id=_resolve_interactive_client_id(config.client_id),
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
