# Licenses in this repository

pql-test is licensed under the [GNU Affero General Public License, version 3 only](LICENSE.txt) (SPDX `AGPL-3.0-only`).
Copyright (C) 2026 Client First Technologies. Every source file carries `# SPDX-License-Identifier: AGPL-3.0-only`.

These files carry their own license:

| Path | License | Notes |
|---|---|---|
| `python/pql_test/odcs/schemas/*.json` | Apache-2.0 ([LICENSE-ODCS.txt](python/pql_test/odcs/schemas/LICENSE-ODCS.txt)) | Unmodified Bitol ODCS JSON schemas, shipped in the package and attributed in [NOTICE](NOTICE) |
| `python/tests/odcs/fixtures/pql-assert-0.9.0/` | MIT ([LICENSE](python/tests/odcs/fixtures/pql-assert-0.9.0/LICENSE)) | Unmodified copy of PQL.Assert 0.9.0, used only by tests and not shipped |
| `ai/`, `.cursor`, and the AIDD-derived parts of `AGENTS.md` and `.github/agents/` | MIT ([LICENSE-AIDD.txt](LICENSE-AIDD.txt)) | The [AIDD Framework](https://github.com/paralleldrive/aidd), Copyright (c) 2025 Eric Elliott: development tooling, not shipped, attributed in [NOTICE](NOTICE) |

## Earlier releases

pql-test releases up to v0.1.x were published under the Business Source License 1.1 and keep that license. From 0.2.0 on, pql-test is AGPL-3.0-only. The ODCS contract commands (`pql-test contract …`) were developed as a separate MIT package, pql-odcs, which was never published; they are now part of pql-test under AGPL-3.0-only.

## Contributions

Outside contributors sign the [Contributor License Agreement](CLA.md) once; a bot asks on the first pull request. Under it you keep your copyright and license your contribution to Client First Technologies, which may also offer pql-test under other licenses. Every commit also needs a [DCO](https://developercertificate.org/) sign-off (`git commit -s`). See [CONTRIBUTING.md](CONTRIBUTING.md).

*This file describes how the repository is licensed. It is not legal advice.*
