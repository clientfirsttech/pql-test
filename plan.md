# Development Plan

<!-- AI agents use this file to understand current priorities and progress. -->

## Active Work

- Incorporate AIDD framework into pql-test repository
- Set up agent-based development workflows with @aidd commands
- Maintain CI pipeline: validate-plugin → promptfoo-eval → run-tests-remote
- Plan Public-cloud Execute DAX Queries REST support with capacity checks and XMLA fallback — see [tasks/execute-dax-queries-rest-epic.md](tasks/execute-dax-queries-rest-epic.md)

## Completed Work

- **Fabric CLI Authentication** — See [tasks/fabric-cli-auth-epic.md](tasks/fabric-cli-auth-epic.md) (archived)
  - Modern authentication with azure-identity and keyring
  - Support for 5 authentication methods (interactive, service principal, managed identity)
  - CLI commands: auth login/logout/status
  - Backward compatible with environment variables and CLI flags
  - 39 unit tests passing
- Core CLI implementation (check-prereqs, retrieve-tests, retrieve-test, run-tests)
- Three MODEL_PATH formats (filesystem, local/, workspace.model)
- CI pipeline with 3 stages (validate-plugin, promptfoo-eval, run-tests-remote)
- Copilot CLI plugin with 4 installable skills
- Service principal authentication via MSAL
- Example semantic models (SampleModel, RLS_Model, OLS_Model)
- Promptfoo skill evaluations migrated from Node.js to plain Python
