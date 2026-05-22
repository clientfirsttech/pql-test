# Execute DAX Queries REST Public Endpoint Epic

**Status**: 📋 PLANNED
**Goal**: Add Public-cloud test execution via Execute DAX Queries REST API with safe capacity gating and XMLA fallback

## Overview

WHY this matters: using the new Execute DAX Queries REST API for Public cloud reduces ADOMD.NET dependency for remote execution and aligns with Microsoft’s newer query path, while keeping current XMLA behavior as a fallback protects existing users and environments that are not eligible for the new API.

---

## Validate Capacity and Permission Feasibility

Confirm whether a workspace contributor (non-admin) can detect Premium/Fabric capacity eligibility through supported APIs and define fallback behavior when the check is denied or inconclusive.

**Requirements**:
- Given a workspace contributor token, should determine whether capacity eligibility can be retrieved from a supported API call
- Given insufficient API permissions (403/401), should fall back safely without blocking XMLA execution
- Given unclear API metadata, should document an explicit compatibility matrix and decision outcome for this project

---

## Design Public REST Execution Strategy

Define the runtime decision flow that uses REST in Public cloud only when capacity-qualified and otherwise routes to existing XMLA execution.

**Requirements**:
- Given `Environment.PUBLIC`, should select REST execution only when capacity qualification is positive
- Given non-Public environments, should continue using XMLA execution
- Given REST execution setup/runtime errors, should apply a deterministic fallback policy with actionable diagnostics

---

## Implement Capacity Qualification and Endpoint Selection

Add capability-detection logic and endpoint routing that can be reused across test discovery and test execution paths.

**Requirements**:
- Given workspace and dataset context, should evaluate capacity eligibility before selecting REST execution
- Given positive eligibility in Public cloud, should construct and use the Execute DAX Queries REST endpoint
- Given negative or unknown eligibility, should keep current XMLA connection resolution unchanged

---

## Implement REST DAX Execution Path

Add a REST-based DAX query executor that supports current test-runner expectations and result parsing semantics.

**Requirements**:
- Given a DAX query request, should execute via `executeDaxQueries` and parse Arrow IPC responses into row records
- Given multiple `EVALUATE` statements or large result sets, should preserve current result semantics and test assertions
- Given API throttling or response-size limitations, should surface clear errors and guidance for retry/mitigation

---

## Update Documentation

Document the new execution mode, eligibility checks, permissions model, and fallback behavior for users and CI operators.

**Requirements**:
- Given remote execution guidance, should describe when REST vs XMLA is selected and why
- Given authentication guidance, should document permission expectations including contributor/non-admin considerations
- Given troubleshooting guidance, should include capacity-check failures, REST throttling, and fallback diagnostics

---

## Update and Expand Tests

Add focused test coverage for routing decisions, capacity checks, REST execution, and backward compatibility.

**Requirements**:
- Given environment and capacity combinations, should verify deterministic REST/XMLA selection behavior
- Given REST success and failure responses, should validate result parsing and fallback/error handling behavior
- Given existing XMLA scenarios, should maintain backward-compatible outcomes for current CLI and runner tests

