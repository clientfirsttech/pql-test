# SPDX-License-Identifier: AGPL-3.0-only
"""Check the repository's Markdown for dead links.

Checks, in each file:
- relative links: the target exists (from the file's own folder);
- ``#anchors``: a heading in the same file (or the linked .md file) has that GitHub anchor;
- links into this repository on GitHub (``.../pql-test/blob/main/...``): the file exists in the
  working tree (main may not have it until this branch is merged);
- with ``--external``: every other http(s) URL answers. 403 and 429 are reported as
  "check by hand" (sites that block scripts), not as dead.

Usage (from the repository root):
    python .github/scripts/check_links.py              # offline: files and anchors
    python .github/scripts/check_links.py --external   # also fetch external URLs

Exits 1 when a link is dead.
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Maintained docs. tasks/ and research/ are historical records and are not checked.
FILES = [
    "README.md",
    "python/README.md",
    "CONTRIBUTING.md",
    "LICENSES.md",
    "SECURITY.md",
    "vision.md",
    "docs/*.md",
    "skills/*/SKILL.md",
    "aidd-custom/AGENTS.md",
    "aidd-custom/skills/*/SKILL.md",
]
REPO_URL = re.compile(r"^https://github\.com/clientfirsttech/pql-test/(?:blob|tree)/main/(.+)$")
LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)|<a\s+[^>]*href=\"([^\"]+)\"")
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"


def _without_code(markdown: str) -> str:
    """Drop fenced code blocks and inline code: links there are examples."""
    return re.sub(r"`[^`\n]*`", "", re.sub(r"```.*?```", "", markdown, flags=re.DOTALL))


def slug(heading: str) -> str:
    """GitHub's anchor for a heading: code spans keep their text; other HTML tags are dropped."""
    parts = re.split(r"(`[^`]*`)", heading)
    text = "".join(p.strip("`") if p.startswith("`") else re.sub(r"<[^>]+>", "", p) for p in parts)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text).strip().lower()
    return "".join(c for c in text if c.isalnum() or c in " -_").replace(" ", "-")


def anchors(markdown: str) -> set[str]:
    counts: dict[str, int] = {}
    found = set()
    for line in re.sub(r"```.*?```", "", markdown, flags=re.DOTALL).splitlines():
        match = re.match(r"^#{1,6}\s+(.*?)\s*#*\s*$", line)
        if match:
            base = slug(match.group(1))
            counts[base] = counts.get(base, -1) + 1
            found.add(base if counts[base] == 0 else f"{base}-{counts[base]}")
    return found


def _anchor_problem(path: Path, fragment: str) -> str | None:
    if fragment and path.suffix == ".md" and fragment.lower() not in anchors(path.read_text(encoding="utf-8")):
        return f"no heading #{fragment} in {path.relative_to(ROOT).as_posix()}"
    return None


def check_file(md: Path) -> tuple[list[str], set[str]]:
    """Dead local links in *md*, and the external URLs it links to."""
    text = md.read_text(encoding="utf-8")
    problems, external = [], set()
    for match in LINK.finditer(_without_code(text)):
        target = match.group(1) or match.group(2)
        repo = REPO_URL.match(target)
        if repo:
            rel, _, fragment = repo.group(1).partition("#")
            path = ROOT / rel
            problems.append(f"{target}: not in the repository" if not path.exists() else _anchor_problem(path, fragment))
        elif target.startswith(("http://", "https://")):
            external.add(target)
        elif target.startswith("mailto:"):
            continue
        elif target.startswith("#"):
            problems.append(_anchor_problem(md, target[1:]) and f"{target}: no such heading")
        else:
            rel, _, fragment = target.partition("#")
            path = (md.parent / rel).resolve()
            problems.append(f"{target}: no such file" if not path.exists() else _anchor_problem(path, fragment))
    return [p for p in problems if p], external


def fetch(url: str) -> tuple[str, str | None]:
    """``(url, problem or None)``; a 403/429 is a warning (the site blocks scripts)."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        # http(s) URLs from our own docs (bandit B310 reviewed).
        with urllib.request.urlopen(request, timeout=20):  # nosec B310
            return url, None
    except urllib.error.HTTPError as exc:
        return url, f"check by hand: HTTP {exc.code}" if exc.code in (403, 429) else f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001 - any failure to answer is the finding
        return url, f"{type(exc).__name__}: {exc}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--external", action="store_true", help="Also fetch external URLs.")
    args = parser.parse_args()

    files = sorted({p for pattern in FILES for p in ROOT.glob(pattern) if p.is_file()})
    dead, urls = 0, {}
    for md in files:
        problems, external = check_file(md)
        for problem in problems:
            print(f"DEAD  {md.relative_to(ROOT).as_posix()}: {problem}")
        dead += len(problems)
        for url in external:
            urls.setdefault(url, md.relative_to(ROOT).as_posix())
    if args.external:
        with ThreadPoolExecutor(12) as pool:
            for url, problem in sorted(pool.map(fetch, urls)):
                if problem:
                    kind = "WARN" if problem.startswith("check by hand") else "DEAD"
                    print(f"{kind}  {urls[url]}: {url}: {problem}")
                    dead += kind == "DEAD"
    checked = f"{len(files)} files" + (f", {len(urls)} external URLs" if args.external else "")
    print(f"{dead} dead link(s) in {checked}." if dead else f"No dead links in {checked}.")
    return 1 if dead else 0


if __name__ == "__main__":
    sys.exit(main())
