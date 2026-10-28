# GitHub Actions Workflows

This directory contains both traditional GitHub Actions workflows and GitHub Agentic Workflows powered by Copilot.

## Traditional Workflows

- `ci.yml` — Master CI pipeline: validate-plugin → promptfoo-eval → run-tests-remote
- `validate-plugin.yml` — Validates plugin.json structure and skill frontmatter
- `promptfoo-eval.yml` — Evaluates Copilot CLI skills via GitHub Models
- `run-tests-remote.yml` — Runs DAX tests against remote Power BI/Fabric workspace
- `release.yml` — Publishes pql-test to PyPI on `vX.Y.Z` tags (Trusted Publishing is bound to this file name; do not rename)
- `pytest.yml` — The full pytest suite on Windows with ADOMD.NET (Stage 3a)
- `contracts.yml` — `pql-test contract` on Linux (Python 3.9 and 3.13): the contract tests, a CLI smoke test, and a check that `contract run` without XMLA fails cleanly

## Agentic Workflows

### `issue-review-agent.yml`

**Purpose**: Automatically analyzes GitHub issues and generates code fixes via PR.

**Triggers**:
- Automatically when an issue is opened (`issues.opened`)
- Manually via workflow_dispatch with issue number input

**How It Works**:

The workflow follows a two-phase execution model:

1. **Pre-execution phase** (bash steps):
   - Fetches issue data via GitHub API
   - Extracts title, body, labels, author
   - Saves structured data to `/tmp/gh-aw/agent/` for agent consumption

2. **Agent execution phase** (Copilot engine):
   - Reads pre-computed issue data
   - Analyzes the codebase to identify relevant files
   - Generates surgical code changes using the `edit` tool
   - Verifies changes with `git diff`
   - Creates a pull request if changes were applied

**Tool Restrictions**:
- `edit:` - Full access for file modifications
- `bash:` - Limited to: `cat`, `echo`, `find`, `git diff`, `git log`, `git status`

**Security**:
- Read-only permissions for contents and issues
- Write permissions for pull-requests only
- `safe-outputs` declaration for PR creation
- No arbitrary code execution allowed

**Usage**:

Automatic (on issue creation):
```
# Just create an issue - the workflow runs automatically
```

Manual (for existing issues):
```bash
# Go to Actions → Issue Review and Fix Agent → Run workflow
# Enter issue number: 123
```

**Example Issue Patterns**:

- **Bug Report**: Issue mentions "error", "fails", "broken" → Agent locates bug and applies minimal fix
- **Feature Request**: Issue requests "add feature" or "enhancement" → Agent implements following existing patterns
- **Documentation**: Issue mentions "typo", "docs unclear" → Agent updates documentation files
- **Configuration**: Issue about "workflow", "ci" → Agent updates config files

**Expected Output**:

If the agent successfully generates a fix:
- New PR created with title: `Fix #<issue-number>: <issue-title>`
- PR description includes:
  - Summary of changes
  - Reference to original issue
  - Testing/verification notes
  - Any questions or uncertainties
- PR is linked to the original issue

If no changes are needed:
- Workflow completes without creating a PR
- Check workflow logs for agent reasoning

**Repository Context**:

The agent understands this is the **pql-test** repository and follows:
- Python >= 3.9 with PEP 8 style
- Click framework for CLI
- Type annotations and Google-style docstrings
- Conventional commits
- XMLA/ADOMD.NET patterns for remote connections

**Limitations**:

- Agent cannot run tests or execute Python code (Windows-only ADOMD.NET dependency)
- Changes are conservative and surgical - no major refactoring
- Complex issues may require human review and iteration
- Agent will not introduce new dependencies without justification

## Adding New Agentic Workflows

To create a new agentic workflow:

1. Define the workflow metadata:
```yaml
---
name: Your Workflow Name
description: What it does

on: [your triggers]

permissions:
  contents: read
  # other permissions as needed

safe-outputs:
  create-pull-request: {}  # if creating PRs

engine:
  id: copilot

timeout-minutes: 15

checkout:
  fetch-depth: 0

tools:
  edit:
  bash:
    - "command:arg-pattern"
```

2. Add pre-execution steps:
```yaml
steps:
  - name: Checkout
    uses: actions/checkout@v4
    with:
      fetch-depth: 0
      persist-credentials: false
  
  - name: Prepare data
    run: |
      # Bash script to fetch/compute data
      # Save results to /tmp/gh-aw/agent/
      # Always exit 0 so agent can run
```

3. Write agent instructions (after `---` separator):
```markdown
---

# Your Agent Name

You are a [role description]. Your tasks are:
1. Task one
2. Task two

## Constraints

Constraints {
  Constraint one
  Constraint two
}

## Inputs

interface Inputs {
  // Define data structure
}

## Workflow

fn yourWorkflow() {
  // Define agent logic
}
```

4. Test locally:
   - Use workflow_dispatch trigger for manual testing
   - Start with read-only operations
   - Gradually add edit capabilities
   - Verify git diff output before PR creation
