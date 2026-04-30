#!/usr/bin/env python3
"""
Lightweight skill-documentation evaluator for pql-test.

Replaces the promptfoo / axios evaluation stack with plain Python stdlib HTTP.
No external dependencies – uses only urllib.request and json (both stdlib).

Environment variables:
  GITHUB_TOKEN      (required) Bearer token for GitHub Models API.
  PQL_TEST_MODEL    (optional) Override the LLM model, e.g. gpt-4o.
                    Default: value in cases.json (gpt-4o-mini).

Exit codes:
  0  All assertions passed (or API errors only – treated as warnings).
  1  One or more assertions failed.

Usage:
  python3 run_eval.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

GITHUB_MODELS_URL = "https://models.inference.ai.azure.com/chat/completions"
HERE = Path(__file__).parent
LLM_TIMEOUT_SECS = int(os.environ.get("LLM_TIMEOUT", "60"))


def _call_llm(model: str, prompt: str, token: str) -> str | None:
    """Send a single-turn chat request to the GitHub Models API.

    Returns the assistant message text, or None on any error (in which case a
    ::warning:: annotation is printed to stderr so that CI treats the run as a
    non-blocking warning rather than a hard failure).
    """
    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": 1024,
        }
    ).encode()

    req = urllib.request.Request(
        GITHUB_MODELS_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=LLM_TIMEOUT_SECS) as resp:
            data = json.loads(resp.read().decode())
            return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        print(
            f"::warning::GitHub Models HTTP {exc.code}: {body[:200]}",
            file=sys.stderr,
        )
        return None
    except Exception as exc:  # noqa: BLE001
        print(f"::warning::LLM request failed: {exc}", file=sys.stderr)
        return None


def main() -> None:
    config_path = HERE / "cases.json"
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)

    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print(
            "::warning::GITHUB_TOKEN is not set – skipping LLM evaluation.",
            file=sys.stderr,
        )
        sys.exit(0)

    model: str = os.environ.get("PQL_TEST_MODEL") or config.get("model", "gpt-4o-mini")
    template: str = config["prompt_template"]
    tests: list[dict] = config["tests"]

    passed = failed = errors = 0
    records: list[dict] = []

    print(f"\nSkill evaluation – model: {model}\n")

    for test in tests:
        desc: str = test["description"]
        skill_path = HERE / test["skill_file"]
        skill_content = skill_path.read_text(encoding="utf-8")
        question: str = test["question"]
        assertions: list[str] = test["assertions"]

        prompt = template.format(skill_content=skill_content, question=question)
        response = _call_llm(model, prompt, token)

        if response is None:
            errors += 1
            records.append({"description": desc, "success": False, "api_error": True})
            print(f"  \u2717  {desc}  (API/provider error)")
            continue

        # icontains: case-insensitive substring match (mirrors promptfoo behaviour)
        failed_assertions = [a for a in assertions if a.lower() not in response.lower()]

        if not failed_assertions:
            passed += 1
            records.append({"description": desc, "success": True})
            print(f"  \u2713  {desc}")
        else:
            failed += 1
            records.append(
                {
                    "description": desc,
                    "success": False,
                    "failed_assertions": failed_assertions,
                }
            )
            print(f"  \u2717  {desc}")
            for a in failed_assertions:
                print(f"       \u21b3 FAILED: expected response to contain '{a}'")

    total = passed + failed + errors
    print(f"\nResults: {passed}/{total} passed, {failed} failed, {errors} error(s)\n")

    # Write results.json so the workflow can upload it as an artifact
    results_path = HERE / "results.json"
    results_path.write_text(
        json.dumps(
            {
                "results": records,
                "stats": {"passed": passed, "failed": failed, "errors": errors},
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    if errors and not failed:
        print(
            f"::warning::{errors} test(s) could not run (API/provider error). "
            "This does not indicate a skill defect.",
            file=sys.stderr,
        )
        sys.exit(0)

    if failed:
        print(f"::error::{failed} assertion(s) failed.", file=sys.stderr)
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
