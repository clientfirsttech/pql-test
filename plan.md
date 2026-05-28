# Development Plan

<!-- AI agents use this file to understand current priorities and progress. -->

## Active Work

- **Issue Review Agent Workflow** — See [tasks/issue-review-agent-epic.md](tasks/issue-review-agent-epic.md)
  - GitHub Actions workflow triggered by issue creation or manual dispatch
  - Automated issue analysis using GitHub agent capabilities
  - Code change generation and PR creation
  - Full documentation and configuration guide
- Incorporate AIDD framework into pql-test repository
- Set up agent-based development workflows with @aidd commands
- Maintain CI pipeline: validate-plugin → promptfoo-eval → run-tests-remote

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
