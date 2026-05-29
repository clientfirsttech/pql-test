# Development Plan

<!-- AI agents use this file to understand current priorities and progress. -->

## Active Work

- **Format Test Results** — See [tasks/2026-05-29-format-test-results.md](tasks/2026-05-29-format-test-results.md) (Issue #30)
  - Enhanced human-readable output with visual icons (✓, ✗, ⊘)
  - Pass rate percentage and color-coded summary stats
  - Total test duration display in summary
  - Improved failure context with labeled fields (Message, Error, Expected, Actual)
  - Better visual grouping in compact mode (dots grouped every 10 tests)
- Incorporate AIDD framework into pql-test repository
- Set up agent-based development workflows with @aidd commands
- Maintain CI pipeline: validate-plugin → promptfoo-eval → run-tests-remote

## Completed Work

- **Issue Review Agent Workflow** — See [tasks/archive/2026-05-28-issue-review-agent.md](tasks/archive/2026-05-28-issue-review-agent.md)
  - GitHub Agentic Workflow triggered by issue creation or manual dispatch
  - Two-phase execution: bash pre-computation + Copilot agent instructions
  - Automated issue analysis, code generation, and PR creation
  - Tool restrictions for security (edit + limited bash commands)
  - Comprehensive documentation with usage examples
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
