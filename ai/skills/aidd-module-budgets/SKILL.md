---
name: aidd-module-budgets
description: File-level size budgets for Python modules and test modules in this project, how to split a module that crossed one, and the seam to split on. Use when adding a test, adding a section to an existing module, reviewing a diff that grows a large file, or when the user asks why a file is so big.
---

# Module Budgets

The ruff configuration in `pyproject.toml` enforces *function*-level limits: complexity, arguments, branches, statements. But nothing measured *file size* — which is how `python/pql_test/runner.py` reached 1,947 lines mixing 9+ responsibilities without a single review objecting: every diff that grew it was small, and the only thing wrong with it was the total.

A file nobody can hold in their head costs on every read — human or agent. An agent asked to change one behavior loads the whole module.

## Budgets

| Unit | Soft (justify) | Hard (split before merging) |
|------|---------------|------------------------------|
| Source module | 400 lines | 800 lines |
| Test module | 500 lines | 900 lines |
| Tests per module | 40 | 80 |

**Soft** means: say in the commit message why this file earns the extra length.  
**Hard** means: the split is part of the task that crossed it, not a follow-up.

A test module tracks its subject. If your source module is over budget, splitting the tests first is often cheaper — tests are more mechanical to partition and reveal the natural seams in the source.

## Where to Split a Source Module

Split on the **responsibility seam**, following Single Responsibility Principle:

```sudolang
fn chooseSeam(module) {
  Prefer: distinct collaborators or external dependencies
    (ADOMD.NET loading | REST API | filesystem | process detection)
  Then:   data vs logic
    (models/dataclasses | parsers | executors | resolvers)
  Then:   public API vs private helpers
    (exposed functions | internal utilities)
  Never:  alphabetical or by line range
  Never:  "part 2" / "_more" / "_utils" — that is the same file with a new name
}
```

**Example from runner.py refactor:**
- `runner/models.py` — all dataclasses (pure data, zero logic)
- `runner/adomd.py` — ADOMD.NET assembly loading (one external dependency)
- `runner/local_pbi.py` — local PBI process detection (psutil + Windows API)
- `runner/pbi_rest.py` — Power BI REST API (urllib, JSON)
- `runner/auth.py` — MSAL token acquisition (MSAL + stored credentials)
- `runner/model_path.py` — path parsing (filesystem + regex)
- `runner/resolver.py` — XMLA connection resolution (orchestration)
- `runner/discovery.py` — test discovery (filesystem + XMLA queries)
- `runner/execution.py` — test execution (ADOMD.NET + result parsing)

Each module has one clear responsibility and minimal coupling to the others.

## Where to Split a Test Module

Split on the **behavior seam**, not on the epic that added the tests.

Section banners named after epic sections (`# ... (CLI Agent Ergonomics §3)`) are a tell that a file grew by accretion. §3 is when the code arrived, not what it does. Six months later nobody greps for §3.

```sudolang
fn chooseTestSeam(tests) {
  Prefer: the observable behavior under test
    (exit codes | output contract | discovery | auth flow | local detection | service connection)
  Then:   the collaborator being faked
    (subprocess | filesystem | network | keyring | process detection)
  Never:  the epic or task number that introduced the test
  Never:  "part 2" / "_more" / "_extra" — that is the same file with a new name
}
```

**Name the file after the seam**: `test_runner_local_detection.py`, not `test_runner_2.py`. A reader should predict the filename from the failure message.

**Example splits:**
- `test_pql_test_runner.py` (monolith) →
  - `test_runner_model_path_parsing.py` — ModelIdentifier, path formats
  - `test_runner_local_detection.py` — PBI Desktop process/port detection
  - `test_runner_service_connection.py` — REST API, MSAL, XMLA resolution
  - `test_runner_discovery.py` — Test file enumeration, live discovery
  - `test_runner_execution.py` — XMLA execution, result parsing

## Shared Setup After a Split

Fixtures used by more than one of the new modules move to `tests/conftest.py`.  
Fixtures used by exactly one move with it.  

**Do not** create a `tests/helpers.py` that every module imports — that rebuilds the monolith through the import graph.

## The Review Lens

When reviewing a diff, check the file the diff lands in, not only the diff:

1. **Did this diff push a file past a budget?** If yes, the split belongs in this change. A +120-line diff on a 1,900-line file reads as clean and is not.
2. **Is there a section banner naming an epic?** Rename it after the behavior, or move the section out.
3. **Is the new code placed by topic or by append?** Code appended to the bottom because that is where the cursor was is a file-shape smell.

## Check

To check module sizes by hand:

```bash
# Show all Python files with line counts, sorted largest first
find python -name '*.py' -exec wc -l {} + | sort -rn | head -20
```

To check test module test counts:

```bash
# Count test functions per file (grep for 'def test_')
for f in $(find python/tests -name 'test_*.py'); do
  count=$(grep -c '^def test_' "$f" 2>/dev/null || echo 0)
  echo "$count $f"
done | sort -rn | head -20
```

## Module Budget Test (Ratchet Pattern)

Create `tests/test_module_budget.py` to prevent silent budget violations:

```python
"""
Module size budget enforcement.

Fails the suite if any source or test module exceeds its hard budget without
a documented exemption.
"""
import pytest
from pathlib import Path

# Hard budgets
SOURCE_HARD_BUDGET = 800
TEST_HARD_BUDGET = 900
TESTS_PER_MODULE_HARD = 80

# Exemptions (name → (limit, reason, date))
EXEMPTIONS = {
    # Example:
    # "python/pql_test/legacy_code.py": (850, "Legacy module, split planned for v0.3", "2026-08-30"),
}

def count_lines(file_path: Path) -> int:
    """Count non-blank, non-comment lines."""
    lines = file_path.read_text(encoding="utf-8").splitlines()
    return sum(1 for line in lines if line.strip() and not line.strip().startswith("#"))

def count_tests(file_path: Path) -> int:
    """Count test functions in a test file."""
    content = file_path.read_text(encoding="utf-8")
    return content.count("\ndef test_")

@pytest.mark.parametrize("file_path", list(Path("python/pql_test").rglob("*.py")))
def test_source_module_budget(file_path):
    """Source modules must be under 800-line hard budget unless exempted."""
    if file_path.name == "__init__.py":
        pytest.skip("__init__.py files exempted")
    
    lines = count_lines(file_path)
    str_path = str(file_path)
    
    if str_path in EXEMPTIONS:
        limit, reason, date = EXEMPTIONS[str_path]
        assert lines <= limit, f"{str_path} exceeds exempted limit {limit} (exemption: {reason}, dated {date})"
    else:
        assert lines <= SOURCE_HARD_BUDGET, f"{str_path} is {lines} lines (hard budget: {SOURCE_HARD_BUDGET})"

@pytest.mark.parametrize("file_path", list(Path("python/tests").rglob("test_*.py")))
def test_test_module_budget(file_path):
    """Test modules must be under 900-line hard budget unless exempted."""
    lines = count_lines(file_path)
    test_count = count_tests(file_path)
    str_path = str(file_path)
    
    if str_path in EXEMPTIONS:
        limit, reason, date = EXEMPTIONS[str_path]
        assert lines <= limit, f"{str_path} exceeds exempted limit {limit} (exemption: {reason}, dated {date})"
    else:
        assert lines <= TEST_HARD_BUDGET, f"{str_path} is {lines} lines (hard budget: {TEST_HARD_BUDGET})"
    
    assert test_count <= TESTS_PER_MODULE_HARD, f"{str_path} has {test_count} tests (hard budget: {TESTS_PER_MODULE_HARD})"
```

**Add to CI workflow** (non-gating soft budget report):

```yaml
- name: Module size report
  run: |
    echo "## Source modules over soft budget (400 lines)" >> $GITHUB_STEP_SUMMARY
    find python/pql_test -name '*.py' ! -name '__init__.py' -exec wc -l {} + | awk '$1 > 400 {print}' | sort -rn >> $GITHUB_STEP_SUMMARY || true
    echo "## Test modules over soft budget (500 lines)" >> $GITHUB_STEP_SUMMARY  
    find python/tests -name 'test_*.py' -exec wc -l {} + | awk '$1 > 500 {print}' | sort -rn >> $GITHUB_STEP_SUMMARY || true
```

## When to Raise a Budget

Raising a budget is a **decision with a reason**, same rule as ruff thresholds.

Valid reasons:
- **Generated code** (e.g., Protobuf bindings) — document in exemption
- **Table-driven logic** where splitting would duplicate the table structure
- **Public API module** that must remain a single import for backward compatibility

Invalid reasons:
- "It's easier to keep it all in one file"
- "I don't have time to split it now" (then make the time — the hard budget exists precisely to prevent this)
- "The tests are passing" (passing tests don't make a 2,000-line file maintainable)

**Process:**
1. Add exemption to `EXEMPTIONS` dict with reason and date
2. Document in commit message
3. File a follow-up epic to split the module (unless it's genuinely exempt forever)
4. Get explicit approval in code review

Report the number, do not silently raise the budget.
