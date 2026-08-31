# Skill Testing with Promptfoo Epic

**Status**: ✅ COMPLETED (2026-08-31)
**Goal**: Every pql-test skill is validated by two complementary layers — deterministic pytest content assertions (fast, always-on gate) and LLM-graded promptfoo evaluations (realistic behavior check) — so skill drift, missing flags, and hallucinated commands are caught before shipping.

## Overview

Skills like `pql-test skill run-tests` are instructions for LLMs, but nothing currently validates that the SKILL.md files still teach the model correctly after CLI changes. The existing `promptfoo-eval.yml` CI workflow references `tests/promptfoo/run_eval.py` which does not exist, so the eval stage silently passes via `continue-on-error`. Add a dual-mode testing system: Mode A uses pytest to assert every documented flag, MODEL_PATH format, environment variable, and SudoLang contract block matches the actual CLI implementation; Mode B feeds each SKILL.md to Claude Sonnet 4 via GitHub Models with realistic user tasks and asserts the LLM produces valid pql-test commands. Together these prevent silent regressions when someone adds a flag to `cli.py` but forgets to document it, deletes a behavioral contract, or the skill becomes ambiguous enough that a competent LLM produces wrong commands.

### Prior art

- **`.github/skills/promptfoo-evals/SKILL.md`** — Repo already has copilot-side promptfoo guidance with deterministic-first, model-graded-sparingly patterns
- **`.github/workflows/promptfoo-eval.yml`** — CI workflow expects `tests/promptfoo/run_eval.py` (currently missing); has `permissions: models: read` for GitHub Models API
- **`python/tests/test_skill_packaging.py`** — Existing packaging validation pattern (frontmatter, version match, source/packaged sync)
- **`python/pql_test/cli.py`** — Click command definitions are the authoritative source for what flags should be documented

pql-test already has: pytest infrastructure, tomli-based pyproject parsing in tests, `permissions: models: read` in CI, skills_resolver for loading SKILL.md content.

## Configuration Decisions

1. **Epic-driven** — This file follows AIDD workflow (planned → in-progress → archived)
2. **New pytest module** — `test_skill_content.py` (separate concern from `test_skill_packaging.py`)
3. **LLM grader** — Claude Sonnet 4 via GitHub Models (`anthropic/claude-sonnet-4` — better instruction-following than gpt-4o-mini)
4. **Offline behavior** — Skip-and-warn: Mode B logs a warning and exits 0 if `GITHUB_TOKEN` is unset, so local dev without credentials never blocks
5. **Zero new runtime dependencies** — Mode A uses only stdlib + tomli (already installed); Mode B `run_eval.py` uses only stdlib `urllib.request`
6. **Package version** — Bump to 0.1.15 at epic completion per project convention

---

## Task 1: Add Mode A pytest content assertions

Create `python/tests/test_skill_content.py` with ~15 deterministic tests that fail immediately if a SKILL.md drifts from the actual CLI implementation.

**Requirements**:
- Given the `run-tests` skill, should document all Click flags from `cli.cmd_run_tests` (`--tenant-id`, `--workspace-id`, `--dataset-id`, `--client-id`, `--client-secret`, `--test`, `--verbose`, `--output`, `--log-format`, `--env`)
- Given the `run-tests` skill, should document all 3 MODEL_PATH formats (filesystem, `local/<name>`, `<workspace>.Workspace/<model>.SemanticModel`)
- Given the `run-tests` skill, should contain `Interface RunTests` block with `exit_code`, `output_format`, `log_annotations` fields
- Given the `run-tests` skill, should contain `Constraints` block covering MODEL_PATH resolution order, credential precedence, environment filtering
- Given the `run-tests` skill, should document exit codes 0 = passed, 1 = failed
- Given the `run-tests` skill, should document all supported env vars (`PQL_TENANT_ID`, `PQL_WORKSPACE_ID`, `PQL_DATASET_ID`, `PQL_CLIENT_ID`, `PQL_CLIENT_SECRET`, `PQL_ENVIRONMENT`, `PQL_TEST_ENV`)
- Given the `retrieve-tests` skill, should document `--env` flag with at least one example
- Given the `retrieve-test` skill, should document `--verbose` flag for full DAX source display
- Given the `check-prereqs` skill, should reference all 4 checks (Python 3.9+, pyadomd, msal, psutil)
- Given any skill, should contain at least one runnable `pql-test <command>` example
- Given any skill, should NOT reference the removed `--local` flag
- Given any skill, should only use command names that exist in the current CLI (`check-prereqs`, `retrieve-tests`, `retrieve-test`, `run-tests`, `skill`, `auth`)
- Given the CLI implementation adds a new flag to `cmd_run_tests`, the corresponding test should fail until SKILL.md is updated

**Extraction helper**: Load `pql_test.cli` module and enumerate `cli.pql_test.commands[name].params` to build the authoritative flag set — the test compares that set against the SKILL.md text.

---

## Task 2: Create promptfoo suite scaffold

Set up `tests/promptfoo/` directory structure with config, prompts, and provider skeleton (no test cases yet).

**Requirements**:
- Given the promptfoo directory, should contain `promptfooconfig.yaml` with `# yaml-language-server: $schema=https://promptfoo.dev/config-schema.json`
- Given the promptfoo config, should reference `providers/skill_provider.py` and glob `tests/*.yaml`
- Given the prompt template `prompts/skill_prompt.txt`, should include `{{skill_content}}` and `{{task}}` placeholders
- Given the prompt template, should instruct the LLM: "Do not invent flags or commands not shown in the skill above"
- Given `providers/skill_provider.py`, should load SKILL.md from `python/pql_test/skills/<name>/SKILL.md` based on a `skill` var and inject into prompt
- Given the scaffold, should include `README.md` explaining local run (`npx promptfoo eval`) vs. CI run (`python run_eval.py`)

---

## Task 3: Implement stdlib run_eval.py runner

Write `tests/promptfoo/run_eval.py` using only stdlib (`urllib.request`, `json`, `yaml` via optional import or plain parsing). This is what the existing `promptfoo-eval.yml` workflow already expects.

**Requirements**:
- Given `GITHUB_TOKEN` is unset, should print a warning to stderr and exit 0 (skip-and-warn)
- Given `GITHUB_TOKEN` is set, should call `https://models.github.ai/inference/chat/completions` (or the correct GitHub Models endpoint) with `anthropic/claude-sonnet-4` as the model
- Given each test YAML file in `tests/`, should load test cases and iterate through them
- Given a test case with `contains`/`not-contains`/`regex`/`icontains`/`starts-with` assertions, should evaluate deterministically without another LLM call
- Given a test case with `llm-rubric` assertion, should make a second call to grade the response against the rubric, using JSON response format
- Given all tests complete, should write `results.json` matching promptfoo output schema (`success`, `score`, `error` fields) so CI upload artifact works
- Given any test fails, should exit 1; given all pass, should exit 0
- Given the runner is invoked with `--dry-run`, should print test cases without calling the API

---

## Task 4: Write Mode B test cases for run-tests skill

Create `tests/promptfoo/tests/run-tests.yaml` with 10 scenarios covering the highest-value user tasks and hallucination guards.

**Requirements**:
- Given a task about running a local Power BI Desktop model, LLM should produce `pql-test run-tests` with `local/<name>` syntax
- Given a task about remote Fabric workspace with service principal, LLM should include `--tenant-id`/`--client-secret` or reference `PQL_*` env vars
- Given a task about GitHub Actions CI, LLM should use `--log-format github` and `--output`
- Given a task about Azure DevOps pipelines, LLM should use `--log-format azuredevops`
- Given a task about filtering to DEV environment, LLM should use `--env DEV`
- Given a task naming workspace and model, LLM should use canonical `<workspace>.Workspace/<model>.SemanticModel` path
- Given a task about running a single named suite, LLM should use `--test`
- Given a task about previewing tests without executing, LLM should NOT invent `--dry-run` and should suggest `retrieve-tests` instead
- Given a task about credential precedence (env vars vs `auth login`), LLM-graded rubric should confirm CLI flags > env vars > keyring
- Given a task about `--env DEV` and `ANY` suites, LLM-graded rubric should confirm `ANY` is not a wildcard

---

## Task 5: Write Mode B test cases for other skills

Create `tests/promptfoo/tests/{retrieve-tests,retrieve-test,check-prereqs,skill-command}.yaml` with 3-5 scenarios each.

**Requirements**:
- Given `retrieve-tests` skill and a task about listing suites, LLM should produce `pql-test retrieve-tests <path>`
- Given `retrieve-tests` skill and a JSON piping task, LLM-graded rubric should confirm default output is JSON
- Given `retrieve-tests` skill and env filter task, LLM should use `--env <name>`
- Given `retrieve-test` skill and a "show DAX source" task, LLM should include `--verbose`
- Given `check-prereqs` skill and a "verify setup" task, LLM should produce `pql-test check-prereqs`
- Given `skill` command skill and "install for Copilot" task, LLM should produce `pql-test skill --install copilot`
- Given `skill` command skill and "check what's installed" task, LLM should produce `pql-test skill --show`
- Given `skill` command skill and "install everywhere" task, LLM should produce `pql-test skill --all`

---

## Task 6: Wire into CI pipeline

Update `.github/workflows/promptfoo-eval.yml` to invoke the new `run_eval.py` correctly and pass the GitHub Models token for Anthropic access.

**Requirements**:
- Given the workflow runs on a skill file change, should execute `python3 run_eval.py` from `tests/promptfoo/`
- Given the workflow runs, should upload `results.json` as artifact (already configured — verify path)
- Given `PQL_TEST_MODEL` env var is set, should override the default `anthropic/claude-sonnet-4` model
- Given the eval succeeds, should annotate the workflow summary with pass/fail counts
- Given `GITHUB_TOKEN` has `models: read` permission (already declared), should succeed calling GitHub Models API

---

## Task 7: Document skill testing workflow

Add "Skill Testing" section to `CONTRIBUTING.md` under the existing "Skill Update Workflow" heading.

**Requirements**:
- Given a contributor adds a CLI flag, docs should instruct them to (1) update the skill, (2) run `pytest tests/test_skill_content.py` to verify
- Given a contributor changes skill wording, docs should mention running Mode B locally: `cd tests/promptfoo && GITHUB_TOKEN=... python run_eval.py`
- Given the contributor uses `--dry-run`, docs should note this validates test structure without API calls
- Given the section explains the two modes, should link to the epic archive after completion

---

## Task 8: Bump version to 0.1.15

Update package version and all skill versions per the "bump at end of every epic" convention established in the ADOMD.NET fix.

**Requirements**:
- Given `python/pyproject.toml`, version should be `0.1.15`
- Given all 4 files in `skills/*/SKILL.md`, version should be `0.1.15`
- Given all 4 files in `python/pql_test/skills/*/SKILL.md`, version should be `0.1.15`
- Given `test_skill_packaging.py` runs, all 6 tests should still pass
- Given a fresh `pip install -e .` and `pql-test skill --version`, should print `0.1.15`

---

## Definition of Done

- ✅ `pytest python/tests/test_skill_content.py -v` — all Mode A tests passing
- ✅ `python tests/promptfoo/run_eval.py --dry-run` — test structure valid, no API calls
- ✅ `python tests/promptfoo/run_eval.py` with `GITHUB_TOKEN` — at least 80% of Mode B scenarios pass
- ✅ `python tests/promptfoo/run_eval.py` without `GITHUB_TOKEN` — warns and exits 0 (offline safe)
- ✅ CI workflow `promptfoo-eval.yml` runs successfully (no longer silently missing script)
- ✅ Deliberately adding a fake `--fakeflag` to `cli.cmd_run_tests` — Mode A test fails
- ✅ Deliberately renaming `Interface RunTests` to `Interface Foo` in run-tests SKILL.md — Mode A test fails
- ✅ CONTRIBUTING.md documents both testing modes
- ✅ Package version bumped to 0.1.15
- ✅ All commits use conventional commit format
- ✅ Epic file archived to `tasks/archive/YYYY-MM-DD-skill-testing-promptfoo.md`

---

## Non-Goals

- Not adding npm/Node dependencies to CI (stdlib-only per existing `promptfoo-eval.yml` design)
- Not replacing `test_skill_packaging.py` — that stays for byte-for-byte source/packaged sync
- Not testing the `auth` command skill (no `auth` SKILL.md exists yet — separate epic)
- Not adding red-team / adversarial prompts — focus is correctness, not safety
- Not benchmarking multiple LLM providers — pick one (Claude Sonnet 4) and iterate
