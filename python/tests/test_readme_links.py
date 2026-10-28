# SPDX-License-Identifier: AGPL-3.0-only
"""README links: relative links resolve from both copies, and #anchors name a heading.

README.md is copied to python/README.md, which is also the PyPI page, so a relative link must
work from both folders. Links to other repository files belong as absolute GitHub URLs.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "README.md").read_text(encoding="utf-8")
BODY = re.sub(r"```.*?```", "", README, flags=re.DOTALL)  # links in code blocks are examples
LINKS = re.findall(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)", BODY) + re.findall(r"!\[[^\]]*\]\(([^)\s]+)\)", BODY)


def _slug(heading: str) -> str:
    """GitHub's anchor for a heading: code spans keep their text; other HTML tags are dropped."""
    parts = re.split(r"(`[^`]*`)", heading)
    text = "".join(p.strip("`") if p.startswith("`") else re.sub(r"<[^>]+>", "", p) for p in parts)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text).strip().lower()
    return "".join(c for c in text if c.isalnum() or c in " -_").replace(" ", "-")


def _anchors() -> set[str]:
    counts: dict[str, int] = {}
    found = set()
    for line in BODY.splitlines():
        match = re.match(r"^#{1,6}\s+(.*?)\s*#*\s*$", line)
        if match:
            base = _slug(match.group(1))
            counts[base] = counts.get(base, -1) + 1
            found.add(base if counts[base] == 0 else f"{base}-{counts[base]}")
    return found


def test_relative_links_resolve_from_both_readme_copies():
    given = "every relative link in README.md"
    should = "point at a file that exists from the repo root and from python/ (PyPI); use a GitHub URL otherwise"
    relative = [link.partition("#")[0] for link in LINKS if not link.startswith(("http://", "https://", "mailto:", "#"))]

    dead = [f"{link} (from {folder.name or 'root'})" for link in relative for folder in (ROOT, ROOT / "python") if not (folder / link).exists()]

    assert dead == [], f"{given}: {should}: {dead}"


def test_anchor_links_name_a_heading():
    given = "every #anchor link in README.md"
    should = "match a heading's GitHub anchor"
    anchors = _anchors()

    dead = [link for link in LINKS if link.startswith("#") and link[1:].lower() not in anchors]

    assert dead == [], f"{given}: {should}: {dead}"
