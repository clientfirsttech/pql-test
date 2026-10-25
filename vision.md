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

**pql-odcs** is a companion package in the same repository, under the MIT license. It converts [ODCS](https://bitol-io.github.io/open-data-contract-standard/) v3.x data contract quality rules into PQL.Assert `*.Tests.dax` suites, and reports every contract rule as mapped, approximated, or skipped, so no rule is dropped silently. It ships standalone on PyPI (the `pql-odcs` CLI) for Bitol and datacontract-cli users. pql-test exposes it as `pql-test contract …` through the optional `pql-test[contracts]` extra.

## Target Users

- Power BI developers who use PBIP (Power BI Projects) format
- Microsoft Fabric developers building semantic models
- DevOps engineers integrating Power BI testing into CI/CD pipelines
- Teams adopting test-driven development for DAX measures and calculations
- Data contract owners (ODCS / Bitol, datacontract-cli) who want their contract's quality rules enforced against a Power BI semantic model

## Core Principles

- **Test-driven development** — Write DAX tests first, then implement measures
- **Cross-platform model support** — Local Desktop, remote Fabric, and filesystem paths
- **CI/CD integration** — Automated testing in GitHub Actions pipelines
- **Security first** — Service principal authentication, no plaintext secrets
- **PEP 8 compliance** — Python code follows PEP 8 with type annotations and Google-style docstrings

## Architecture

- **CLI Layer** (`python/pql_test/cli.py`) — Click-based CLI entry point with commands: `check-prereqs`, `retrieve-tests`, `retrieve-test`, `run-tests`, `code-coverage`, `skill`, `auth`
- **Core Runner** (`python/pql_test/runner/`) — Refactored module package for test discovery and execution via XMLA/ADOMD.NET
- **Skill Distribution** (`python/pql_test/skills/`, `python/pql_test/skills_resolver.py`) — Version-matched skills packaged in wheel, installable to any harness (Claude, Copilot, Cursor, Windsurf)
- **Plugin Skills** (`skills/`) — Source skills with YAML frontmatter (name, description, version), SudoLang behavioral contracts
- **CI Pipeline** (`.github/workflows/`) — 3-stage pipeline: validate-plugin → promptfoo-eval → run-tests-remote
- **AIDD Framework** (`ai/`, `.github/agents/`) — AI-Driven Development skills and agent definitions
- **pql-odcs** (`packages/pql-odcs/`, MIT) — Contract loader, name resolution, rule mappers, versioned PQL.Assert catalog, DAX emitter, coverage, and result tracing. Plugs into pql-test through the `pql_test.commands` entry point group. Has its own version, changelog, release tag (`pql-odcs-v*`), and cross-platform CI.

## Constraints

- ADOMD.NET / pyadomd requires Windows and .NET runtime for XMLA queries
- Remote test execution requires Power BI Premium or Fabric workspace with XMLA endpoint enabled
- Service principal authentication requires Azure AD app registration
- Python >= 3.9 is the minimum supported version
- DAX test files must follow `*.Tests.dax` naming convention in `DAXQueries/` directory
- **One-way license boundary** — pql-test (BUSL-1.1) may depend on pql-odcs (MIT). pql-odcs never imports, vendors, or copies pql-test code. Its only knowledge of pql-test is data: PQL.Assert function signatures in its catalog, and pql-test's documented `--output` JSON shape.
- pql-odcs runtime dependencies are limited to MIT, BSD, or Apache-2.0 licensed packages. It needs no ADOMD.NET and must run on Linux, macOS, and Windows. All XMLA transport stays in pql-test.

## Success Criteria

- All DAX tests in example models pass against a remote Fabric workspace
- CI pipeline runs successfully on every push and PR
- Plugin structure validates correctly (`plugin.json` + `SKILL.md` frontmatter)
- Skill evaluations produce expected CLI guidance via GitHub Models
- Skills package correctly in wheel and can be installed to any harness with version validation
- Source and packaged skill content remains byte-for-byte identical
- CI guards prevent skill format drift or missing frontmatter
- Developers can discover and run tests with a single CLI command
- An ODCS contract generates byte-identical PQL.Assert suites on every run, and every contract rule appears in the coverage report
- CI blocks any change that crosses the license boundary (imports, SPDX headers, wheel contents, dependency licenses)
