# Model Path Names The Dataset Epic

**Status**: ✅ COMPLETED (2026-11-17)
**Goal**: A `<name>.SemanticModel` MODEL_PATH runs against the `<name>` dataset, not whatever dataset `PQL_DATASET_ID` holds in the environment or `.env`

## Overview

`pql-test contract run test.odcs.yaml examples/CodeCoverage.SemanticModel` connected to `SampleModel`, because `python/.env` sets `PQL_DATASET_ID` to SampleModel's GUID. Click reads that variable as the `--dataset-id` default, and the CLI only names the dataset after the folder when no dataset ID is set. So a default meant for one model silently redirected every folder run to that model, and every rule failed with NOT FOUND.

A `--dataset-id` typed on the command line is a deliberate choice and keeps winning. `PQL_DATASET_ID` from the environment is only a default, so the folder the user named should win over it. CI's run-tests-remote matrix already leaves `PQL_DATASET_ID` unset and routes by folder name, so it is unaffected.

---

## A Folder MODEL_PATH Wins Over PQL_DATASET_ID

**Requirements**:
- Given a `<name>.SemanticModel` MODEL_PATH and `PQL_DATASET_ID` set in the environment, should connect to the dataset named `<name>`, not the dataset `PQL_DATASET_ID` identifies
- Given the folder replaces `PQL_DATASET_ID`, should say so in one line, naming the model it uses and how to pick another dataset
- Given a `<name>.SemanticModel` MODEL_PATH and `--dataset-id` on the command line, should connect to the dataset that ID identifies
- Given a MODEL_PATH that is not a `.SemanticModel` folder and `PQL_DATASET_ID` set, should keep using `PQL_DATASET_ID`
- Given a `local/<name>` MODEL_PATH, should not mention `PQL_DATASET_ID`, because it connects to the open Desktop model and never to a dataset
- Given any command that connects from a MODEL_PATH (`run-tests`, `retrieve-tests`, `retrieve-test`, `code-coverage`, `contract run`, `contract coverage --live`), should follow the same rule

---

## Epic Vision (Definition of Done)

### Quality Gates (All Must Pass)

- **Ruff Check**: `ruff check python/` reports zero violations
- **Tests**: `cd python && pytest` passes
- **Documentation**: README and docs describe the precedence: `--dataset-id`, then the `.SemanticModel` folder name, then `PQL_DATASET_ID`
