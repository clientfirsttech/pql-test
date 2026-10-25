# Licenses in this repository

This repository holds two separately licensed packages. [LICENSE.txt](LICENSE.txt), the Business Source License 1.1, covers everything **except** the paths listed below with a different license.

| Path | License | Published as | May depend on |
|---|---|---|---|
| `python/`, and every other path not listed here | BUSL-1.1 ([LICENSE.txt](LICENSE.txt)) | `pql-test` on PyPI | `pql-odcs` (optional `contracts` extra) |
| `packages/pql-odcs/` | MIT ([packages/pql-odcs/LICENSE](packages/pql-odcs/LICENSE)) | `pql-odcs` on PyPI | PyYAML, jsonschema, click only |
| `packages/pql-odcs/src/pql_odcs/schemas/*.json` | Apache-2.0 ([LICENSE-ODCS.txt](packages/pql-odcs/src/pql_odcs/schemas/LICENSE-ODCS.txt)) | inside `pql-odcs` | — (unmodified Bitol ODCS JSON schemas, attributed in [NOTICE](packages/pql-odcs/NOTICE)) |

## The boundary is one-way

- pql-test (BUSL-1.1) may depend on pql-odcs (MIT).
- pql-odcs never imports, vendors, or copies pql-test code.
- pql-odcs knows two things about pql-test, and both are data: PQL.Assert function names and argument order (kept in its catalog), and pql-test's documented `--output` JSON shape.

## How CI enforces it

The `pql-odcs` workflow runs these blocking checks on every pull request:

- **Import boundary**: an import-linter contract forbids `pql_odcs` from importing `pql_test`.
- **SPDX headers**: every `.py` file under `packages/pql-odcs/` starts with `# SPDX-License-Identifier: MIT`, and every `.py` file under `python/` starts with `# SPDX-License-Identifier: BUSL-1.1`.
- **Wheel contents**: the pql-odcs wheel contains only `pql_odcs/` and its own `LICENSE` and `NOTICE`.
- **Dependency licenses**: pql-odcs's resolved runtime dependencies must be MIT, BSD, or Apache-2.0 licensed.

## Contributions

Contributions to `packages/pql-odcs/` need a [DCO](https://developercertificate.org/) sign-off (`git commit -s`), and [CODEOWNERS](.github/CODEOWNERS) requires review from a pql-odcs maintainer. See [CONTRIBUTING.md](CONTRIBUTING.md#contributing-to-pql-odcs-mit).

*This file describes how the repository is organized. It is not legal advice.*
