# Custom Agent Instructions for pql-test

Add project-specific agent instructions here. Settings in this file override the root AGENTS.md.

## Project-Specific Rules

- **Python is the primary language** — All core logic is in Python >= 3.9
- **Follow PEP 8** — Use type annotations, Google-style docstrings
- **CLI uses Click** — The CLI framework is Click >= 8.1
- **XMLA/ADOMD.NET is Windows-only** — pyadomd requires Windows and .NET runtime
- **Test with pytest** — Run `cd python && pytest` for unit tests
- **DAX test files** — Must follow `*.Tests.dax` naming in `DAXQueries/` directories
- **Plugin skills** — Live in `skills/` at repo root, mapped by `plugin.json`
- **CI pipeline** — 3 stages: validate-plugin → promptfoo-eval → run-tests-remote
- **No plaintext secrets** — Use environment variables for credentials (PQL_TENANT_ID, PQL_CLIENT_ID, PQL_CLIENT_SECRET, etc.)
