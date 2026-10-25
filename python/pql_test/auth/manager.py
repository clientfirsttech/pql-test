# SPDX-License-Identifier: BUSL-1.1
"""
Authentication manager — Main interface for authentication operations.
"""

from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timezone
from typing import Optional

try:
    from azure.core.credentials import TokenCredential
except ImportError:
    TokenCredential = None  # type: ignore

from pql_test.auth.cloud_config import CloudConfig
from pql_test.auth.exceptions import TokenAcquisitionError
from pql_test.auth.factory import CredentialFactory
from pql_test.auth.models import AuthStatus, CredentialConfig
from pql_test.auth.store import CredentialStore

# Configure audit logger for authentication events
# Addresses OWASP A09 (Security Logging and Monitoring Failures)
_audit_logger = logging.getLogger("pql_test.auth.audit")
_audit_logger.setLevel(logging.INFO)


def _decode_jwt_expiry(token: str) -> Optional[datetime]:
    """
    Extract expiry timestamp from JWT token without signature verification.

    Decodes the JWT payload to read the 'exp' claim. This is safe for expiry
    validation because we don't verify the signature—we just read the expiry
    timestamp. Actual signature verification happens when Azure SDK uses the token.

    Addresses OWASP A07 (Authentication Failures) by validating token expiry
    locally without making service calls.

    Args:
        token: JWT access token string

    Returns:
        Token expiration datetime (UTC) or None if token is invalid/malformed

    Note:
        JWT format: header.payload.signature (all base64url-encoded)
        We decode the payload (middle part) to read the 'exp' claim
    """
    try:
        # JWT is header.payload.signature, we need the payload (middle part)
        parts = token.split(".")
        if len(parts) != 3:
            return None

        # Base64url decode the payload (add padding if needed)
        payload_b64 = parts[1]
        # Add padding: base64 requires length to be multiple of 4
        padding = "=" * (4 - len(payload_b64) % 4)
        payload_bytes = base64.urlsafe_b64decode(payload_b64 + padding)

        # Parse JSON payload
        payload = json.loads(payload_bytes.decode("utf-8"))

        # Extract 'exp' claim (Unix timestamp)
        exp_timestamp = payload.get("exp")
        if exp_timestamp is None:
            return None

        # Convert Unix timestamp to datetime (UTC)
        return datetime.fromtimestamp(exp_timestamp, tz=timezone.utc)

    except (ValueError, KeyError, json.JSONDecodeError):
        # Invalid token format or missing 'exp' claim
        return None


class AuthenticationManager:
    """
    Manages authentication for pql-test.

    Handles credential storage, token acquisition, and authentication state.
    Provides a unified interface for all authentication methods.
    """

    def __init__(self, namespace: str = "pql-test"):
        """
        Initialize authentication manager.

        Args:
            namespace: Keyring namespace for credential storage
        """
        self._store = CredentialStore(namespace)
        self._factory = CredentialFactory()
        self._cloud_config = CloudConfig()

    def save_credential(self, config: CredentialConfig) -> None:
        """
        Save credential configuration to secure storage.

        Args:
            config: Credential configuration to store

        Raises:
            CredentialStorageError: If credential cannot be stored
        """
        self._store.save(config)
        
        # Audit log: credential saved (OWASP A09: Security Logging)
        _audit_logger.info(
            "Credential saved: method=%s, tenant_id=%s, client_id=%s, account=%s",
            config.method.value if config.method else "unknown",
            config.tenant_id or "N/A",
            config.client_id or "N/A",
            config.account_name or "N/A",
        )

    def get_credential(self) -> Optional[TokenCredential]:
        """
        Get credential from stored configuration.

        Returns:
            TokenCredential instance or None if not authenticated

        Raises:
            CredentialConfigError: If stored config is invalid
        """
        config = self._store.load()
        if config is None:
            return None

        return self._factory.create(config, self._cloud_config)

    def get_access_token(
        self, scope: str = "https://analysis.windows.net/powerbi/api/.default"
    ) -> Optional[str]:
        """
        Get access token for the given scope.

        Args:
            scope: OAuth2 scope for the token

        Returns:
            Access token string or None if not authenticated

        Raises:
            TokenAcquisitionError: If token acquisition fails
        """
        credential = self.get_credential()
        if credential is None:
            _audit_logger.warning("Token acquisition failed: No credential stored")
            return None

        try:
            token_result = credential.get_token(scope)
            
            # Audit log: token acquired successfully
            _audit_logger.info(
                "Access token acquired: scope=%s",
                scope,
            )
            
            return token_result.token
        except Exception as e:
            # Audit log: token acquisition failed
            _audit_logger.error(
                "Token acquisition failed: scope=%s, error=%s",
                scope,
                str(e),
            )
            raise TokenAcquisitionError(
                f"Failed to acquire access token: {e}"
            ) from e

    def clear_credential(self) -> None:
        """
        Clear stored credential configuration.

        Raises:
            CredentialStorageError: If credential cannot be cleared
        """
        # Get config before deleting for audit log
        config = self._store.load()
        
        self._store.delete()
        
        # Audit log: credential cleared
        if config:
            _audit_logger.info(
                "Credential cleared: method=%s, account=%s",
                config.method.value if config.method else "unknown",
                config.account_name or "N/A",
            )
        else:
            _audit_logger.info("Credential cleared: No credential was stored")

    def get_status(self) -> AuthStatus:
        """
        Get current authentication status.

        Attempts to acquire a token and validates its expiry without making
        service calls. Addresses OWASP A07 (Authentication Failures) by
        checking token validity locally.

        Returns:
            AuthStatus with current authentication state, including:
            - token_expires_at: Token expiration time (if token acquired)
            - token_is_valid: Whether token is not expired (if token acquired)
        """
        config = self._store.load()

        if config is None:
            return AuthStatus(authenticated=False)

        # Try to get a token to validate it
        token_expires_at = None
        token_is_valid = False

        try:
            # Attempt to get token for Power BI scope
            token = self.get_access_token()
            if token:
                # Decode JWT to extract expiry (no signature verification needed)
                token_expires_at = _decode_jwt_expiry(token)
                if token_expires_at:
                    # Check if token is still valid (not expired)
                    now = datetime.now(timezone.utc)
                    token_is_valid = token_expires_at > now
        except (TokenAcquisitionError, Exception):
            # Token acquisition failed—leave token_is_valid=False
            # Don't raise—this is a status check, not a critical operation
            pass

        return AuthStatus(
            authenticated=True,
            method=config.method,
            account_name=config.account_name,
            tenant_id=config.tenant_id,
            client_id=config.client_id,
            environment=config.environment,
            token_expires_at=token_expires_at,
            token_is_valid=token_is_valid,
        )
