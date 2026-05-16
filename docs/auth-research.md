# Fabric CLI Authentication Research Findings

## Current pql-test Implementation

**Library**: `msal` (Microsoft Authentication Library)  
**Current Support**: Service principal with client secret only  
**Implementation**: `msal.ConfidentialClientApplication` with client credentials flow

```python
app = msal.ConfidentialClientApplication(
    client_id=client_id,
    client_credential=client_secret,
    authority=f"{login_url}/{tenant_id}",
)
result = app.acquire_token_for_client(scopes=[f"{resource_url}/.default"])
```

## Fabric CLI Authentication Pattern

Based on Fabric CLI documentation, they support:

1. **Interactive User Authentication** — Browser-based login with device code flow
2. **Service Principal with Secret** — Client credentials with client_id + client_secret
3. **Service Principal with Certificate** — Client credentials with PEM or P12 certificate
4. **Service Principal with Federated Credential** — OIDC token-based authentication
5. **Managed Identity** — System-assigned or user-assigned managed identity for Azure VMs

### Authentication Commands

- `fab auth login` — Interactive authentication with prompts for method selection
- `fab auth login -u <client_id> -p <secret> --tenant <tenant_id>` — Direct service principal login
- `fab auth logout` — Clear stored credentials
- `fab auth status` — View current authentication state

## Recommended Approach: Azure Identity SDK

**Migration Path**: `msal` → `azure-identity`

The `azure-identity` library is Microsoft's modern, unified authentication library that:
- Supports all authentication methods Fabric CLI uses
- Provides higher-level abstractions than MSAL
- Handles token caching and refresh automatically
- Works across Azure SDK services

### Key Credential Classes

```python
from azure.identity import (
    InteractiveBrowserCredential,      # Interactive browser login
    ClientSecretCredential,            # Service principal with secret
    CertificateCredential,             # Service principal with certificate
    ClientAssertionCredential,         # Service principal with federated token
    ManagedIdentityCredential,         # Managed identity
    DefaultAzureCredential,            # Automatic credential chain
)
```

### Token Caching

`azure-identity` provides built-in token caching:
- **Windows**: Uses Windows Credential Manager (DPAPI)
- **Linux/macOS**: Uses encrypted file-based cache at `~/.azure/msal_token_cache.bin`
- **Custom**: Can implement custom `TokenCache` for alternative storage

## Credential Storage Strategy

### Option 1: Platform Keyring (Recommended)

**Library**: `keyring` (Python standard for secure credential storage)  
**Storage**:
- Windows: Windows Credential Manager
- macOS: Keychain
- Linux: Secret Service API (GNOME Keyring, KWallet)

```python
import keyring

# Store
keyring.set_password("pql-test", "username", "credential_json")

# Retrieve
credential_json = keyring.get_password("pql-test", "username")

# Delete
keyring.delete_password("pql-test", "username")
```

### Option 2: Azure Identity Token Cache (Built-in)

Use `azure-identity`'s built-in `TokenCache` which handles token persistence automatically.

**Pros**:
- No additional library needed
- Automatic token refresh
- Consistent with Azure SDK patterns

**Cons**:
- Stores tokens, not credentials (need to re-authenticate when tokens expire after ~90 days)
- Less control over credential lifecycle

### Recommendation

**Hybrid Approach**:
1. Store credential configuration (method, client_id, tenant_id, certificate path) in `keyring`
2. Let `azure-identity` handle token caching automatically
3. When token refresh fails, use stored credential config to re-authenticate

## Authentication Flow Design

```
┌─────────────────────────────────────────┐
│   pql-test auth login                   │
│   ┌─────────────────────────────────┐   │
│   │ Select authentication method    │   │
│   └─────────────────────────────────┘   │
│              ↓                           │
│   ┌─────────────────────────────────┐   │
│   │ Acquire credential              │   │
│   │ (azure.identity.*)              │   │
│   └─────────────────────────────────┘   │
│              ↓                           │
│   ┌─────────────────────────────────┐   │
│   │ Store credential config         │   │
│   │ (keyring)                       │   │
│   └─────────────────────────────────┘   │
└─────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────┐
│   pql-test run-tests MODEL_PATH         │
│   ┌─────────────────────────────────┐   │
│   │ 1. Check CLI flags              │   │
│   │ 2. Check environment variables  │   │
│   │ 3. Check stored credentials     │   │
│   └─────────────────────────────────┘   │
│              ↓                           │
│   ┌─────────────────────────────────┐   │
│   │ Load credential from keyring    │   │
│   └─────────────────────────────────┘   │
│              ↓                           │
│   ┌─────────────────────────────────┐   │
│   │ Recreate azure.identity         │   │
│   │ credential object               │   │
│   └─────────────────────────────────┘   │
│              ↓                           │
│   ┌─────────────────────────────────┐   │
│   │ Get access token (cached)       │   │
│   └─────────────────────────────────┘   │
│              ↓                           │
│   ┌─────────────────────────────────┐   │
│   │ Execute DAX tests via XMLA      │   │
│   └─────────────────────────────────┘   │
└─────────────────────────────────────────┘
```

## Dependencies to Add

```
# requirements.txt
azure-identity>=1.19.0    # Modern Azure authentication with all credential types
keyring>=25.0.0           # Secure cross-platform credential storage
```

## Migration Strategy

1. Add `azure-identity` and `keyring` to dependencies (keep `msal` for backward compatibility)
2. Create new `auth` module with credential storage and provider abstraction
3. Implement auth subcommands (`login`, `logout`, `status`)
4. Update existing commands to check stored credentials after env vars
5. Maintain MSAL-based flow as fallback for CI/CD with environment variables
6. Deprecate direct `--client-secret` flag in favor of `auth login` (but keep for CI)

## Token Lifecycle

- **Access Token Lifetime**: 60-90 minutes (Azure AD default)
- **Refresh Token Lifetime**: Up to 90 days (if interactive login)
- **Service Principal**: No refresh token; must re-authenticate when access token expires
- **Managed Identity**: Tokens auto-refresh via Azure Instance Metadata Service

**Recommendation**: For service principals, store credentials (not just tokens) so we can acquire new access tokens without re-running `auth login`.
