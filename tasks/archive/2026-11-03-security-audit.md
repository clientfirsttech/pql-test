# Security Audit Epic

**Status**: ✅ COMPLETED (2026-11-03)
**Goal**: Close the OWASP A01, A04, and A06 findings left from the 2026-08-30 AIDD review.

## Overview

Maintainers and CI users need confidence that credentials and impersonation settings cannot be abused, so the audit re-checks dependencies, the connection-string builder, file writes, and workflow supply chain, and documents the remaining auth guidance.

---

## Dependency and tool scan

**Requirements**:
- Given the requirements and the project's resolved dependencies, `pip-audit` should report no known vulnerabilities.
- Given the package, `bandit` at medium severity and above should report no findings.

## Connection-string values

**Requirements**:
- Given a client secret containing `;` or `"`, should keep it one quoted value, so it cannot add or override connection keys.
- Given an ordinary secret or token, should leave it unquoted.

## Workflow supply chain

**Requirements**:
- Given any workflow or setup-steps file, should reference actions by commit SHA.

## Auth guidance

**Requirements**:
- Given a federated credential, should document restrictive subject claims and a GitHub Actions example.
- Given a managed identity, should document least-privilege workspace roles and metadata-endpoint exposure.
- Given the threat model, should show current statuses with no duplicate entries.
