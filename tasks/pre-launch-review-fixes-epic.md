# Pre-Launch Review Fixes Epic

**Status**: ✅ COMPLETED (2026-11-05), pending the maintainer steps in plan.md Open Items

**Changed during the work (2026-11-05):**
- Bot-authored pull requests get empty secrets in Stage 3a and skip Stage 3b, instead of moving the secrets into a reviewed Environment, which would hold every CI run for approval.
- `auth login` reads `PQL_CLIENT_SECRET` only when both `--client-id` and `--tenant-id` are given; `--client-id` alone still opens the browser.
- The AIDD license is `LICENSE-AIDD.txt` at the root, not `ai/LICENSE`, because `aidd upgrade` overwrites `ai/`.
- Not done, by decision: splitting cli.py (2,200 lines) is its own refactor; the AIDD tooling docs (UPGRADING.md, TESTING-AIDD.md, COPILOT-QUICKSTART.md) stay at the root where `aidd` expects them; SECURITY.md gets no fallback email until the maintainer picks one.

**Goal**: Fix every finding of the 2026-11-05 pre-launch AIDD review (security, licensing, docs, stray files) before the repository goes public.

## Overview

The pre-launch review found no critical issue, but public launch changes who can write issues and open pull requests, and who reads logs. Agent-written code must not run with the service principal secret, PyPI publishing must be gated to tags, CI log commands must not be spoofable by model data, and the licensing files must agree with the CLA and credit the vendored AIDD framework (MIT, Copyright (c) 2025 Eric Elliott).

Maintainer-only items (deleting old Actions runs, the Corporate CLA and past-contributor IP decisions, launch-day repository settings) stay in plan.md.

---

## Secrets out of bot-authored pull requests

Stop agent- or bot-authored code from running with repository secrets.

**Requirements**:
- Given a pull request opened by a bot (gh-aw issue agent, Copilot coding agent, Dependabot), Stage 3a should run without the `PQL_*` secrets and Stage 3b should be skipped
- Given a push to a `copilot/**` branch, CI should not run with secrets (the push trigger is removed; `pull_request` covers those branches)

---

## PyPI publishing gated to tags

**Requirements**:
- Given a `workflow_dispatch` with `target=pypi` from a branch, should not publish
- Given any publish from a `v*` tag, should verify the tag matches the pyproject version
- Given the publish-pypi job, should run in a `pypi` Environment (reviewers and tag-only deployment set by the maintainer)
- Given the build job, should install pinned `build` and `twine`

---

## Escape CI logging commands

**Requirements**:
- Given a test message containing a newline, `%`, or `##vso[`, the Azure DevOps output should not start a new logging command
- Given a test name or message with `%`, `:`, `,`, CR or LF, the GitHub output should escape it per the workflow-command rules

---

## Smaller security fixes

**Requirements**:
- Given `cla.yml`, the job (not the step) should be skipped for comments that are not CLA comments on a pull request
- Given `auth login --client-id X --tenant-id T` and `PQL_CLIENT_SECRET` set, should log in as that service principal without the secret on the command line
- Given a skill name with a path separator or `..`, `resolve_skill_dir` should refuse it
- Given the `pql-test-remote.yml` template, should install pinned packages
- Given `.github/copilot-setup-steps.yml` (inert, wrong location, stale imports), should be removed
- Given CODEOWNERS, should cover `CLA.md`, `python/pyproject.toml`, `uv.lock`, and `scripts/`

---

## Licensing and attribution

**Requirements**:
- Given LICENSES.md, the Contributions section should require the CLA plus the DCO, matching CONTRIBUTING.md
- Given `ai/` (vendored AIDD), LICENSES.md and NOTICE should name the MIT license and Eric Elliott's copyright, with the full text in `ai/LICENSE`
- Given NOTICE (both copies), should name the `pql-assert-0.9.0` fixture
- Given `pql_test.__version__`, should equal the installed package version
- Given every `.py` and `.ps1` project source file, should carry the SPDX header, and a test should enforce it

---

## Docs and stray files

**Requirements**:
- Given the README (both copies), should link to CONTRIBUTING and the CLA, and link LICENSE.txt by absolute URL
- Given CONTRIBUTING and `release.yml`, should not say Environments need a paid plan
- Given `docs/contracts.md`, should state the `--pql-assert 0.9` requirement
- Given the contract gap-check skill, should check the DAX Lib registry for new PQL.Assert releases
- Given the link check, should cover `docs/**` and the other root Markdown files
- Given `python/requirements*.txt` (drifted from pyproject), should be removed and the CI cache keyed on `python/pyproject.toml`
- Given `python/coverage.json`, `research/`, and `docs/bun-typescript-conversion.md`, should be untracked or removed
- Given plan.md, should drop stale items and identifying details
