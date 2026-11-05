---
name: pql-test-docs-check
description: The documentation step for pql-test changes. Checks dead links (relative links, #anchors, and external URLs), that README.md matches python/README.md (the PyPI page), and that source and packaged skills are byte-identical. Use in the documentation step of an AIDD review (/aidd-review step 9), whenever README, CONTRIBUTING, docs/, or a skill changes, and before a release.
allowed-tools: Bash(git:*) Bash(python:*)
---

# pql-test documentation check

Act as a technical editor. Documentation is not done until every link works for every reader:
- on GitHub;
- on PyPI, which shows `python/README.md`;
- for agents reading the skills.

## Process

```sudolang
DocsCheck() {
  1. Dead links, offline (files and #anchors, including anchors into other .md files):
     python .github/scripts/check_links.py
  2. Dead links, online (also fetches every external URL):
     python .github/scripts/check_links.py --external
     // WARN "check by hand" (HTTP 403/429) = the site blocks scripts: open it in a browser.
  3. README copies and skills:
     cd python && pytest tests/test_readme_sync.py tests/test_readme_links.py tests/test_skill_packaging.py tests/test_skill_content.py
  4. Fix every DEAD line before finishing:
     - a link to another repository file from README.md -> an absolute
       https://github.com/clientfirsttech/pql-test/blob/main/... URL
       (python/README.md is a copy, so relative links break on PyPI);
     - an anchor -> the heading's GitHub anchor: lowercase; drop punctuation,
       including the dots in "PQL.Assert 0.8" -> #pqlassert-08; spaces become hyphens;
     - a moved page -> the final URL, not a redirect chain.
  5. Report what was checked and fixed, and any WARN left for a human to open.
}

Constraints {
  Edit README.md and python/README.md identically; the sync test fails otherwise.
  Edit skills/<name>/SKILL.md and python/pql_test/skills/<name>/SKILL.md identically.
  Never "fix" a dead link by deleting the reference without saying so; replace it, or report it.
  tasks/ is a historical record: its links are not checked.
}
```
