# Fabric CLI Authentication Epic

**Status**: � IN-PROGRESS
**Goal**: Replace per-command credential flags with persistent Fabric CLI-style authentication

## Overview

Developers currently must pass `--tenant-id`, `--client-id`, `--client-secret` flags on every command, which is tedious and exposes credentials in shell history. By implementing Fabric CLI's authentication pattern, users authenticate once via `pql-test auth login`, and all subsequent commands use the stored credentials automatically. This dramatically improves developer experience and security while maintaining backward compatibility for CI/CD pipelines.

---

## Research Fabric CLI Authentication

Investigate how Fabric CLI implements authentication and credential storage.

**Requirements**:
- Given Fabric CLI source code or documentation, should identify the authentication library used (likely Azure Identity SDK)
- Given credential storage mechanism, should identify how tokens are persisted (keyring, encrypted file, etc.)
- Given token refresh logic, should understand how expired tokens are handled
- Given multiple authentication methods, should document the flow for each (interactive, service principal, managed identity)

---

## Design Authentication Architecture

Design the authentication module architecture for pql-test.

**Requirements**:
- Given multiple authentication methods, should design a credential provider abstraction
- Given secure credential storage needs, should select appropriate keyring library (keyring, cryptography)
- Given token lifecycle management, should design token refresh and expiration handling
- Given backward compatibility requirements, should design fallback to environment variables and CLI flags
- Given cross-platform support, should ensure credential storage works on Windows, Linux, macOS

---

## Implement Core Authentication Module

Create the core authentication module with credential storage and token management.

**Requirements**:
- Given a credential to store, should persist it securely using platform keyring
- Given a stored credential, should retrieve it without exposing plaintext
- Given an expired token, should detect expiration and trigger refresh
- Given no stored credential, should return None gracefully
- Given a credential to delete, should clear it from secure storage
- Given multiple tenants/workspaces, should namespace credentials appropriately

---

## Implement Interactive User Authentication

Implement `pql-test auth login` with interactive browser-based authentication.

**Requirements**:
- Given user selects interactive authentication, should open browser for Azure AD login
- Given successful authentication, should acquire and store access token
- Given token with refresh token, should store refresh token for future use
- Given authentication failure, should display clear error message
- Given stored credentials exist, should prompt user before overwriting

---

## Implement Service Principal with Secret

Implement service principal authentication with client secret.

**Requirements**:
- Given user provides client ID, secret, and tenant ID, should authenticate via client credentials flow
- Given successful authentication, should store credentials securely
- Given stored service principal credentials, should acquire new access tokens as needed
- Given invalid credentials, should display clear error message with troubleshooting guidance

---

## Implement Service Principal with Certificate

Implement service principal authentication with certificate (PEM and P12 formats).

**Requirements**:
- Given user provides certificate path (PEM format), should authenticate using certificate
- Given user provides certificate path (P12 format) with password, should authenticate using encrypted certificate
- Given certificate file does not exist, should display clear error message
- Given invalid certificate, should display clear error with certificate validation details
- Given successful authentication, should store certificate path and credential metadata

---

## Implement Service Principal with Federated Credential

Implement service principal authentication with federated credential (OIDC).

**Requirements**:
- Given user provides federated token and client ID, should authenticate via federated credential flow
- Given successful authentication, should store credential configuration
- Given invalid federated token, should display clear error message
- Given token expiration, should guide user to refresh federated token

---

## Implement Managed Identity Authentication

Implement managed identity authentication for Azure VM/container scenarios.

**Requirements**:
- Given system-assigned managed identity, should authenticate without credentials
- Given user-assigned managed identity with client ID, should authenticate with specific identity
- Given environment is not Azure VM/container, should display clear error explaining managed identity requirements
- Given successful authentication, should store identity configuration
- Given identity lacks required permissions, should display clear error with RBAC guidance

---

## Implement auth logout Command

Implement `pql-test auth logout` to clear stored credentials.

**Requirements**:
- Given stored credentials exist, should delete all stored authentication data
- Given no stored credentials, should display message indicating already logged out
- Given logout completes successfully, should confirm credentials were cleared
- Given credential deletion fails, should display error with details

---

## Implement auth status Command

Implement `pql-test auth status` to display current authentication state.

**Requirements**:
- Given stored credentials exist, should display authentication method and account/principal information
- Given stored token is valid, should display token expiration time
- Given stored token is expired, should indicate token needs refresh
- Given no stored credentials, should display "Not authenticated" message
- Given multiple credential sets exist, should display all with clear namespace labels

---

## Update Existing Commands to Use Stored Credentials

Update `run-tests`, `retrieve-tests`, `retrieve-test` to use stored credentials.

**Requirements**:
- Given stored credentials exist and no CLI flags provided, should use stored credentials
- Given CLI flags provided, should prefer CLI flags over stored credentials
- Given environment variables exist and no CLI flags or stored credentials, should use environment variables
- Given no credentials available from any source, should display clear error with authentication guidance
- Given stored token is expired, should attempt refresh before failing

---

## Update Documentation

Update README, COPILOT-QUICKSTART, and skill documentation.

**Requirements**:
- Given authentication refactoring is complete, should document all `auth` subcommands with examples
- Given backward compatibility is maintained, should clearly explain precedence (CLI flags > env vars > stored)
- Given multiple authentication methods, should provide decision tree or comparison table
- Given CI/CD scenarios, should recommend environment variable approach with justification
- Given security considerations, should document keyring storage and token handling

---

## Update Tests and CI Pipeline

Update unit tests and CI pipeline to work with new authentication.

**Requirements**:
- Given new authentication module, should add comprehensive unit tests for all credential operations
- Given multiple authentication methods, should add integration tests for each method
- Given CI pipeline uses environment variables, should verify backward compatibility
- Given credential storage tests, should use mock keyring to avoid persisting real credentials
- Given all tests pass, should verify no regression in existing functionality
