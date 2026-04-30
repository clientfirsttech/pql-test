"""Constants for pql-test CLI."""

# Auth scopes
SCOPE_FABRIC_DEFAULT = ["https://api.fabric.microsoft.com/.default"]
SCOPE_ONELAKE_DEFAULT = ["https://storage.azure.com/.default"]
SCOPE_AZURE_DEFAULT = ["https://management.azure.com/.default"]

# Auth authority
AUTH_DEFAULT_AUTHORITY = "https://login.microsoftonline.com/common"
AUTH_TENANT_AUTHORITY = "https://login.microsoftonline.com/"
AUTH_DEFAULT_CLIENT_ID = "5814bfb4-2705-4994-b8d6-39aabeb5eaeb"

# Identity types
IDENTITY_TYPE_USER = "user"
IDENTITY_TYPE_SERVICE_PRINCIPAL = "service_principal"
IDENTITY_TYPE_MANAGED_IDENTITY = "managed_identity"

# Auth info keys
IDENTITY_TYPE = "identity_type"
TENANT_ID = "tenant_id"
CLIENT_ID = "client_id"

# Environment variables
ENV_TENANT_ID = "PQL_TENANT_ID"
ENV_SPN_CLIENT_ID = "PQL_SPN_CLIENT_ID"
ENV_SPN_CLIENT_SECRET = "PQL_SPN_CLIENT_SECRET"
ENV_MANAGED_IDENTITY = "PQL_MANAGED_IDENTITY"

# Error codes
ERROR_AUTHENTICATION_FAILED = "AuthenticationFailed"
ERROR_UNAUTHORIZED = "Unauthorized"
ERROR_INVALID_INPUT = "InvalidInput"
