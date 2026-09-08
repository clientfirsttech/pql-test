#!/usr/bin/env python3
"""Stdlib promptfoo-compatible skill eval runner.

Loads test cases from tests/*.yaml, injects live SKILL.md content into the
prompt template, calls GitHub Models (Claude Sonnet 4 by default), then
evaluates deterministic assertions locally and llm-rubric assertions via a
second grader call.

Offline behavior: if GITHUB_TOKEN is unset, prints a warning and exits 0 so
local dev never blocks on API access.

Usage:
    python run_eval.py               # Run all tests
    python run_eval.py --dry-run     # Validate test structure only
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent

# Import our provider for GitHub Models access + skill loading
sys.path.insert(0, str(HERE / "providers"))
from skill_provider import (  # noqa: E402
    DEFAULT_MODEL,
    call_github_models,
    load_skill,
    render_prompt,
)

RESULTS_FILE = HERE / "results.json"


# ---------------------------------------------------------------------------
# Minimal YAML parser (avoids adding PyYAML as a runtime dep)
# ---------------------------------------------------------------------------
#
# Test files use a narrow subset of YAML: list of mappings with str/bool/int
# scalars, block-literal strings (|), and nested `assert` lists. Rather than
# depend on PyYAML for a hundred-line runner, we use a tiny purpose-built
# parser. For anything richer, contributors can install PyYAML and swap
# `_parse_yaml` for `yaml.safe_load`.

try:
    import yaml  # type: ignore[import]

    def _parse_yaml(text: str) -> Any:
        return yaml.safe_load(text)
except ImportError:
    print(
        "warning: PyYAML not installed; using minimal fallback parser. "
        "Install with `pip install pyyaml` for full YAML support.",
        file=sys.stderr,
    )

    def _parse_yaml(text: str) -> Any:  # pragma: no cover - fallback path
        raise RuntimeError(
            "PyYAML is required to run promptfoo evals. Install with `pip install pyyaml`."
        )


# ---------------------------------------------------------------------------
# Assertion evaluation
# ---------------------------------------------------------------------------


def _assert_contains(output: str, value: str) -> tuple[bool, str]:
    ok = value in output
    return ok, "" if ok else f"expected substring: {value!r}"


def _assert_icontains(output: str, value: str) -> tuple[bool, str]:
    ok = value.lower() in output.lower()
    return ok, "" if ok else f"expected case-insensitive substring: {value!r}"


def _assert_not_contains(output: str, value: str) -> tuple[bool, str]:
    ok = value not in output
    return ok, "" if ok else f"unexpected substring present: {value!r}"


def _assert_regex(output: str, value: str) -> tuple[bool, str]:
    ok = bool(re.search(value, output))
    return ok, "" if ok else f"expected regex: {value!r}"


def _assert_starts_with(output: str, value: str) -> tuple[bool, str]:
    ok = output.strip().startswith(value)
    return ok, "" if ok else f"expected output to start with: {value!r}"


def _assert_llm_rubric(output: str, rubric: str, model: str) -> tuple[bool, str]:
    """Grade output against a rubric using another Claude call."""
    grader_prompt = (
        "You are grading an LLM response against a rubric.\n\n"
        f"Response:\n---\n{output}\n---\n\n"
        f"Rubric:\n{rubric}\n\n"
        'Respond with a single JSON object: {"pass": true|false, "reason": "..."}\n'
        "Only output the JSON, nothing else."
    )
    try:
        raw = call_github_models(grader_prompt, model=model, temperature=0.0)
    except Exception as e:  # noqa: BLE001
        return False, f"grader error: {e}"

    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return False, f"grader returned non-JSON: {raw[:200]}"
    try:
        verdict = json.loads(match.group(0))
    except json.JSONDecodeError:
        return False, f"grader JSON invalid: {match.group(0)[:200]}"

    passed = bool(verdict.get("pass"))
    reason = verdict.get("reason", "")
    return passed, "" if passed else f"rubric fail: {reason}"


ASSERTION_HANDLERS = {
    "contains": _assert_contains,
    "icontains": _assert_icontains,
    "not-contains": _assert_not_contains,
    "regex": _assert_regex,
    "starts-with": _assert_starts_with,
}


def evaluate_assertions(
    output: str,
    assertions: list[dict[str, Any]],
    grader_model: str,
) -> tuple[bool, list[str]]:
    failures: list[str] = []
    for a in assertions:
        atype = a.get("type", "")
        value = a.get("value", "")
        if atype in ASSERTION_HANDLERS:
            ok, msg = ASSERTION_HANDLERS[atype](output, value)
        elif atype == "llm-rubric":
            ok, msg = _assert_llm_rubric(output, value, grader_model)
        else:
            ok, msg = False, f"unknown assertion type: {atype}"
        if not ok:
            failures.append(f"[{atype}] {msg}")
    return not failures, failures


# ---------------------------------------------------------------------------
# Test discovery
# ---------------------------------------------------------------------------


def load_test_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for yaml_file in sorted((HERE / "tests").glob("*.yaml")):
        raw = yaml_file.read_text(encoding="utf-8")
        parsed = _parse_yaml(raw)
        if not isinstance(parsed, list):
            continue
        for case in parsed:
            case["_source_file"] = yaml_file.name
            cases.append(case)
    return cases


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run(dry_run: bool = False) -> int:
    prompt_template = (HERE / "prompts" / "skill_prompt.txt").read_text(encoding="utf-8")
    model = os.environ.get("PQL_TEST_MODEL", DEFAULT_MODEL)
    grader_model = os.environ.get("PQL_TEST_GRADER_MODEL", model)

    cases = load_test_cases()
    print(f"Loaded {len(cases)} test case(s) from tests/*.yaml", file=sys.stderr)

    if dry_run:
        for case in cases:
            print(f"  - [{case['_source_file']}] {case.get('description', '<no description>')}")
        print("\nDry run complete — no API calls made.", file=sys.stderr)
        return 0

    if not os.environ.get("GITHUB_TOKEN"):
        print(
            "\nwarning: GITHUB_TOKEN is not set. Skipping LLM evaluation.\n"
            "         Set GITHUB_TOKEN with `models: read` scope to run Mode B tests.\n",
            file=sys.stderr,
        )
        RESULTS_FILE.write_text(
            json.dumps({"results": [], "stats": {"skipped": len(cases), "reason": "no GITHUB_TOKEN"}}, indent=2),
            encoding="utf-8",
        )
        return 0

    results: list[dict[str, Any]] = []
    passed = 0
    failed = 0

    for i, case in enumerate(cases, 1):
        desc = case.get("description", f"case {i}")
        vars_ = case.get("vars", {})
        skill_name = vars_.get("skill")
        task = vars_.get("task", "")

        print(f"[{i}/{len(cases)}] {desc}", file=sys.stderr)

        try:
            skill_content = load_skill(skill_name) if skill_name else ""
        except FileNotFoundError as e:
            results.append({"description": desc, "success": False, "error": str(e)})
            failed += 1
            continue

        prompt = render_prompt(prompt_template, skill_content, task)

        try:
            output = call_github_models(prompt, model=model, temperature=0.0)
        except Exception as e:  # noqa: BLE001
            results.append({"description": desc, "success": False, "error": str(e)})
            failed += 1
            continue

        ok, failures = evaluate_assertions(output, case.get("assert", []), grader_model)
        results.append(
            {
                "description": desc,
                "source_file": case["_source_file"],
                "output": output,
                "success": ok,
                "failures": failures,
            }
        )
        if ok:
            passed += 1
            print(f"    PASS", file=sys.stderr)
        else:
            failed += 1
            print(f"    FAIL — {'; '.join(failures)}", file=sys.stderr)

    summary = {
        "stats": {"passed": passed, "failed": failed, "total": len(cases)},
        "results": results,
    }
    RESULTS_FILE.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"\n{passed} passed, {failed} failed, {len(cases)} total", file=sys.stderr)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    sys.exit(run(dry_run=dry))
