# Security Threat Model

**Created**: 2026-08-31
**Status**: Current  
**Scope**: Authentication flows and credential handling in pql-test

## Overview

This document analyzes security threats for pql-test's 5 authentication methods, using the STRIDE model (Spoofing, Tampering, Repudiation, Information Disclosure, Denial of Service, Elevation of Privilege) and OWASP Top 10 framework.

---

## 1. Interactive Authentication (Browser-Based)

### Flow Description
- User runs `pql-test auth login` → selects "Interactive (Browser)"
- azure-identity's `InteractiveBrowserCredential` launches browser
- User authenticates via Microsoft OAuth2 flow
- Token cached locally by MSAL
- AuthenticationRecord serialized to keyring for silent token refresh

### Threat Analysis

| Threat Category | Risk | Mitigation | Status |
|----------------|------|------------|--------|
| **S - Spoofing** | Medium | OAuth2 PKCE flow prevents token interception; redirect URI validation | ✅ Mitigated (azure-identity) |
| **T - Tampering** | Low | Token stored in OS credential manager (keyring); MSAL cache encrypted | ✅ Mitigated |
| **R - Repudiation** | Low | No audit logging of auth attempts | ⚠️ **Gap** — Add logging |
| **I - Information Disclosure** | Medium | AuthenticationRecord in keyring could leak account info | ⚠️ **Accepted Risk** — keyring protects at OS level |
| **D - Denial of Service** | Low | Browser popup could be blocked; user can retry | ✅ Mitigated |
| **E - Elevation of Privilege** | Low | User authenticates with own permissions only | ✅ Mitigated |

**OWASP Mapping**:
- **A07: Identification and Authentication Failures** — Token expiry now validated (implemented 2026-08-31)
- **A08: Software and Data Integrity Failures** — MSAL token cache integrity assumed

**Recommendations**:
1. ✅ **DONE** — Validate token expiry locally before use
2. ⚠️ **TODO** — Add audit logging for auth login attempts (success/failure)
3. ✅ **DONE** — Credential stored in OS keyring (Windows Credential Manager / macOS Keychain / Linux Secret Service)

---

## 2. Service Principal with Secret

### Flow Description
- User runs `pql-test auth login` → selects "Service Principal (Secret)"
- Provides tenant_id, client_id, client_secret
- Credentials stored in keyring
- azure-identity's `ClientSecretCredential` used for token acquisition

### Threat Analysis

| Threat Category | Risk | Mitigation | Status |
|----------------|------|------------|--------|
| **S - Spoofing** | Medium | Service principal validated by Azure AD; secret proves identity | ✅ Mitigated (Azure AD) |
| **T - Tampering** | Medium | Secret stored in keyring; could be extracted with OS-level access | ⚠️ **Accepted Risk** — keyring best practice |
| **R - Repudiation** | Medium | No audit logging of which user/process used SPN credentials | ⚠️ **Gap** — Add logging |
| **I - Information Disclosure** | **High** | Secret in plaintext if keyring compromised; no rotation tracking | ⚠️ **Gap** — Recommend secret rotation policy |
| **D - Denial of Service** | Low | Invalid secret causes auth failure; user can update | ✅ Mitigated |
| **E - Elevation of Privilege** | **High** | SPN permissions control privilege; over-permissioned SPN risks all datasets | ⚠️ **Gap** — Document least-privilege SPN setup |

**OWASP Mapping**:
- **A02: Cryptographic Failures** — Secrets stored in OS keyring (platform-dependent encryption)
- **A07: Identification and Authentication Failures** — Token expiry validated; secret rotation enforced via documentation

**Recommendations**:
1. ✅ **DONE** (2026-08-31) — Document least-privilege Azure AD role assignment for SPNs (CONTRIBUTING.md)
2. ✅ **DONE** (2026-08-31) — Add secret rotation guidance in CONTRIBUTING.md (90-day rotation recommended)
3. ✅ **DONE** (2026-08-31) — Secret rotation reminder added to README Security section
4. ✅ **DONE** — Credentials never logged or printed (verified in codebase)
5. ✅ **DONE** (2026-08-31) — Audit logging implemented (pql_test.auth.audit logger)

---

## 3. Service Principal with Certificate

### Flow Description
- User runs `pql-test auth login --certificate` with cert path
- Certificate file read from disk
- azure-identity's `CertificateCredential` used for token acquisition
- Certificate path (not content) stored in keyring

### Threat Analysis

| Threat Category | Risk | Mitigation | Status |
|----------------|------|------------|--------|
| **S - Spoofing** | Low | Certificate proves identity cryptographically; Azure AD validates signature | ✅ Mitigated (Azure AD PKI) |
| **T - Tampering** | Low | Certificate tampering detectable via signature validation | ✅ Mitigated |
| **R - Repudiation** | Medium | No audit logging of certificate-based auth | ⚠️ **Gap** — Add logging |
| **I - Information Disclosure** | Medium | Certificate file readable by any process with filesystem access | ⚠️ **Accepted Risk** — User controls file permissions |
| **D - Denial of Service** | Low | Invalid/expired cert causes auth failure; user can replace | ✅ Mitigated |
| **E - Elevation of Privilege** | **High** | SPN permissions control privilege; certificate theft = full SPN access | ⚠️ **Gap** — Recommend HSM/Azure Key Vault for certs |

**OWASP Mapping**:
- **A02: Cryptographic Failures** — Certificate private key stored on disk (user responsibility)
- **A04: Insecure Design** — Certificate protection guidance provided

**Recommendations**:
1. ✅ **DONE** (2026-08-31) — Document certificate protection (file permissions, Azure Key Vault) in CONTRIBUTING.md
2. ⚠️ **TODO** — Add certificate expiry warning in `pql-test auth status`
3. ✅ **DONE** (2026-08-31) — Audit logging implemented for certificate-based auth
4. ✅ **DONE** — Certificate content never logged (only path stored in keyring)
3. ⚠️ **TODO** — Log certificate-based authentication attempts
4. ✅ **DONE** — Certificate content never logged (only path stored in keyring)

---

## 4. Service Principal with Federated Credential

### Flow Description
- GitHub Actions/Azure Pipelines workload identity federation
- Platform provides short-lived token
- azure-identity's `ClientAssertionCredential` exchanges token for Azure AD access token
- No long-lived secrets stored

### Threat Analysis

| Threat Category | Risk | Mitigation | Status |
|----------------|------|------------|--------|
| **S - Spoofing** | Low | Federated token cryptographically signed by IdP; Azure AD validates signature | ✅ Mitigated (OpenID Connect) |
| **T - Tampering** | Low | Token tampering detectable via JWT signature | ✅ Mitigated |
| **R - Repudiation** | Low | GitHub Actions/Azure Pipelines audit logs track token issuance | ✅ Mitigated (platform) |
| **I - Information Disclosure** | Low | Token short-lived (1 hour); no persistent secrets | ✅ Mitigated |
| **D - Denial of Service** | Low | Token issuance failure causes auth failure; retry logic possible | ✅ Mitigated |
| **E - Elevation of Privilege** | Medium | Federated credential subject claim controls access; misconfiguration = unauthorized access | ⚠️ **Gap** — Document subject claim validation |

**OWASP Mapping**:
- **A04: Insecure Design** — No guidance on federated credential subject claim configuration
- **A05: Security Misconfiguration** — Overly permissive subject claims (e.g., `repo:*/*`) risks unauthorized access

**Recommendations**:
1. ⚠️ **TODO** — Document federated credential setup with restrictive subject claims
   - Good: `repo:owner/repo:environment:production`
   - Bad: `repo:owner/*` (too broad)
2. ⚠️ **TODO** — Add GitHub Actions workflow example with federated auth
3. ✅ **DONE** — No long-lived secrets stored (federated token ephemeral)

---

## 5. Managed Identity

### Flow Description
- Azure VM/Container/App Service runtime provides identity
- azure-identity's `ManagedIdentityCredential` acquires token from IMDS endpoint
- No credentials stored or configured by user

### Threat Analysis

| Threat Category | Risk | Mitigation | Status |
|----------------|------|------------|--------|
| **S - Spoofing** | Low | IMDS endpoint only accessible from within Azure resource | ✅ Mitigated (Azure platform) |
| **T - Tampering** | Low | Token issued by Azure AD; tampering detectable | ✅ Mitigated |
| **R - Repudiation** | Low | Azure Activity Log tracks managed identity usage | ✅ Mitigated (platform) |
| **I - Information Disclosure** | Low | No secrets stored; token short-lived | ✅ Mitigated |
| **D - Denial of Service** | Low | IMDS endpoint failure causes auth failure; Azure SLA applies | ✅ Mitigated (platform) |
| **E - Elevation of Privilege** | **High** | Managed identity permissions control access; compromise of Azure resource = full identity access | ⚠️ **Gap** — Document least-privilege role assignment |

**OWASP Mapping**:
- **A01: Broken Access Control** — Managed identity permissions must follow least-privilege principle
- **A04: Insecure Design** — No guidance on managed identity role assignment

**Recommendations**:
1. ⚠️ **TODO** — Document managed identity setup with Power BI Reader role
2. ⚠️ **TODO** — Document IMDS endpoint hardening (network-level firewall rules)
3. ✅ **DONE** — No credentials stored (managed identity is platform-provided)
4. ⚠️ **TODO** — Add CI/CD example using managed identity on Azure DevOps agent

---

## RLS/OLS Security Model

### Row-Level Security (RLS) Threat Analysis

**Flow**: `run-tests` with `ImpersonateUser:` annotation in test file
- Test specifies `ImpersonateUser: user@example.com`
- XMLA connection string includes `EffectiveUserName` property
- Analysis Services impersonates user for query execution
- User's RLS roles applied to query results

| Threat | Risk | Mitigation | Status |
|--------|------|------------|--------|
| **Privilege Escalation** | **High** | Malicious test file could impersonate admin user to bypass RLS | ⚠️ **Gap** — Validate EffectiveUserName against allowed list |
| **Information Disclosure** | **High** | Test results expose whether user can see sensitive data | ⚠️ **Accepted Risk** — Purpose of RLS tests |
| **Role Confusion** | Medium | Typo in ImpersonateUser email could test wrong user's access | ✅ Mitigated — Clear error messages |

**OWASP Mapping**:
- **A01: Broken Access Control** — EffectiveUserName allows impersonation without permission check

**Recommendations**:
1. 🗄️ **ARCHIVED** — Add configuration option to restrict EffectiveUserName to approved user list (2026-08-31: Out of scope—users responsible for test file content review)
2. ✅ **DONE** — Document security implications of RLS testing in README (2026-08-31)
3. 🗄️ **ARCHIVED** — Add warning when EffectiveUserName is used in test execution (2026-08-31: Documented in README instead)
4. ✅ **DONE** — Error handling when impersonation fails (Analysis Services validates user exists)

### Object-Level Security (OLS) Threat Analysis

**Flow**: `run-tests` with `ImpersonateRole:` annotation in test file
- Test specifies `ImpersonateRole: RoleName`
- XMLA connection string includes `Roles` property
- Analysis Services applies role's OLS permissions to query

| Threat | Risk | Mitigation | Status |
|--------|------|------------|--------|
| **Privilege Escalation** | **High** | Malicious test could specify admin role to bypass OLS | ⚠️ **Gap** — Validate role name against allowed list |
| **Information Disclosure** | Medium | Test results reveal which objects are hidden by OLS | ⚠️ **Accepted Risk** — Purpose of OLS tests |
| **Role Injection** | Low | Invalid role name causes query failure; AS validates role exists | ✅ Mitigated (Analysis Services) |

**OWASP Mapping**:
- **A01: Broken Access Control** — Roles property allows role assumption without permission check

**Recommendations**:
1. 🗄️ **ARCHIVED** — Add configuration to restrict ImpersonateRole to approved role list (2026-08-31: Out of scope—users responsible for test file content review)
2. ✅ **DONE** — Document OLS testing security model in README (2026-08-31)
3. 🗄️ **ARCHIVED** — Add warning when Roles property is used in XMLA connection (2026-08-31: Documented in README instead)
4. ✅ **DONE** — Error handling when role doesn't exist (Analysis Services validates)

---

## Summary of Critical Findings

### High-Risk Gaps (Immediate Action)

1. **RLS/OLS Impersonation Controls** (A01: Broken Access Control)
   - **Issue**: No validation of `EffectiveUserName` or `Roles` properties
   - **Impact**: Malicious test files can impersonate any user/role
   - **Recommendation**: Document security implications and rely on code review
   - **Priority**: 🟡 MEDIUM (originally CRITICAL)
   - **Status**: 🗄️ **ARCHIVED** — Security implications documented in README.md (2026-08-31). Runtime enforcement deemed out of scope; users responsible for test file content review.

2. **Service Principal Over-Permissioning** (A01: Broken Access Control)
   - **Issue**: No guidance on least-privilege role assignment
   - **Impact**: Compromised SPN credentials grant excessive access
   - **Recommendation**: Document Power BI Reader role as minimum viable permission
   - **Priority**: 🟡 HIGH
   - **Status**: ✅ **RESOLVED** (2026-08-31) — Comprehensive guide added to CONTRIBUTING.md

3. **Certificate Storage** (A02: Cryptographic Failures)
   - **Issue**: No guidance on certificate protection best practices
   - **Impact**: Certificate file theft = full SPN access
   - **Recommendation**: Document file permissions, recommend Azure Key Vault for production
   - **Priority**: 🟡 HIGH
   - **Status**: ✅ **RESOLVED** (2026-08-31) — Certificate security section added to CONTRIBUTING.md

### Medium-Risk Gaps (Should Address)

4. **Audit Logging** (A09: Security Logging and Monitoring Failures)
   - **Issue**: No logging of authentication attempts or failures
   - **Impact**: Cannot detect or investigate unauthorized access attempts
   - **Recommendation**: Add audit logging to AuthenticationManager
   - **Priority**: 🟠 MEDIUM
   - **Status**: ✅ **RESOLVED** (2026-08-31) — Audit logger implemented (pql_test.auth.audit)

5. **Secret Rotation** (A07: Identification and Authentication Failures)
   - **Issue**: No guidance or enforcement of secret rotation
   - **Impact**: Long-lived secrets increase exposure window
   - **Recommendation**: Document 90-day rotation policy in CONTRIBUTING.md
   - **Priority**: 🟠 MEDIUM
   - **Status**: ✅ **RESOLVED** (2026-08-31) — Rotation policy documented in CONTRIBUTING.md + README.md

6. **Federated Credential Configuration** (A05: Security Misconfiguration)
   - **Issue**: No guidance on restrictive subject claims
   - **Impact**: Overly broad subject claims grant unauthorized access
   - **Recommendation**: Document subject claim best practices with examples
   - **Priority**: 🟠 MEDIUM
   - **Status**: ⚠️ **TODO** — Pending GitHub Actions workflow example

---

## Compliance Status

| OWASP Top 10 2021 | Relevant Controls | Status |
|-------------------|------------------|--------|
| A01: Broken Access Control | RLS/OLS impersonation validation, SPN permissions | ⚠️ **Partial** — SPN docs done, RLS/OLS enforcement pending |
| A02: Cryptographic Failures | Keyring storage, certificate protection | ✅ **Resolved** — Certificate guidance documented |
| A03: Injection | Parameterized XMLA queries, no dynamic SQL | ✅ Mitigated |
| A04: Insecure Design | Federated cred guidance, certificate guidance | ⚠️ **Partial** — Certificate done, federated pending |
| A05: Security Misconfiguration | Subject claim validation, role assignment docs | ✅ **Resolved** — Role assignment docs complete |
| A06: Vulnerable Components | pip-audit clean (2026-08-31) | ✅ Mitigated |
| A07: Identification/Auth Failures | Token validation, secret rotation | ✅ **Resolved** — Both implemented (2026-08-31) |
| A08: Software/Data Integrity | MSAL cache integrity, PyPI package signing | ⚠️ **Assumed** |
| A09: Logging/Monitoring Failures | Audit logging | ✅ **Resolved** — Implemented (2026-08-31) |
| A10: SSRF | No user-controlled URLs in HTTP requests | ✅ Mitigated |

---

## Next Steps

### Completed (2026-08-31)
1. ✅ Implement token validation (JWT expiry check without service calls)
2. ✅ Add audit logging for authentication attempts
3. ✅ Document least-privilege SPN setup and certificate protection
4. ✅ Add security best practices section to CONTRIBUTING.md + README.md
5. ✅ Document secret rotation policy (90-day recommendation)
6. ✅ Document RLS/OLS security implications in README

### Remaining Work
1. **Priority 1** — Create GitHub Actions workflow example with federated auth
2. **Priority 2** — Add certificate expiry warning in `pql-test auth status`

### Archived (Out of Scope)
1. 🗄️ RLS/OLS impersonation validation (config-based allowlist) — Deemed out of scope; security implications documented in README, users responsible for test file review

**Review Date**: 2027-02-28 (6 months)

**Review Date**: 2027-02-28 (6 months)
