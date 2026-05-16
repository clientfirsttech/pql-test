# Development Plan

<!-- AI agents use this file to understand current priorities and progress. -->

## Active Work

- **Refactor authentication to match Fabric CLI pattern** — See [tasks/fabric-cli-auth-epic.md](tasks/fabric-cli-auth-epic.md)

- Incorporate AIDD framework into pql-test repository
- Set up agent-based development workflows with @aidd commands
- Maintain CI pipeline: validate-plugin → promptfoo-eval → run-tests-remote

## Completed Work

- Core CLI implementation (check-prereqs, retrieve-tests, retrieve-test, run-tests)
- Three MODEL_PATH formats (filesystem, local/, workspace.model)
- CI pipeline with 3 stages (validate-plugin, promptfoo-eval, run-tests-remote)
- Copilot CLI plugin with 4 installable skills
- Service principal authentication via MSAL
- Example semantic models (SampleModel, RLS_Model, OLS_Model)
- Promptfoo skill evaluations migrated from Node.js to plain Python
