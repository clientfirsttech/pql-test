# SPDX-License-Identifier: AGPL-3.0-only
"""Promptfoo provider that injects live SKILL.md content and calls GitHub Models.

Used by both `npx promptfoo eval` (as a `file://` provider) and by our stdlib
`run_eval.py` (imported directly).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = REPO_ROOT / "python" / "pql_test" / "skills"
DEFAULT_MODEL = "anthropic/claude-sonnet-4"
GITHUB_MODELS_ENDPOINT = "https://models.github.ai/inference/chat/completions"


def load_skill(skill_name: str) -> str:
    path = SKILLS_DIR / skill_name / "SKILL.md"
    if not path.exists():
        raise FileNotFoundError(f"Skill not found: {path}")
    return path.read_text(encoding="utf-8")


def render_prompt(template: str, skill_content: str, task: str) -> str:
    return template.replace("{{skill_content}}", skill_content).replace("{{task}}", task)


def call_github_models(
    prompt: str,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.0,
    token: str | None = None,
) -> str:
    """POST a single-turn chat completion to GitHub Models and return content."""
    token = token or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN not set; cannot call GitHub Models API")

    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        GITHUB_MODELS_ENDPOINT,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"GitHub Models HTTP {e.code}: {e.read().decode('utf-8', 'replace')}") from e

    return payload["choices"][0]["message"]["content"]


def call_api(prompt: str, options: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Promptfoo provider entrypoint.

    Reads the `skill` var from context.vars, loads its SKILL.md, and substitutes
    into the prompt (which already has {{skill_content}}).
    """
    config = (options or {}).get("config", {})
    model = config.get("model", DEFAULT_MODEL)
    temperature = float(config.get("temperature", 0.0))
    skill_name = context.get("vars", {}).get("skill")

    if skill_name:
        skill_content = load_skill(skill_name)
        prompt = prompt.replace("{{skill_content}}", skill_content)

    try:
        output = call_github_models(prompt, model=model, temperature=temperature)
        return {"output": output}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}
