---
name: pql-test-version-bump
description: Bump the pql-test release version consistently across pyproject.toml, plugin.json, and every source and packaged SKILL.md. Use when shipping a user-visible change, adding or editing a skill, preparing a release tag, or when the version-alignment test or CI check fails.
allowed-tools: Bash(git:*)
---

# pql-test version bump

Act as a release engineer. pql-test ships one version across every manifest;
a bump is not done until all of them agree.

## Files that carry the version

| File | Field |
|---|---|
| `python/pyproject.toml` | `version = "X.Y.Z"` (source of truth — `release.yml` checks the `vX.Y.Z` tag against it) |
| `plugin.json` | `"version": "X.Y.Z"` (Copilot CLI plugin manifest) |
| `skills/*/SKILL.md` | `version: X.Y.Z` frontmatter (source skills) |
| `python/pql_test/skills/*/SKILL.md` | `version: X.Y.Z` frontmatter (packaged skills — must stay byte-identical to `skills/`) |

## Process

```sudolang
BumpVersion(newVersion) {
  1. Decide whether a bump is needed:
     git tag --sort=-v:refname | head -1   // latest released version
     if pyproject version > latest tag => the version is still unreleased; keep it
       (add the new work to the pending release instead of bumping again)
     else => pick newVersion per PEP 440 / semver (patch for fixes and small
       features, minor for new commands or breaking skill-contract changes)
  2. Update every file in the table above to newVersion.
  3. Re-sync packaged skills: each python/pql_test/skills/<name>/SKILL.md must be
     byte-identical to skills/<name>/SKILL.md.
  4. Verify:
     cd python && pytest tests/test_version_alignment.py tests/test_skill_content.py
  5. Record the bump in plan.md / the commit message
     (e.g. "chore: bump to X.Y.Z").
}

Constraints {
  Never bump only pyproject.toml — plugin.json and all SKILL.md files move with it.
  Never edit installed skill copies (.claude/skills/pql-test/**) — they are
    per-machine installs, refreshed with `pql-test skill --install <harness>`.
  Keep old version numbers in CONTRIBUTING.md examples as-is; they are illustrative.
}
```

## Pre-release (beta) versions

The `X.Y.Z` in the table above is the common case, but every guard (the pytest
alignment test, the CI step, and `release.yml`'s tag check) does a plain
string comparison — not a semver/format check — so a PEP 440 pre-release
suffix is a valid value everywhere `X.Y.Z` is, as long as it's applied
identically across all files:

- Append a suffix directly to the base version, e.g. `0.1.18b1` (beta 1),
  `0.1.18rc1` (release candidate 1). No dot before the suffix — that's what
  PEP 440 expects and what PyPI parses.
- A beta tagged and pushed as `v0.1.18b1` publishes to PyPI as a pre-release:
  `pip install pql-test` skips it unless the installer passes `--pre` or pins
  the exact version. This is the mechanism for a rehearsal/beta release
  without affecting the default install.
- To promote a beta to the real release, bump every file in the table above
  from the pre-release value (e.g. `0.1.18b1`) to the plain `X.Y.Z` value
  (e.g. `0.1.18`) — drop the suffix — as a normal version bump, then tag
  `vX.Y.Z`. Don't skip straight to the next patch/minor — the beta and its
  stable release should carry the same base version unless new changes
  landed in between.

## Guards

- `python/tests/test_version_alignment.py` fails pytest when `plugin.json` or
  any SKILL.md differs from `pyproject.toml`.
- The "Versions aligned with pyproject.toml" step in
  `.github/workflows/validate-plugin.yml` fails CI for the same drift.
- `release.yml` fails when the pushed `vX.Y.Z` tag differs from `pyproject.toml`.
