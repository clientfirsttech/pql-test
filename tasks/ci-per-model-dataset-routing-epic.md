# CI Per-Model Dataset Routing Epic

**Status**: 🚧 IN PROGRESS (2026-05-23)
**Goal**: Route each matrix entry in the remote-tests CI workflow to its own dataset GUID so `PQL.Assert.RetrieveTestsV2()` returns the tests defined in *that specific model*

## Overview

The remote-tests CI workflow ([.github/workflows/run-tests-remote.yml](../.github/workflows/run-tests-remote.yml)) runs `pql-test run-tests` against every `.SemanticModel` directory under `examples/` in a matrix. Today every matrix entry receives the same `PQL_DATASET_ID` secret, so the XMLA connection always points to a single dataset regardless of which model the matrix entry is supposed to be testing. `PQL.Assert.RetrieveTestsV2()` then returns the tests registered in *that* dataset, which causes (for example) `RLS.ANY.Tests` to appear in the SampleModel job's results.

The README already documents three per-model dataset env vars — `PQL_DATASET_ID` (SampleModel), `PQL_DATASET_ID_RLS`, `PQL_DATASET_ID_OLS` — but the workflow does not wire them up.

---

## Route Matrix Entries To Their Own Dataset Secret

Update the workflow so each matrix model uses the dataset GUID that corresponds to *that* model.

**Requirements**:
- Given a CI matrix entry whose model path identifies the SampleModel, should connect with the `PQL_DATASET_ID` secret so `RetrieveTestsV2()` returns the SampleModel test suites only
- Given a CI matrix entry whose model path identifies the RLS_Model, should connect with the `PQL_DATASET_ID_RLS` secret so `RetrieveTestsV2()` returns `RLS.ANY.Tests` and no SampleModel suites
- Given a CI matrix entry whose model path identifies the OLS_Model, should connect with the `PQL_DATASET_ID_OLS` secret so `RetrieveTestsV2()` returns the OLS test suites only
- Given a model path the routing helper does not recognise, should fail fast with a clear error rather than silently fall back to the default dataset

---

## Propagate The New Secrets Through The Calling Workflow

`ci.yml` calls `run-tests-remote.yml` as a reusable workflow and must forward the new secrets.

**Requirements**:
- Given `ci.yml` calls the reusable run-tests-remote workflow, should forward `PQL_DATASET_ID_RLS` and `PQL_DATASET_ID_OLS` alongside the existing `PQL_DATASET_ID`
- Given the reusable workflow declares secrets, should mark the per-model dataset secrets as required so a misconfigured repo fails at the `workflow_call` boundary rather than at runtime
