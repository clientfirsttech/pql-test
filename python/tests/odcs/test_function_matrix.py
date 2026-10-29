# SPDX-License-Identifier: AGPL-3.0-only
"""Every PQL.Assert function is reachable from a contract, or out of scope for a stated reason.

``pql_test/odcs/catalog/pql_assert_functions.yaml`` classifies each function as ``mapped``
(an ODCS rule generates it), ``dax`` (only an ``engine: pql-test`` rule calls it), or ``none``.
These tests keep that file equal to the vendored PQL.Assert release and to the catalogs, so a
function PQL.Assert adds fails here until someone decides how contracts reach it.
"""

from __future__ import annotations

from pathlib import Path

from pql_test.odcs.catalog import PQL_ASSERT_CATALOGS, load_catalog, load_signatures
from pql_test.odcs.udf import parse_functions

LIBRARY = Path(__file__).resolve().parent / "fixtures" / "pql-assert-0.8.0" / "lib"
OUT_OF_SCOPE_PREFIXES = ("PQL.Assert.BP.", "PQL.Assert.RetrieveTests", "PQL.Assert.LibraryVersion")


def _library() -> dict:
    functions = []
    for tmdl in sorted(LIBRARY.glob("*.tmdl")):
        functions.extend(parse_functions(tmdl.read_text(encoding="utf-8-sig")))
    return {fn.name: fn for fn in functions}


def _catalog_functions() -> set[str]:
    return {spec.fn for name in PQL_ASSERT_CATALOGS.values() for spec in load_catalog(name).ops.values()}


def test_signatures_match_the_vendored_library():
    given = "the packaged signature list and the vendored PQL.Assert 0.8.0 library"
    should = "list exactly the library's functions with their parameter counts"
    library = _library()

    actual = {name: (s.params, s.optional) for name, s in load_signatures().functions.items()}
    expected = {name: (len(fn.parameters), sum(1 for p in fn.parameters if p.optional)) for name, fn in library.items()}

    assert actual == expected, f"{given}: {should}"


def test_mapped_means_a_catalog_calls_it():
    given = "functions classified as mapped"
    should = "be exactly the functions some catalog op calls"
    mapped = {name for name, s in load_signatures().functions.items() if s.use == "mapped"}

    assert mapped == _catalog_functions(), f"{given}: {should}"


def test_only_non_assertions_are_out_of_scope():
    given = "functions classified as none"
    should = "be only the best-practice checks and the discovery helpers"
    out = sorted(name for name, s in load_signatures().functions.items() if s.use == "none")

    assert [n for n in out if not n.startswith(OUT_OF_SCOPE_PREFIXES)] == [], f"{given}: {should}"


def test_every_callable_function_takes_a_test_name_first():
    given = "every function a contract can call"
    should = "take testName as its first parameter, which pql-test supplies"
    library = _library()
    callable_names = [name for name, s in load_signatures().functions.items() if s.callable]

    wrong = [n for n in callable_names if not library[n].parameters or library[n].parameters[0].name != "testName"]

    assert wrong == [], f"{given}: {should}"
