# Open-Source Readiness: Docs Links and Security Epic

**Status**: ✅ COMPLETED (2026-10-28), pending the maintainer steps in plan.md Open Items

**Changed during the work (2026-10-28):**
- The documentation step lives in a project skill (`aidd-custom/skills/pql-test-docs-check`) plus a rule in `aidd-custom/AGENTS.md`, not in `ai/skills/aidd-review`, which `aidd upgrade` overwrites.
- The fixed `requests`, `urllib3`, and `python-dotenv` releases need Python 3.10+, so their floors apply only there; Python 3.9 (end of life) keeps the old versions. Raising `requires-python` to 3.10 is a vision change, left to the maintainer.
- bandit 1.9.4 still flags the SafeLoader `yaml.load` and the `"0.0.0.0"` address comparisons, so those lines carry `# nosec` with the reason in a comment above.
- The link check also fixed `docs/contracts.md` (`#pqlassert-08`) and the Power BI Desktop URL in CONTRIBUTING.

**Goal**: Before the repository goes public, prove no secret was ever committed, stop one from being committed in future (locally and in CI), fix the security flaws a scan finds, and make the documentation step check for dead links.

## Overview

The repository will be open-sourced. A public repository needs:
- proof that history holds no secrets, and hooks that keep it that way;
- the Python code and dependencies scanned for known flaws;
- workflows safe to run on outside contributions;
- a way to report vulnerabilities.

The README links have just been fixed by hand; the documentation step of the AIDD review should catch dead links every time.

**Decided 2026-10-28 (maintainer):** use gitleaks; check before every commit and in CI; include a dead-link check in the documentation step.

**Findings on 2026-10-28:**
- **gitleaks history (195 commits, all branches):** one finding, the public client ID `5814bfb4-…` in a deleted file. It is an app identifier, not a secret.
- **gitleaks working tree:** the real client secrets sit only in the gitignored `python/.env` and `python/tests/.env`.
- **bandit:**
  - the ADOMD.NET auto-download loads DLLs from an unverified package, and its extraction allows zip slip;
  - `urlopen` calls have no timeout;
  - the YAML loader is a `SafeLoader` (a false positive).
- **pip-audit:** `requests` 2.32.5, `urllib3` 2.6.3, and `python-dotenv` 1.2.1 have published fixes.
- **Workflows:** `run-tests-remote.yml` interpolates the `test_name` input into a shell command.

---

## Dead links in the documentation step

**Requirements**:
- Given `.github/scripts/check_links.py`, should report dead relative links, unknown `#anchors` (also into other Markdown files), and, with `--external`, unreachable URLs, in the README copies, CONTRIBUTING, docs/, and the skills
- Given a project skill `pql-test-docs-check`, should be the documentation step: README copies identical, links alive, skills byte-identical; `aidd-custom/AGENTS.md` should require it in the review's documentation step and whenever docs change
- Given CI, should run the offline link check on every push

---

## Secrets: gitleaks locally and in CI

**Requirements**:
- Given `.pre-commit-config.yaml`, should run gitleaks on staged changes, detect private keys, block large files, and run bandit on `python/pql_test` before every commit
- Given CI, should scan the full history with a pinned, checksum-verified gitleaks, and fail on any finding
- Given the public client ID finding, should be allowlisted by fingerprint in `.gitleaksignore`, with the reason

---

## Security fixes

**Requirements**:
- Given the ADOMD.NET auto-download, should verify the package's SHA-512 against a pinned value before extracting, and refuse members that would land outside the cache folder
- Given every `urlopen` call, should set a timeout
- Given the dependencies, should set floors that exclude the published vulnerabilities, and CI should run pip-audit
- Given `run-tests-remote.yml`, should pass workflow inputs through environment variables
- Given bandit false positives, should mark each with `# nosec <id>` and the reason

---

## Policy and docs

**Requirements**:
- Given SECURITY.md, should say how to report a vulnerability privately
- Given CONTRIBUTING, should document the hooks, how to install them, and what to do when gitleaks finds something
- Given `.github/dependabot.yml`, should keep pip dependencies and GitHub Actions up to date
