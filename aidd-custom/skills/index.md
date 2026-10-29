## Skills Index

- pql-test-version-bump - Bump the pql-test release version consistently across pyproject.toml, plugin.json, and every source and packaged SKILL.md. Use when shipping a user-visible change, adding or editing a skill, preparing a release tag, or when the version-alignment test or CI check fails.
- pql-test-docs-check - The documentation step for pql-test changes. Checks dead links (relative links, #anchors, and external URLs), that README.md matches python/README.md (the PyPI page), and that source and packaged skills are byte-identical. Use in the documentation step of an AIDD review (/aidd-review step 9), whenever README, CONTRIBUTING, docs/, or a skill changes, and before a release.
