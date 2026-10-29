# Custom Agent Instructions for pql-test

Add project-specific agent instructions here. Settings in this file override the root AGENTS.md.

## Project-Specific Rules

- **Python is the primary language** — All core logic is in Python >= 3.10
- **Follow PEP 8** — Use type annotations, Google-style docstrings
- **CLI uses Click** — The CLI framework is Click >= 8.1
- **CLI output goes through `cli_format.py`** — Any new command printing a session banner, bordered table, or status color must reuse `python/pql_test/runner/cli_format.py`, not a new per-command implementation. See [CONTRIBUTING.md's CLI Output Conventions](../CONTRIBUTING.md#cli-output-conventions) before writing presentation code for a command.
- **XMLA/ADOMD.NET is Windows-only** — pyadomd requires Windows and .NET runtime
- **Test with pytest** — Run `cd python && pytest` for unit tests
- **DAX test files** — Must follow `*.Tests.dax` naming in `DAXQueries/` directories
- **Plugin skills** — Live in `skills/` at repo root, mapped by `plugin.json`
- **Version bumps** — Follow `aidd-custom/skills/pql-test-version-bump/SKILL.md`: `python/pyproject.toml`, `plugin.json`, and every SKILL.md (source + packaged) always carry the same version
- **CI pipeline** — 3 stages: validate-plugin → promptfoo-eval → run-tests-remote
- **License** — Everything is AGPL-3.0-only (see `LICENSES.md`); every `.py` file starts with `# SPDX-License-Identifier: AGPL-3.0-only`. Runtime dependencies must be AGPL-compatible (MIT, BSD, Apache-2.0, LGPL, GPL-3.0). The Bitol ODCS schemas (Apache-2.0) and the vendored PQL.Assert test fixture (MIT) keep their own licenses.
- **Contract commands** — `pql-test contract` lives in `python/pql_test/odcs/` (file-only: lint, coverage, generate, trace) and `python/pql_test/contract_run.py` (connected: run, doctor). The file-only commands must run without ADOMD.NET (Linux CI), so import XMLA code lazily.
- **No plaintext secrets** — Use environment variables for credentials (PQL_TENANT_ID, PQL_CLIENT_ID, PQL_CLIENT_SECRET, etc.)
- **Secrets and security checks** — Never commit `.env` files, certificates, or keys (gitignored). The pre-commit hooks run gitleaks, a private-key check, and bandit before every commit, and CI repeats them on the full history; never bypass them with `--no-verify`. A finding that is not a secret is allowlisted by fingerprint in `.gitleaksignore` with the reason, and a bandit false positive gets `# nosec <id>` with the reason. See CONTRIBUTING.md, "Secrets and security checks".
- **Documentation step** — The documentation step of an AIDD review (`/aidd-review` step 9, "Check documentation") always runs `aidd-custom/skills/pql-test-docs-check/SKILL.md`, which checks dead links, the README copies, and the skill copies. Run it too whenever README, CONTRIBUTING, docs/, or a skill changes.
