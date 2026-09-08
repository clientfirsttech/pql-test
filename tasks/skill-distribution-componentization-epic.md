# pql-test Skill Distribution & Componentization Epic

**Status**: ✅ COMPLETED
**Goal**: pql-test ships its own versioned, componentized skills and installs them to whatever harness is running, so skill files can never drift from the installed CLI version, and agents only load the reference sections they need.

## Overview

Today `skills/*/SKILL.md` files are hand-maintained and synced to consumer repos only through `plugin.json` — nothing stops a repo from running pql-test 0.2.x against a SKILL.md written for 0.1.x, and large skills (like `run-tests/SKILL.md`) force agents to consume all reference content on every load. Ship skill content inside the wheel (similar to how pql-test already packages Python modules), add a `pql-test skill` subcommand that prints or installs version-matched skills into whichever agent harness (Claude Code, Copilot, Cursor, Windsurf, ...) the consumer repo is using, and componentize large skills into main + `references/` following SudoLang conventions for behavioral contracts.

### Prior art

- **`rtk init`** demonstrates harness-detection with `--agent <claude|cursor|windsurf|...>`, `--show`, `--dry-run`, `--uninstall`, `--auto-patch` — exactly the anti-drift motivation we need here.
- **Anthropic's Agent Skills (SKILL.md)** standardizes format but distributes skills separately from CLI releases.
- **MCP** is tool/function-calling, not instruction docs.
- **`fab-test` skill distribution** (reference implementation): packages SKILL.md in wheel, `fab-test skill --install <harness>`, idempotent writes, harness auto-detection.
- **`dataflows-authoring-cli` componentization**: short main file + `references/` folder for detailed flag/example docs, reducing per-load context cost.
- **`aidd-sudolang-syntax`**: SudoLang `Interfaces`/`Constraints`/`fn` blocks for behavioral contracts (exit codes, output guarantees, precedence rules).

pql-test already has the foundation: pyproject.toml build system, Click CLI framework, and version-pinned package metadata.

---

## Task: Package skill content with the wheel

Move `skills/*/SKILL.md` files under a packaged resource path (similar to how Python modules are packaged) so they ship with every install and always match the package version from `pyproject.toml`.

**Requirements**:
- Given a `pip install`ed pql-test, should have all packaged SKILL.md files resolvable without network access
- Given a repo with local override skill files, should prefer local `skills/*/SKILL.md` over packaged versions (same pattern as `.env` overrides)
- Given packaged SKILL.md files, should have version metadata in frontmatter reflecting package version from `pyproject.toml` so drift is visible
- Given `pyproject.toml`, should include `[tool.setuptools.package-data]` entry for `pql_test = ["skills/**/*.md"]` to ensure skills are packaged in wheel
- Given CI pipeline, should verify packaged skills match source `skills/` directory content

---

## Task: Add `pql-test skill` command (print/install/show)

Add a new `skill` command group to `pql_test/cli.py` alongside existing commands. Implement `pql-test skill [NAME]` (print), `pql-test skill --install <harness>` (install), `pql-test skill --show` (report status), and `pql-test skill --uninstall` (remove).

**Requirements**:
- Given `pql-test skill`, should list all available skills with names and one-line descriptions
- Given `pql-test skill run-tests`, should print the packaged (or locally-overridden) run-tests/SKILL.md content to stdout
- Given `pql-test skill run-tests --format json`, should emit `{version, name, source_path, content}` for programmatic consumption
- Given `pql-test skill --list`, should output skill names only (one per line) for scripting
- Given `pql-test skill --version`, should print the package version from `pyproject.toml`
- Given missing packaged resources, should fail with clear message (exit code 1), not a stack trace

---

## Epic Vision (Definition of Done)

### Quality Gates (All Must Pass)

✅ **Ruff Check**: All code passes `ruff check python/` with zero violations

✅ **Code Review**: 
- Skill packaging mechanism is clear and maintainable
- Harness detection and install logic is robust
- Version pinning prevents drift
- Local override mechanism works correctly

✅ **Test Coverage**: 
- Overall test coverage ≥ 80% (`pytest --cov=pql_test --cov-fail-under=80`)
- Skill packaging verified in wheel
- Install/uninstall operations tested
- Harness detection tested
- All existing tests continue to pass

✅ **Documentation**: 
- README.md documents `pql-test skill` commands
- Skill file format documented
- Harness compatibility matrix documented
- CONTRIBUTING.md includes skill development guidance

---

## Task: Add harness install targets (`--install <harness>`)

Implement idempotent skill installation following `rtk init` conventions: detect existing harness config, never clobber differing local files without `--dry-run` warning, support `--show` and `--uninstall`.

**Requirements**:
- Given `pql-test skill --install claude`, should write/update `.github/skills/pql-test/*/SKILL.md` (or `.claude/skills/pql-test/...` per Claude Code convention) and report created/updated/unchanged per file
- Given `pql-test skill --install copilot`, should write Copilot custom-instructions equivalent to `.github/copilot-instructions.md` or `.vscode/copilot-instructions.md`
- Given `pql-test skill --install cursor`, should write to `.cursor/skills/pql-test/*.md`
- Given `pql-test skill --install windsurf`, should write to `.windsurf/skills/pql-test/*.md`
- Given `pql-test skill --install --dry-run`, should report what would change without writing any files
- Given `pql-test skill --show`, should report install state per harness: found/missing/version-mismatched (compare installed version from frontmatter to package version)
- Given `pql-test skill --uninstall`, should remove only artifacts this command created (use marker comment in files: `<!-- Installed by pql-test skill v{version} -->`)
- Given `pql-test skill --install --all`, should install to all detected harnesses in the workspace
- Given an unrecognized `--install` value, should list valid harness names (`claude`, `copilot`, `cursor`, `windsurf`, `cline`) and exit with code 1

---

## Task: Componentize large skills (split into main + references/)

Identify skills exceeding ~300 lines (starting with `run-tests/SKILL.md`) and split them into:
- **Main file** (`SKILL.md`): Frontmatter, quick-start usage, behavioral contract (exit codes, output format, precedence rules) written in SudoLang
- **References** (`references/*.md`): Detailed flag tables, worked examples, configuration options, credential setup

**Requirements**:
- Given `run-tests/SKILL.md`, should split into main file + references:
  - `references/model-path-formats.md` (filesystem, local/, Fabric-style paths)
  - `references/credentials.md` (service principal, environment variables, auth login)
  - `references/options.md` (all CLI flags with descriptions)
  - `references/log-formats.md` (GitHub Actions, Azure Pipelines output)
  - `references/examples.md` (all usage examples from current SKILL.md)
- Given the main `run-tests/SKILL.md` after split, should be <200 lines with table of contents linking each reference file
- Given any componentized skill, should preserve all factual content — no behavior silently dropped in the split
- Given the main file's table of contents, should include one-line "when to read this" notes for each reference (e.g., "Read when you need to understand connection string formats")
- Given skills under ~300 lines (check-prereqs, retrieve-test, retrieve-tests), should remain as single files (no unnecessary componentization)

---

## Task: Convert behavioral contracts to SudoLang

Rewrite the behavioral/contract sections of skill files (exit codes, JSON output guarantees, precedence rules, install idempotency) using SudoLang `Interfaces`, `Constraints`, and `fn` blocks following `aidd-sudolang-syntax` conventions.

**Requirements**:
- Given the main `run-tests/SKILL.md`, should have a SudoLang `Interface RunTests` block defining:
  - `exit_code: 0 | 1` (0 = all passed, 1 = one or more failed)
  - `output_format: "pytest-style" | "json" (when --output specified)`
  - `log_annotations: "github" | "azuredevops" (when --log-format specified)`
- Given the main file, should have a `Constraints` block defining:
  - "MODEL_PATH resolution order: local override > remote Fabric path > filesystem path"
  - "Credential precedence: CLI flags > PQL_* env vars > stored auth login credentials"
  - "When --env specified, only run suites matching `<Suite>.<ENV>.Tests.dax` naming convention"
- Given the main file, should have `fn` blocks for core operations:
  - `fn discover_tests(model_path, env?) -> TestSuite[]`
  - `fn execute_test(suite, connection_opts) -> TestResult`
  - `fn format_output(results, format) -> string | JSON`
- Given a section that's pure reference (flag tables, examples), should stay as markdown (SudoLang doesn't compress these usefully)
- Given the SudoLang rewrite, should preserve every behavioral guarantee currently in prose — no contracts silently weakened

---

## Task: Update packaging for multi-file skill resources

Extend pyproject.toml package-data configuration and wheel validation to handle componentized skills (main + references/ directories).

**Requirements**:
- Given `pyproject.toml`, should use glob `pql_test = ["skills/**/*.md"]` to package all skill markdown files recursively
- Given the packaged wheel, should contain all main SKILL.md files and their references/ subdirectories
- Given a new `pql_test/skills_resolver.py` module, should implement `resolve_skill_dir(name) -> Path` that:
  - Returns local `skills/{name}/` directory if it exists (repo override)
  - Falls back to packaged `pql_test/skills/{name}/` resource
  - Raises clear error if skill name not found
- Given `pql-test skill run-tests` (bare print), should print only the main SKILL.md file content (not references)
- Given `pql-test skill run-tests --format json`, should include `references: ["model-path-formats.md", ...]` array with reference filenames
- Given `pql-test skill --install <harness>`, should install full component set (main + all references/) and report per-file status
- Given `pql-test skill --uninstall`, should remove all files in the component set that have the `pql-test skill` installation marker

---

## Task: Add CI guards for skill format and freshness

Add pytest tests that verify:
1. Packaged skills match source skills/ directory (prevent drift)
2. Componentized skills have required SudoLang constructs (prevent format regression)
3. Skill frontmatter version matches package version from pyproject.toml

**Requirements**:
- Given a new `python/tests/test_skill_packaging.py`, should verify every skill in source `skills/` directory exists in packaged `pql_test/skills/` with identical content (byte-for-byte match or normalized line endings)
- Given the test suite, should fail if any main SKILL.md for a componentized skill is missing required SudoLang constructs: at least one `Interface`, `Constraints`, or `fn` block
- Given the test suite, should fail if any SKILL.md frontmatter `version` field doesn't match `pyproject.toml` version
- Given CI pipeline, should run `python/tests/test_skill_packaging.py` in the `validate-plugin` stage (Stage 1) to catch drift before deployment
- Given a failed check, should print diff showing which skills are out of sync or missing required format

---

## Task: Update vision.md and documentation

Document the skill distribution and componentization system as a core architectural principle.

**Requirements**:
- Given `vision.md`, should add to Architecture section:
  - "Skill Distribution — Skills ship versioned in the wheel, installable via `pql-test skill --install <harness>`, preventing version drift"
  - "Skill Componentization — Large skills (>300 lines) split into main + references/ for efficient agent context loading"
  - "SudoLang Behavioral Contracts — Skill behavioral guarantees (exit codes, output formats, precedence rules) authored in SudoLang `Interfaces`/`Constraints`/`fn` blocks per `aidd-sudolang-syntax` conventions"
- Given `vision.md` Success Criteria, should add:
  - "Skill files can be installed to any supported harness (`claude`, `copilot`, `cursor`, `windsurf`) via `pql-test skill --install`"
  - "CI validates that packaged skills match source and follow SudoLang format requirements"
- Given `CONTRIBUTING.md`, should document:
  - "When updating skills: edit source `skills/*/SKILL.md`, update frontmatter version to match pyproject.toml, run `pytest tests/test_skill_packaging.py` to verify"
  - "Large skills (>300 lines) should be componentized: main behavioral contract + `references/` for detailed docs"
- Given `README.md`, should add Usage section for:
  - `pql-test skill` (list skills)
  - `pql-test skill <name>` (print skill content)
  - `pql-test skill --install <harness>` (install to harness)
  - `pql-test skill --show` (report installation status)

---

## Task: Run ruff check before documentation

Per [vision.md](vision.md#definition-of-done) and AIDD workflow, run `ruff check` over `python/pql_test/` and fix any issues before the documentation updates in the task above.

**Requirements**:
- Given `ruff check python/pql_test/`, should pass with no errors or warnings
- Given any ruff violations, should fix them before proceeding with documentation tasks
- Given the CLI module `pql_test/cli.py`, should maintain PEP 8 compliance and type annotations throughout new `skill` command implementation
