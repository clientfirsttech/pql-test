# Authentication Architecture Design

## Overview

This document defines the authentication architecture for pql-test, implementing Fabric CLI-style persistent authentication while maintaining backward compatibility with existing environment variable and CLI flag patterns.

## Core Components

```
┌─────────────────────────────────────────────────────────────┐
│                      CLI Commands                           │
│  (pql_test_cli.py)                                         │
│  - auth login / logout / status                            │
│  - run-tests / retrieve-tests / retrieve-test              │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ↓
┌─────────────────────────────────────────────────────────────┐
│              AuthenticationManager                          │
│  (python/pql_test/auth_manager.py)                         │
│                                                             │
│  + get_credential() → TokenCredential                      │
│  + save_credential(config: CredentialConfig) → None        │
│  + clear_credential() → None                               │
│  + get_credential_status() → AuthStatus                    │
│  + get_access_token(scope: str) → str                      │
└──────────────────┬──────────────────────────────────────────┘
                   │
        ┌──────────┴───────────┬──────────────┬─────────────┐
        ↓                      ↓              ↓             ↓
┌────────────────┐  ┌──────────────────┐  ┌────────────┐  ┌──────────────┐
│CredentialStore │  │CredentialFactory │  │TokenCache  │  │CloudConfig   │
│                │  │                  │  │            │  │              │
│ (keyring)      │  │ (azure.identity) │  │ (built-in) │  │ (sovereign)  │
└────────────────┘  └──────────────────┘  └────────────┘  └──────────────┘
```

## Module Structure

```
python/
├── pql_test/
│   ├── __init__.py
│   ├── auth/
│   │   ├── __init__.py
│   │   ├── manager.py          # AuthenticationManager (main interface)
│   │   ├── store.py            # CredentialStore (keyring wrapper)
│   │   ├── factory.py          # CredentialFactory (azure.identity wrapper)
│   │   ├── models.py           # Data classes (CredentialConfig, AuthStatus)
│   │   └── cloud_config.py     # Cloud environment configuration
│   ├── pql_test_cli.py         # CLI entry point (updated with auth commands)
│   └── pql_test_runner.py      # Core runner (updated to use AuthenticationManager)
└── tests/
    └── auth/
        ├── test_manager.py
        ├── test_store.py
        ├── test_factory.py
        └── test_integration.py
```

## Data Models

### CredentialConfig

```python
from dataclasses import dataclass
from enum import Enum
from typing import Optional

class AuthMethod(Enum):
    """Supported authentication methods."""
    INTERACTIVE = "interactive"
    SERVICE_PRINCIPAL_SECRET = "service_principal_secret"
    SERVICE_PRINCIPAL_CERT = "service_principal_cert"
    SERVICE_PRINCIPAL_FEDERATED = "service_principal_federated"
    MANAGED_IDENTITY = "managed_identity"

@dataclass
class CredentialConfig:
    """Credential configuration stored in keyring."""
    method: AuthMethod
    tenant_id: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None  # Only for service principal with secret
    certificate_path: Optional[str] = None  # Only for certificate auth
    certificate_password: Optional[str] = None  # Only for encrypted cert
    federated_token: Optional[str] = None  # Only for federated credential
    use_system_assigned_identity: bool = False  # For managed identity
    environment: str = "Public"  # Cloud environment
    account_name: Optional[str] = None  # Display name for status
```

### AuthStatus

```python
@dataclass
class AuthStatus:
    """Current authentication status."""
    authenticated: bool
    method: Optional[AuthMethod] = None
    account_name: Optional[str] = None
    tenant_id: Optional[str] = None
    client_id: Optional[str] = None
    environment: str = "Public"
    token_expires_at: Optional[datetime] = None
    token_is_valid: bool = False
```

## AuthenticationManager API

### Primary Methods

```python
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
            StorageError: If credential cannot be stored
        """
        pass
    
    def get_credential(self) -> Optional[TokenCredential]:
        """
        Get credential from stored configuration.
        
        Returns:
            TokenCredential instance or None if not authenticated
            
        Raises:
            CredentialError: If stored config is invalid
        """
        pass
    
    def get_access_token(
        self, 
        scope: str = "https://analysis.windows.net/powerbi/api/.default"
    ) -> Optional[str]:
        """
        Get access token for the given scope.
        
        Args:
            scope: OAuth2 scope for the token
            
        Returns:
            Access token string or None if not authenticated
            
        Raises:
            AuthenticationError: If token acquisition fails
        """
        pass
    
    def clear_credential(self) -> None:
        """
        Clear stored credential configuration.
        
        Raises:
            StorageError: If credential cannot be cleared
        """
        pass
    
    def get_status(self) -> AuthStatus:
        """
        Get current authentication status.
        
        Returns:
            AuthStatus with current authentication state
        """
        pass
```

## CredentialStore (Keyring Wrapper)

```python
import keyring
import json
from typing import Optional

class CredentialStore:
    """Secure credential storage using platform keyring."""
    
    def __init__(self, namespace: str = "pql-test"):
        self._namespace = namespace
        self._service_name = f"pql-test-{namespace}"
    
    def save(self, config: CredentialConfig) -> None:
        """
        Save credential config to keyring.
        
        Stores as JSON under service=pql-test, username=default.
        """
        config_json = json.dumps(asdict(config))
        keyring.set_password(self._service_name, "default", config_json)
    
    def load(self) -> Optional[CredentialConfig]:
        """Load credential config from keyring."""
        config_json = keyring.get_password(self._service_name, "default")
        if config_json is None:
            return None
        config_dict = json.loads(config_json)
        # Convert method string back to enum
        config_dict["method"] = AuthMethod(config_dict["method"])
        return CredentialConfig(**config_dict)
    
    def delete(self) -> None:
        """Delete stored credential config."""
        try:
            keyring.delete_password(self._service_name, "default")
        except keyring.errors.PasswordDeleteError:
            pass  # Already deleted
```

## CredentialFactory (azure.identity Wrapper)

```python
from azure.identity import (
    InteractiveBrowserCredential,
    ClientSecretCredential,
    CertificateCredential,
    ClientAssertionCredential,
    ManagedIdentityCredential,
)

class CredentialFactory:
    """Factory for creating azure.identity credential objects."""
    
    def create(self, config: CredentialConfig, cloud_config: CloudConfig) -> TokenCredential:
        """
        Create TokenCredential from configuration.
        
        Args:
            config: Credential configuration
            cloud_config: Cloud environment configuration
            
        Returns:
            TokenCredential instance
            
        Raises:
            ValueError: If config is invalid for the selected method
        """
        if config.method == AuthMethod.INTERACTIVE:
            return InteractiveBrowserCredential(
                tenant_id=config.tenant_id,
                authority=cloud_config.get_authority(config.environment),
            )
        
        elif config.method == AuthMethod.SERVICE_PRINCIPAL_SECRET:
            if not all([config.tenant_id, config.client_id, config.client_secret]):
                raise ValueError("Service principal with secret requires tenant_id, client_id, and client_secret")
            return ClientSecretCredential(
                tenant_id=config.tenant_id,
                client_id=config.client_id,
                client_secret=config.client_secret,
                authority=cloud_config.get_authority(config.environment),
            )
        
        elif config.method == AuthMethod.SERVICE_PRINCIPAL_CERT:
            if not all([config.tenant_id, config.client_id, config.certificate_path]):
                raise ValueError("Service principal with certificate requires tenant_id, client_id, and certificate_path")
            return CertificateCredential(
                tenant_id=config.tenant_id,
                client_id=config.client_id,
                certificate_path=config.certificate_path,
                password=config.certificate_password,
                authority=cloud_config.get_authority(config.environment),
            )
        
        elif config.method == AuthMethod.SERVICE_PRINCIPAL_FEDERATED:
            if not all([config.tenant_id, config.client_id, config.federated_token]):
                raise ValueError("Federated credential requires tenant_id, client_id, and federated_token")
            # Note: azure-identity uses ClientAssertionCredential for federated tokens
            def token_provider():
                return config.federated_token
            return ClientAssertionCredential(
                tenant_id=config.tenant_id,
                client_id=config.client_id,
                func=token_provider,
                authority=cloud_config.get_authority(config.environment),
            )
        
        elif config.method == AuthMethod.MANAGED_IDENTITY:
            if config.use_system_assigned_identity:
                return ManagedIdentityCredential()
            else:
                if not config.client_id:
                    raise ValueError("User-assigned managed identity requires client_id")
                return ManagedIdentityCredential(client_id=config.client_id)
        
        else:
            raise ValueError(f"Unsupported authentication method: {config.method}")
```

## CloudConfig

```python
class CloudConfig:
    """Cloud environment configuration for sovereign clouds."""
    
    ENVIRONMENTS = {
        "Public": {
            "authority": "https://login.microsoftonline.com",
            "resource": "https://analysis.windows.net/powerbi/api",
        },
        "USGov": {
            "authority": "https://login.microsoftonline.us",
            "resource": "https://analysis.usgovcloudapi.net/powerbi/api",
        },
        "USGovHigh": {
            "authority": "https://login.microsoftonline.us",
            "resource": "https://high.analysis.usgovcloudapi.net/powerbi/api",
        },
        "USGovDoD": {
            "authority": "https://login.microsoftonline.us",
            "resource": "https://mil.analysis.usgovcloudapi.net/powerbi/api",
        },
        "Germany": {
            "authority": "https://login.microsoftonline.de",
            "resource": "https://analysis.cloudapi.de/powerbi/api",
        },
        "China": {
            "authority": "https://login.chinacloudapi.cn",
            "resource": "https://analysis.chinacloudapi.cn/powerbi/api",
        },
    }
    
    def get_authority(self, environment: str) -> str:
        """Get Azure AD authority URL for environment."""
        return self.ENVIRONMENTS.get(environment, self.ENVIRONMENTS["Public"])["authority"]
    
    def get_resource_scope(self, environment: str) -> str:
        """Get Power BI resource scope for environment."""
        resource = self.ENVIRONMENTS.get(environment, self.ENVIRONMENTS["Public"])["resource"]
        return f"{resource}/.default"
```

## Credential Resolution Priority

When a command like `run-tests` is executed, credentials are resolved in this order:

1. **CLI flags** (`--tenant-id`, `--client-id`, `--client-secret`) — Highest priority
2. **Environment variables** (`PQL_TENANT_ID`, `PQL_CLIENT_ID`, `PQL_CLIENT_SECRET`)
3. **Stored credentials** (from `auth login`) — Lowest priority

```python
def resolve_authentication(
    cli_tenant_id: Optional[str],
    cli_client_id: Optional[str],
    cli_client_secret: Optional[str],
    auth_manager: AuthenticationManager,
) -> Optional[str]:
    """
    Resolve authentication and return access token.
    
    Priority:
      1. CLI flags
      2. Environment variables
      3. Stored credentials
    
    Returns:
        Access token string or None
    """
    # 1. CLI flags (existing MSAL flow for backward compatibility)
    if all([cli_tenant_id, cli_client_id, cli_client_secret]):
        return _acquire_service_principal_token(
            cli_tenant_id, cli_client_id, cli_client_secret
        )
    
    # 2. Environment variables (existing flow)
    env_tenant = os.getenv("PQL_TENANT_ID")
    env_client = os.getenv("PQL_CLIENT_ID")
    env_secret = os.getenv("PQL_CLIENT_SECRET")
    if all([env_tenant, env_client, env_secret]):
        return _acquire_service_principal_token(
            env_tenant, env_client, env_secret
        )
    
    # 3. Stored credentials (new auth login flow)
    return auth_manager.get_access_token()
```

## CLI Command Structure

```python
@click.group()
def auth():
    """Manage authentication for pql-test."""
    pass

@auth.command("login")
@click.option("--method", type=click.Choice([...]), help="Authentication method")
@click.option("-u", "--user", "--client-id", help="User or client ID")
@click.option("-p", "--password", help="Password, secret, or certificate password")
@click.option("--tenant", "--tenant-id", help="Azure AD tenant ID")
@click.option("--certificate", help="Path to certificate file (.pem or .p12)")
@click.option("--federated-token", help="Federated credential token")
@click.option("--identity", is_flag=True, help="Use managed identity")
@click.option("--environment", help="Cloud environment")
def login(...):
    """Log in to pql-test."""
    pass

@auth.command("logout")
def logout():
    """Log out and clear stored credentials."""
    pass

@auth.command("status")
def status():
    """Show current authentication status."""
    pass
```

## Error Handling

```python
class AuthenticationError(Exception):
    """Base class for authentication errors."""
    pass

class CredentialStorageError(AuthenticationError):
    """Error storing or retrieving credentials."""
    pass

class TokenAcquisitionError(AuthenticationError):
    """Error acquiring access token."""
    pass

class CredentialConfigError(AuthenticationError):
    """Invalid credential configuration."""
    pass
```

## Testing Strategy

1. **Unit Tests** — Test each component in isolation with mocks
   - `test_store.py` — Keyring operations with mock backend
   - `test_factory.py` — Credential creation with mock configs
   - `test_manager.py` — Manager orchestration with mocked dependencies

2. **Integration Tests** — Test end-to-end flows
   - `test_integration.py` — Full auth login → get token → logout flow

3. **Mock Keyring** — Use `keyring.backends.null.Keyring` for tests
   ```python
   keyring.set_keyring(keyring.backends.null.Keyring())
   ```

## Backward Compatibility

- Existing commands continue to work with `--tenant-id`, `--client-id`, `--client-secret` flags
- Environment variables `PQL_*` continue to work
- MSAL-based service principal flow remains as fallback for CI/CD
- New `auth` commands are opt-in; existing users see no breaking changes

## Security Considerations

1. **Secrets in Keyring** — Client secrets stored in platform keyring (encrypted at rest)
2. **Certificate Handling** — Certificate passwords stored in keyring, not in plain text
3. **Token Cache** — azure-identity handles token caching with encryption
4. **Federated Tokens** — Short-lived, not stored long-term
5. **CLI History** — Secrets passed via stdin prompts, not command args (when interactive)

## Future Enhancements

1. **Multiple Profiles** — Support multiple stored credentials with named profiles
2. **Credential Rotation** — Automatic detection of expired certificates/secrets
3. **SSO Integration** — Integration with Azure CLI or VS Code authentication
4. **Audit Logging** — Log authentication events for compliance
