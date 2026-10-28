# PQL.Assert 0.8.0 (test fixture)

An unmodified copy of the released [PQL.Assert](https://github.com/clientfirsttech/PQL.Assert) 0.8.0 DAX Lib package. Copyright (c) 2026 Client First Technologies, MIT licensed; see [LICENSE](LICENSE).

- Source: `clientfirsttech/PQL.Assert`, `src/lib/*.tmdl` and `src/manifest.daxlib` at commit `3bc73c42a0fd4fa83d487e315912c49a6099deae` (manifest version 0.8.0).
- Used only by tests. It is not part of the pql-test package.
- `python/tests/odcs/test_library_conformance.py` checks that every op in pql-test's PQL.Assert catalogs calls a function defined here, with an argument count it accepts.
- pql-test's live tests use it to define 0.8.0 functions in the query when the model under test has an older PQL.Assert.

To update the fixture to a new PQL.Assert release, replace `lib/`, `manifest.daxlib`, and `LICENSE` from the release, then update the commit above.
