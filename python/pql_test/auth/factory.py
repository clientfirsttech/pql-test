"""
Credential factory for creating azure.identity credential objects.
"""

from __future__ import annotations

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
