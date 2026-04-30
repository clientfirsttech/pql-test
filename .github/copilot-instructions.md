# Copilot Instructions for pql-test

## AIDD Framework

This project uses AI-assisted development with structured guidance in the `ai/` directory.

### Custom AIDD Agent

**Preferred Method**: Use the custom `@aidd` agent for all AIDD workflows.

The AIDD framework is available as a custom GitHub Copilot agent defined in `.github/agents/aidd.agent.md`. 

To use it:
1. Open GitHub Copilot Chat (`Ctrl+Shift+I`)
2. Type `@aidd` to invoke the agent
3. Use commands like `@aidd help`, `@aidd task`, `@aidd review`, etc.

See [COPILOT-QUICKSTART.md](../COPILOT-QUICKSTART.md) for complete command reference.

### Vision Document Requirement

**Before creating or running any task, agents must first read the vision document (`vision.md`) in the project root.**

The vision document serves as the source of truth for:
- Project goals and objectives
- Key constraints and non-negotiables
- Architectural decisions and rationale
- User experience principles
- Success criteria

### Conflict Resolution

If any conflicts are detected between a requested task and the vision document, agents must:

1. Stop and identify the specific conflict
2. Explain how the task conflicts with the stated vision
3. Ask the user to clarify how to resolve the conflict before proceeding

Never proceed with a task that contradicts the vision without explicit user approval.

### Directory Structure and Progressive Discovery

Agents should examine the `ai/*` directory listings to understand the available commands, rules, and workflows.

Each folder in the `ai/` directory contains an `index.md` file that describes the purpose and contents of that folder. Agents can read these index files to learn the function of files in each folder without needing to read every file.

**Important:** The `ai/**/index.md` files are auto-generated from frontmatter. Do not create or edit these files manually—they will be overwritten by the pre-commit hook.

#### Progressive Discovery Pattern

Agents should only consume the root index until they need subfolder contents. For example:
- This project is Python — there is no need to read JavaScript-specific folders
- Only drill into subfolders when the task requires that specific domain knowledge

### Custom Configuration

Project-specific customization lives in `aidd-custom/`. Before starting work:
1. Read `aidd-custom/index.md` to discover available project-specific skills
2. Read `aidd-custom/config.yml` to load configuration into context
3. Read `aidd-custom/AGENTS.md` for custom agent instructions (overrides root AGENTS.md settings)

### AIDD Command Reference

When the user asks these questions or uses these phrases, automatically load and execute the corresponding skills:

| User Says | Action | Skills to Load |
|-----------|--------|----------------|
| "help", "list commands", "what can you do" | List all AIDD commands | `ai/skills/aidd-please/SKILL.md` |
| "plan", "what's next", "priorities" | Review plan.md and suggest next steps | `ai/skills/aidd-please/SKILL.md` |
| "discover", "user journey", "user story" | Product discovery session | `ai/skills/aidd-product-manager/SKILL.md`, `ai/skills/aidd-please/SKILL.md` |
| "task", "create epic", "plan task" | Plan and execute task epic with TDD | `ai/skills/aidd-task-creator/SKILL.md`, `ai/skills/aidd-please/SKILL.md`, `ai/skills/aidd-tdd/SKILL.md` |
| "execute epic", "run epic", "continue task" | Execute previously planned epic | `ai/skills/aidd-task-creator/SKILL.md`, `ai/skills/aidd-please/SKILL.md` |
| "review", "code review", "check quality" | Conduct thorough code review | `ai/skills/aidd-review/SKILL.md`, `ai/skills/aidd-please/SKILL.md` |
| "churn", "hotspots", "refactoring candidates" | Run churn analysis | `ai/skills/aidd-churn/SKILL.md`, `ai/skills/aidd-please/SKILL.md` |
| "fix bug", "implement feedback", "aidd fix" | Bug fixing with AIDD process | `ai/skills/aidd-fix/SKILL.md`, `ai/skills/aidd-please/SKILL.md` |
| "user test", "test script", "generate tests" | Generate test scripts from user journeys | `ai/skills/aidd-user-testing/SKILL.md`, `ai/skills/aidd-please/SKILL.md` |
| "run test", "execute test" | Execute AI agent test | `ai/skills/aidd-user-testing/SKILL.md`, `ai/skills/aidd-please/SKILL.md` |
| "log changes", "update changelog", "document work" | Document completed epics | `ai/skills/aidd-log/SKILL.md`, `ai/skills/aidd-please/SKILL.md` |
| "commit", "create commit", "commit message" | Create conventional commit | `ai/commands/commit.md`, `ai/skills/aidd-please/SKILL.md` |

### Skill Loading Protocol

When a user request matches any command trigger:

1. **Read the vision document first**: Always check `vision.md` before starting any task
2. **Load command file**: Read the corresponding file from `ai/commands/[command-name].md`
3. **Load referenced skills**: Read all SKILL.md files referenced in the command
4. **Follow constraints**: Respect all constraints specified in the skill files
5. **Execute workflow**: Follow the workflow defined in the loaded skills

---

## Project Overview

**pql-test** is a Python CLI tool that discovers and runs DAX unit tests stored
inside a Power BI / Microsoft Fabric PBIP semantic model's `DAXQueries/` folder
via the XMLA endpoint. It is packaged as a GitHub Copilot CLI plugin with
installable skills.

## Repository Structure

```
pql-test/
├── AGENTS.md               # AI agent guidelines (AIDD framework)
├── vision.md               # Project vision document
├── plan.md                 # Development plan and priorities
├── COPILOT-QUICKSTART.md   # AIDD agent quick start guide
├── plugin.json             # Copilot CLI plugin manifest
├── ai/                     # AIDD commands, skills, and scaffolds
│   ├── commands/           # AIDD command definitions
│   └── skills/             # AIDD skill modules
├── aidd-custom/            # Project-specific AIDD customizations
├── tasks/                  # Epic task files for AIDD workflow
├── skills/                 # Plugin skills (check-prereqs, retrieve-test, retrieve-tests, run-tests)
│   └── <skill>/SKILL.md    # Skill definition with YAML frontmatter (name + description required)
├── python/                 # Python package source
│   ├── pql_test_cli.py     # Click-based CLI entry point
│   ├── pql_test_runner.py  # Core test runner logic
│   ├── pyproject.toml      # Build metadata, dependencies, pytest config
│   ├── requirements.txt    # Runtime dependencies
│   └── requirements-dev.txt # Dev/test dependencies
├── examples/               # PBIP semantic models with sample DAX test suites
│   ├── SampleModel.SemanticModel/
│   ├── RLS_Model.SemanticModel/
│   └── OLS_Model.SemanticModel/
├── tests/                  # Promptfoo skill evaluation tests
│   └── promptfoo/
├── docs/                   # Internal documentation
├── .github/
│   ├── agents/             # Custom Copilot agents (aidd.agent.md)
│   ├── workflows/          # CI pipeline (validate-plugin → promptfoo-eval → run-tests-remote)
│   └── skills/             # Copilot development skills (promptfoo-evals)
└── .vscode/                # VS Code settings and MCP server config
```

## Language and Frameworks

- **Python >= 3.9** is the primary language.
- **Click >= 8.1** is used for the CLI framework.
- **pyadomd >= 0.0.5** is the ADOMD.NET wrapper for XMLA queries (Windows/.NET only).
- **msal >= 1.24.0** handles Azure AD / service-principal authentication.
- **psutil >= 5.9.0** is used for local Power BI Desktop detection.
- **pytest >= 7.4** with **pytest-cov >= 4.1** for testing.

## Conventions

### Code Style

- Follow PEP 8 for Python code.
- Use type annotations (`from __future__ import annotations`).
- Docstrings follow Google-style conventions.
- Keep imports organized: stdlib → third-party → local.

### Plugin and Skills

- `plugin.json` at the repo root defines the Copilot CLI plugin manifest. Required fields: `name`, `description`, `version`, `skills`.
- Each skill lives in its own directory under `skills/` and must contain a `SKILL.md` file with YAML frontmatter including `name` and `description`.
- The plugin name should be lowercase-kebab-case.

### MODEL_PATH Formats

pql-test supports three `MODEL_PATH` formats throughout the CLI:

1. **Filesystem path** — PBIP root directory or `.SemanticModel` directory.
2. **`local/<model_name>`** — Connect to a locally-open Power BI Desktop instance.
3. **`<workspace>.<semantic_model>`** — Fabric CLI dot notation for remote workspace connections.

### Environment Variables

Credentials are configured via environment variables (loaded from `.env` when `python-dotenv` is available):

- `PQL_TENANT_ID` — Azure AD tenant GUID
- `PQL_WORKSPACE_ID` — Power BI workspace GUID
- `PQL_DATASET_ID` — Dataset / semantic model GUID
- `PQL_CLIENT_ID` — Service principal application (client) ID
- `PQL_CLIENT_SECRET` — Service principal client secret
- `PQL_ENVIRONMENT` — Cloud environment (`Public`, `USGov`, `USGovHigh`, `DOD`, `Germany`, `China`). Default: `Public`.

### DAX Test Files

- Test files follow the naming convention `*.Tests.dax` and live in `DAXQueries/` inside a `.SemanticModel` directory.
- Test file names can include environment tags: `<Name>.<ENV>.Tests.dax` (e.g., `Calcs.DEV.Tests.dax`).

## Building and Testing

### Install Dependencies

```bash
cd python
pip install -e .                   # Install pql-test in editable mode
pip install -r requirements-dev.txt # Install dev/test dependencies
```

### Run Unit Tests

```bash
cd python
pytest                             # Run all unit tests
pytest -v                          # Verbose output
pytest --cov                       # With coverage
pytest -m "not live"               # Skip tests requiring real Power BI credentials
```

### Run the CLI

```bash
pql-test check-prereqs
pql-test retrieve-tests <MODEL_PATH>
pql-test retrieve-test <MODEL_PATH> <NAME>
pql-test run-tests <MODEL_PATH> [--verbose] [--output results.json]
```

### Validate Plugin Structure

The CI pipeline validates the plugin structure automatically. To check locally:

```bash
# Verify plugin.json is valid
python -c "import json; json.load(open('plugin.json'))"

# Install and verify via gh copilot
gh copilot plugin install .
gh copilot plugin list
```

## CI Pipeline

The CI pipeline (`.github/workflows/ci.yml`) runs three sequential stages:

1. **Stage 1 — Validate plugin structure** (`validate-plugin.yml`):
   Static structural validation of `plugin.json`, skill directory layout, `SKILL.md` frontmatter, and `gh copilot` CLI install check.

2. **Stage 2 — Skill evaluation** (`promptfoo-eval.yml`):
   Sends skill instructions to GitHub Models (gpt-4o-mini) via plain Python `urllib.request` and asserts expected CLI flags/commands. Uses `GITHUB_TOKEN`; no third-party keys required.

3. **Stage 3 — Run DAX tests remotely** (`run-tests-remote.yml`):
   Installs pql-test on a Windows runner (required for ADOMD.NET), discovers `.SemanticModel` directories under `examples/`, and runs the full DAX test suite against a remote Power BI Premium / Fabric workspace. Requires repository secrets.

## Important Notes

- ADOMD.NET / pyadomd requires Windows and .NET runtime. Remote test stages use `windows-latest` runners.
- On Windows runners, install ADOMD.NET via `nuget.exe` CLI, not PowerShell `Install-PackageProvider` / `Install-Package`.
- The promptfoo evaluation step is marked `continue-on-error` since GitHub Models may be unavailable for some repositories.
- Exit code 0 from `pql-test run-tests` means all tests passed; exit code 1 means one or more tests failed.
