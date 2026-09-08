# Vision

<!-- This file is read by AI agents before starting any task. -->
<!-- See: https://github.com/paralleldrive/aidd -->

## Mission

Enable Power BI and Microsoft Fabric developers to write, discover, and run DAX unit tests directly from their semantic model's `DAXQueries/` folder, with seamless CI/CD integration via GitHub Actions.

## Product

**pql-test** is a Python CLI tool and GitHub Copilot CLI plugin that discovers and runs DAX unit tests stored inside a Power BI / Microsoft Fabric PBIP semantic model via the XMLA endpoint. It supports local Power BI Desktop, remote Fabric workspaces, and filesystem-based model paths.

What makes it unique:
- First-class DAX testing CLI for the Power BI / Fabric ecosystem
- Three MODEL_PATH formats: filesystem, `local/<model_name>`, `<workspace>.<semantic_model>`
- GitHub Copilot CLI plugin with installable skills for AI-assisted testing workflows
- Built-in CI pipeline for structural validation, skill evaluation, and remote DAX test execution

## Target Users

- Power BI developers who use PBIP (Power BI Projects) format
- Microsoft Fabric developers building semantic models
- DevOps engineers integrating Power BI testing into CI/CD pipelines
- Teams adopting test-driven development for DAX measures and calculations

## Core Principles

- **Test-driven development** — Write DAX tests first, then implement measures
- **Cross-platform model support** — Local Desktop, remote Fabric, and filesystem paths
- **CI/CD integration** — Automated testing in GitHub Actions pipelines
- **Security first** — Service principal authentication, no plaintext secrets
- **PEP 8 compliance** — Python code follows PEP 8 with type annotations and Google-style docstrings

## Architecture

- **CLI Layer** (`python/pql_test/cli.py`) — Click-based CLI entry point with commands: `check-prereqs`, `retrieve-tests`, `retrieve-test`, `run-tests`, `skill`
- **Core Runner** (`python/pql_test/runner/`) — Refactored module package for test discovery and execution via XMLA/ADOMD.NET
- **Skill Distribution** (`python/pql_test/skills/`, `python/pql_test/skills_resolver.py`) — Version-matched skills packaged in wheel, installable to any harness (Claude, Copilot, Cursor, Windsurf)
- **Plugin Skills** (`skills/`) — Source skills with YAML frontmatter (name, description, version), SudoLang behavioral contracts
- **CI Pipeline** (`.github/workflows/`) — 3-stage pipeline: validate-plugin → promptfoo-eval → run-tests-remote
- **AIDD Framework** (`ai/`, `.github/agents/`) — AI-Driven Development skills and agent definitions

## Constraints

- ADOMD.NET / pyadomd requires Windows and .NET runtime for XMLA queries
- Remote test execution requires Power BI Premium or Fabric workspace with XMLA endpoint enabled
- Service principal authentication requires Azure AD app registration
- Python >= 3.9 is the minimum supported version
- DAX test files must follow `*.Tests.dax` naming convention in `DAXQueries/` directory

## Success Criteria

- All DAX tests in example models pass against a remote Fabric workspace
- CI pipeline runs successfully on every push and PR
- Plugin structure validates correctly (`plugin.json` + `SKILL.md` frontmatter)
- Skill evaluations produce expected CLI guidance via GitHub Models
- Skills package correctly in wheel and can be installed to any harness with version validation
- Source and packaged skill content remains byte-for-byte identical
- CI guards prevent skill format drift or missing frontmatter
- Developers can discover and run tests with a single CLI command
