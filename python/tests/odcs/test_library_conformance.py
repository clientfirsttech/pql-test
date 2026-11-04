# SPDX-License-Identifier: AGPL-3.0-only
"""Every catalog op must call a function that the released PQL.Assert library defines.

The fixture under ``fixtures/pql-assert-0.9.0/`` is the released PQL.Assert 0.9.0 package
(see its README). 0.9.0 keeps every 0.8.x name and signature, so all three catalogs are
checked against it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pql_test.odcs.catalog import PQL_ASSERT_CATALOGS, load_catalog
from pql_test.odcs.udf import library_versions, parse_functions

LIBRARY = Path(__file__).resolve().parent / "fixtures" / "pql-assert-0.9.0"
# Catalog argument source -> the PQL.Assert parameter types it can be passed as (pql_test.odcs.emit.dax).
_TABLE = {"TABLE", "TABLE EXPR"}
SOURCE_TYPES = {
    "testName": {"STRING"},
    "tableName": {"STRING"},
    "columnList": {"STRING"},
    "columnName": {"STRING"},
    "dataType": {"STRING"},
    "tableRef": _TABLE,
    "keyProjection": _TABLE,
    "columnRef": {"ANYREF EXPR"},
    "valueTable": _TABLE,
    "valueColumn": {"ANYREF EXPR"},
    "filteredRows": _TABLE,
    "refreshAgeHours": {"DOUBLE"},
}


def _library():
    functions = []
    for tmdl in sorted((LIBRARY / "lib").glob("*.tmdl")):
        functions.extend(parse_functions(tmdl.read_text(encoding="utf-8-sig")))
    return {fn.name: fn for fn in functions}


def test_fixture_is_the_whole_0_9_0_release():
    given = "the vendored PQL.Assert 0.9.0 fixture"
    should = "hold only 0.9.0 PQL.Assert functions, including LibraryVersion() returning 0.9.0"

    library = _library()

    assert (
        library_versions(library.values()),
        library["PQL.Assert.LibraryVersion"].expression,
    ) == ({"0.9.0": len(library)}, '() => "0.9.0"'), f"{given}: {should}"


@pytest.mark.parametrize("version", sorted(PQL_ASSERT_CATALOGS))
def test_every_catalog_op_calls_a_released_function(version):
    given = f"the PQL.Assert {version} catalog"
    should = "name only functions in the released library, with arguments each one accepts"
    library = _library()
    catalog = load_catalog(PQL_ASSERT_CATALOGS[version])

    problems = []
    for key, spec in sorted(catalog.ops.items()):
        fn = library.get(spec.fn)
        if fn is None:
            problems.append(f"{key}: {spec.fn} is not in PQL.Assert 0.9.0")
            continue
        required = sum(1 for p in fn.parameters if not p.optional)
        if not required <= len(spec.args) <= len(fn.parameters):
            signature = ", ".join(p.name for p in fn.parameters)
            problems.append(f"{key}: {spec.fn}({signature}) cannot take {len(spec.args)} arguments")
            continue
        for source, param in zip(spec.args, fn.parameters):
            expected = SOURCE_TYPES.get(source)
            if expected and param.type.upper() not in expected:
                problems.append(f"{key}: {source} is passed as {param.name} : {param.type}, not {sorted(expected)}")

    assert problems == [], f"{given}: {should}\n" + "\n".join(problems)
