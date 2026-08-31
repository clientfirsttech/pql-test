# pql-test skill promptfoo suite

This directory contains **Mode B** skill evaluations — LLM-graded tests that
feed each `SKILL.md` to Claude Sonnet 4 with realistic user tasks and assert
the LLM produces correct `pql-test` commands.

For **Mode A** (fast deterministic content assertions), see
[python/tests/test_skill_content.py](../../python/tests/test_skill_content.py).

## Structure

```
tests/promptfoo/
├── promptfooconfig.yaml       # Config for `npx promptfoo eval`
├── prompts/skill_prompt.txt   # Prompt template with {{skill_content}} + {{task}}
├── providers/skill_provider.py # Loads live SKILL.md, calls GitHub Models
├── tests/*.yaml               # Test cases, one file per skill
├── run_eval.py                # Stdlib runner (used by CI)
└── results.json               # Output artifact (uploaded by promptfoo-eval.yml)
```

## Running Locally

**With `GITHUB_TOKEN`** (requires `models: read` scope):

```powershell
cd tests/promptfoo
$env:GITHUB_TOKEN = "ghp_..."
python run_eval.py
```

**Without `GITHUB_TOKEN`**: the runner prints a warning and exits 0, so
local dev never blocks on API access.

**Dry run** (validates test structure without calling the API):

```powershell
python run_eval.py --dry-run
```

**With external promptfoo** (requires Node.js):

```powershell
npx promptfoo@latest eval -c promptfooconfig.yaml --no-cache
```

## Environment Variables

| Variable | Purpose | Default |
|---|---|---|
| `GITHUB_TOKEN` | GitHub Models API token (must have `models: read`) | required |
| `PQL_TEST_MODEL` | Model for skill response generation | `anthropic/claude-sonnet-4` |
| `PQL_TEST_GRADER_MODEL` | Model for `llm-rubric` grading | same as `PQL_TEST_MODEL` |

## Adding a New Test Case

1. Pick the right YAML file (`tests/run-tests.yaml`, `tests/retrieve-tests.yaml`, etc.)
2. Add a new list item:

   ```yaml
   - description: Short description of the scenario
     vars:
       skill: run-tests           # which SKILL.md to inject
       task: Natural language user task
     assert:
       - type: contains           # deterministic
         value: pql-test run-tests
       - type: llm-rubric         # LLM-graded
         value: The response must ...
   ```

3. Run locally with `python run_eval.py` to verify.

## Supported Assertion Types

| Type | Purpose |
|---|---|
| `contains` | Exact substring match |
| `icontains` | Case-insensitive substring |
| `not-contains` | Hallucination guard |
| `regex` | Pattern match |
| `starts-with` | Prefix check |
| `llm-rubric` | Second LLM call grades against rubric |

## CI Integration

The [promptfoo-eval.yml](../../.github/workflows/promptfoo-eval.yml) workflow
runs `python run_eval.py` on every push that touches `skills/**` or this
directory. The workflow uses `continue-on-error` because the grader model
(Claude Sonnet 4) may occasionally return non-JSON responses — Mode A pytest
tests are the authoritative gate.

Results are uploaded as the `eval-results` artifact for review.
