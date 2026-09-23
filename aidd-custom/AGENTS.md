# Custom Agent Instructions for pql-test

Add project-specific agent instructions here. Settings in this file override the root AGENTS.md.

## Project-Specific Rules

- **Python is the primary language** — All core logic is in Python >= 3.9
- **Follow PEP 8** — Use type annotations, Google-style docstrings
- **CLI uses Click** — The CLI framework is Click >= 8.1
- **CLI output goes through `cli_format.py`** — Any new command printing a session banner, bordered table, or status color must reuse `python/pql_test/runner/cli_format.py`, not a new per-command implementation. See [CONTRIBUTING.md's CLI Output Conventions](../CONTRIBUTING.md#cli-output-conventions) before writing presentation code for a command.
- **XMLA/ADOMD.NET is Windows-only** — pyadomd requires Windows and .NET runtime
- **Test with pytest** — Run `cd python && pytest` for unit tests
- **DAX test files** — Must follow `*.Tests.dax` naming in `DAXQueries/` directories
- **Plugin skills** — Live in `skills/` at repo root, mapped by `plugin.json`
- **Version bumps** — Follow `aidd-custom/skills/pql-test-version-bump/SKILL.md`: `python/pyproject.toml`, `plugin.json`, and every SKILL.md (source + packaged) always carry the same version
- **CI pipeline** — 3 stages: validate-plugin → promptfoo-eval → run-tests-remote
- **No plaintext secrets** — Use environment variables for credentials (PQL_TENANT_ID, PQL_CLIENT_ID, PQL_CLIENT_SECRET, etc.)
