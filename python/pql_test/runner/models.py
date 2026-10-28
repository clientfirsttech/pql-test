# SPDX-License-Identifier: AGPL-3.0-only
"""
Data models for PQL Test Runner.

This module contains all dataclasses and enums used throughout the runner package:

- Environment: Cloud environment enum (Public, USGov, China, etc.)
- Endpoints: API and auth endpoints for each environment
- ModelIdentifier: Parsed model path (filesystem, local/, Fabric-style)
- PqlTest: Single DAX test file descriptor
- TestResult: Single test execution result
- TestSuite: Full test run summary
- XmlaConnectionOptions: XMLA connection parameters
- ResolvedXmlaConnection: Resolved XMLA connection with auth
- LocalPbiInstance: Local Power BI Desktop instance descriptor
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import ClassVar, Optional

__all__ = [
    "Endpoints",
    "Environment",
    "LocalPbiInstance",
    "ModelIdentifier",
    "PqlTest",
    "ResolvedXmlaConnection",
    "TestResult",
    "TestSuite",
    "XmlaConnectionOptions",
    "get_api_endpoints",
]


# ---------------------------------------------------------------------------
# Cloud environment support
# ---------------------------------------------------------------------------


class Environment(str, Enum):
    """Supported Power BI cloud environments."""

    PUBLIC = "Public"
    GERMANY = "Germany"
    CHINA = "China"
    US_GOV = "USGov"
    US_GOV_HIGH = "USGovHigh"
    US_GOV_DOD = "USGovDoD"


@dataclass
class Endpoints:
    """API and auth endpoints for a Power BI cloud environment."""

    api_prefix: str
    resource_url: str
    login_url: str


def get_api_endpoints(environment: Environment = Environment.PUBLIC) -> Endpoints:
    """Return the correct API and auth endpoints for the given cloud environment."""
    if environment == Environment.GERMANY:
        return Endpoints(
            api_prefix="https://api.powerbi.de",
            resource_url="https://analysis.cloudapi.de/powerbi/api",
            login_url="https://login.microsoftonline.com",
        )
    if environment == Environment.CHINA:
        return Endpoints(
            api_prefix="https://api.powerbi.cn",
            resource_url="https://analysis.chinacloudapi.cn/powerbi/api",
            login_url="https://login.partner.microsoftonline.cn",
        )
    if environment == Environment.US_GOV:
        return Endpoints(
            api_prefix="https://api.powerbigov.us",
            resource_url="https://analysis.usgovcloudapi.net/powerbi/api",
            login_url="https://login.microsoftonline.com",
        )
    if environment == Environment.US_GOV_HIGH:
        return Endpoints(
            api_prefix="https://api.high.powerbigov.us",
            resource_url="https://analysis.high.usgovcloudapi.net/powerbi/api",
            login_url="https://login.microsoftonline.us",
        )
    if environment == Environment.US_GOV_DOD:
        return Endpoints(
            api_prefix="https://api.mil.powerbi.us",
            resource_url="https://analysis.dod.usgovcloudapi.net/powerbi/api",
            login_url="https://login.microsoftonline.us",
        )
    # Default: Public commercial cloud
    return Endpoints(
        api_prefix="https://api.powerbi.com",
        resource_url="https://analysis.windows.net/powerbi/api",
        login_url="https://login.microsoftonline.com",
    )


# ---------------------------------------------------------------------------
# Model identifier parsing
# ---------------------------------------------------------------------------


@dataclass
class ModelIdentifier:
    """Parsed model identifier from the CLI model_path argument.

    Supports three formats:

    * ``local/<model_name>`` — connect to a locally-open Power BI Desktop
      instance matching *model_name* (case-insensitive).  File-based test
      discovery is skipped; only live XMLA discovery is used.
    * ``<workspace>.Workspace/<model>.SemanticModel`` — Fabric-style path
      using workspace and semantic-model display names directly.
    * A regular filesystem path — traditional PBIP root directory.
    """

    kind: str
    """One of ``'local'``, ``'service'``, or ``'path'``."""
    model_name: Optional[str] = None
    """Semantic-model display name (``local`` and ``service`` modes)."""
    workspace_name: Optional[str] = None
    """Workspace display name (``service`` mode only)."""
    raw: str = ""
    """The original model_path string as supplied by the user."""


# ---------------------------------------------------------------------------
# Test data types
# ---------------------------------------------------------------------------


@dataclass
class PqlTest:
    """A single DAX test file discovered in a PBIP model."""

    name: str
    """Test suite name derived from the file stem (e.g. 'Calculations.DEV.Tests')."""
    file_path: str
    """Absolute path to the .dax source file."""
    source: str
    """Raw DAX source."""
    description: Optional[str] = None
    """Optional description (FUNCTION name when present in the DAX source)."""
    impersonated_user_name: Optional[str] = None
    """RLS impersonation user (AAD UPN) from PQL.Assert.RetrieveTestsV2.  Used with service endpoints."""
    role_name: Optional[str] = None
    """RLS role name from PQL.Assert.RetrieveTestsV2 (PQLAssert_RoleName annotation).  Used with local connections."""


@dataclass
class TestResult:
    """Result of executing a single DAX assertion row."""

    # Suppress pytest collection: name starts with 'Test' but this is a dataclass
    __test__: ClassVar[bool] = False

    test_name: str
    passed: bool
    message: str
    skipped: bool = False
    error: Optional[str] = None
    duration_ms: Optional[float] = None
    actual: Optional[str] = None
    expected: Optional[str] = None
    suite_name: Optional[str] = None


@dataclass
class TestSuite:
    """Summary of a full test run against a model."""

    # Suppress pytest collection: name starts with 'Test' but this is a model
    # used by tests and by the runner, not a real test case.
    __test__: ClassVar[bool] = False

    model_path: str
    tests: list[PqlTest]
    results: list[TestResult]
    passed: int
    failed: int
    skipped: int
    total: int


# ---------------------------------------------------------------------------
# XMLA connection types
# ---------------------------------------------------------------------------


@dataclass
class XmlaConnectionOptions:
    """
    Connection parameters for XMLA execution.

    For remote Power BI Premium / Fabric connections, tenant_id and
    workspace_id are required, plus EITHER dataset_id OR dataset_name
    (the dataset's display name as it appears in the workspace).  When
    only dataset_name is supplied the resolver looks up the dataset via
    REST so the caller doesn't need to store GUIDs anywhere.

    client_id + client_secret are used to acquire an OAuth2 bearer
    token via the MSAL service-principal (client-credentials) flow.
    This is the same authentication pattern used by Invoke-DQVTesting
    when running in CI/CD pipelines against cloud-hosted models.

    access_token is an optional pre-acquired bearer token.  When set, the
    downstream resolver skips MSAL and uses this token directly.  Populated
    by ``_resolve_authentication_with_stored_credentials`` when a non-secret
    stored credential (interactive, certificate, federated, managed identity)
    is found — see tasks/unified-auth-runtime-epic.md.
    """

    tenant_id: Optional[str] = None
    workspace_id: Optional[str] = None
    dataset_id: Optional[str] = None
    dataset_name: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    environment: Environment = Environment.PUBLIC
    access_token: Optional[str] = None


@dataclass
class ResolvedXmlaConnection:
    """Resolved XMLA server, catalog, and optional auth details."""

    server: str
    catalog: str
    tenant_id: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    access_token: Optional[str] = None
    effective_user_name: Optional[str] = None
    """AAD UPN passed as EffectiveUserName; used for service-endpoint RLS simulation."""
    roles: Optional[str] = None
    """Semi-colon-separated role name(s) passed as Roles=; used for local-AS RLS simulation."""


@dataclass
class LocalPbiInstance:
    """
    A Power BI Desktop instance open on the local machine.

    Mirrors the custom object returned by Invoke-DQVTesting's
    Get-PowerBIFilesOpened for each detected process.
    """

    model_name: str
    """Window title with " - Power BI Desktop" suffix stripped."""
    server: str
    """XMLA server string, e.g. "localhost:63402"."""
    catalog: str
    """Catalog name or GUID from DBSCHEMA_CATALOGS."""
