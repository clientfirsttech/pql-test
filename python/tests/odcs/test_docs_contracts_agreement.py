# SPDX-License-Identifier: AGPL-3.0-only
"""``docs/contracts.md``'s hand-written mapping tables stay in sync with the mapping code.

Three directions:
1. Every PQL.Assert function the docs name is a real function (any classification) —
   catches a renamed or removed function left stale in prose.
2. Every function a catalog actually generates is named in the docs somewhere — catches a
   new mapping landing without a docs update (``test_odcs_rule_matrix.py`` is the forcing
   function that would have required this fixture or test to exist in the first place).
3. The "skipped" / "not planned" tables' stated reasons match what the mapper actually
   produces for a representative unmapped rule — catches a reason that changed wording on
   one side and not the other.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from pql_test.odcs.api import plan_contract
from pql_test.odcs.catalog import PQL_ASSERT_CATALOGS, load_catalog, load_signatures
from pql_test.odcs.ir import Status
from tests.odcs.factories import contract_dict, prop, schema_object

DOCS = (Path(__file__).resolve().parent.parent.parent.parent / "docs" / "contracts.md").read_text(encoding="utf-8")
# Backtick-stripped, case-folded: a keyword phrase can cross a `code span` boundary in prose
# ("add a `logicalType` or a `pbiDataType`"), and a table cell may capitalise what a reason
# string does not ("Regular expressions beyond..." vs "regular expressions beyond...").
DOCS_PLAIN = DOCS.replace("`", "").lower()
_IDENT_RE = re.compile(r"\b[A-Z][A-Za-z0-9]*(?:\.[A-Z][A-Za-z0-9]*)*\b")


def _doc_function_mentions() -> set[str]:
    """Every ``Should*`` / ``LibraryVersion`` identifier inside a backtick span in the docs.

    Prose sometimes names a function once in full (``Col.ShouldEndWith``) and a sibling once
    bare (``ShouldEndWith``), relying on the shared prefix read from context — both forms are
    collected, short-form included, so a bare mention still counts as naming the function.
    """
    names = set()
    for span in re.findall(r"`([^`]*)`", DOCS):
        for ident in _IDENT_RE.findall(span):
            if "Should" in ident or ident == "LibraryVersion":
                names.add(ident.removeprefix("PQL.Assert."))
    return names


def _known(name: str, universe: set[str]) -> bool:
    """A doc mention *name* (full or bare) matches a real function in *universe* (full names)."""
    return name in universe or any(full.rsplit(".", 1)[-1] == name for full in universe)


def _named_in(function: str, mentions: set[str]) -> bool:
    """A real function *function* (full name) is named in *mentions* (full or bare)."""
    return function in mentions or function.rsplit(".", 1)[-1] in mentions


def test_every_function_docs_name_is_a_real_pql_assert_function():
    given = "every PQL.Assert function docs/contracts.md names in backticks"
    should = "be a function the bundled PQL.Assert 0.9.0 library actually has (any classification)"
    all_functions = {name.removeprefix("PQL.Assert.") for name in load_signatures().functions}

    unknown = [n for n in _doc_function_mentions() if not _known(n, all_functions)]

    assert unknown == [], f"{given}: {should}\nUnknown: {', '.join(sorted(unknown))}"


def test_every_catalog_generated_function_is_named_in_docs():
    given = "every function some catalog op (0.7, 0.8, or 0.9) actually calls"
    should = "be named in docs/contracts.md somewhere (full or bare form)"
    catalog_functions = {
        spec.fn.removeprefix("PQL.Assert.")
        for version in PQL_ASSERT_CATALOGS.values()
        for spec in load_catalog(version).ops.values()
    }
    mentioned = _doc_function_mentions()

    missing = [f for f in catalog_functions if not _named_in(f, mentioned)]

    assert missing == [], f"{given}: {should}\nMissing: {', '.join(sorted(missing))}"


def _reason(contract: dict, rule_id: str, pql_assert: str = "0.8") -> str:
    plan = plan_contract(contract, pql_assert=pql_assert)
    outcome = next(o for o in plan.outcomes if o.rule_id == rule_id)
    assert outcome.status is Status.SKIPPED, f"{rule_id} was not skipped: {outcome.status}"
    return outcome.reason


# (contract, rule_id, doc keyword) — the keyword must appear in both the real skip reason
# and docs/contracts.md's explanatory prose, so either side drifting from the other fails
# this test. Limited to rows the docs actually explain *why* (not the final "Planned" table,
# which deliberately only states a plan, e.g. "later" for `type: sql` — nothing to cross-check
# there beyond the rule kind itself, which existing golden files already pin byte-for-byte).
_SKIP_CASES = [
    (
        # No `prop()` here: it defaults logicalType to "string", which this case must omit.
        contract_dict(schema=[schema_object("T", [{"name": "a", "physicalType": "DECIMAL(10,2)"}])]),
        "T.a.type",
        "pbidatatype",
    ),
    (
        contract_dict(schema=[schema_object("T", [prop("a", "string", logicalTypeOptions={"pattern": "a.b*"})])]),
        "T.a.pattern",
        "regular expressions beyond",
    ),
    (
        contract_dict(schema=[schema_object("T", [prop("a", "number", logicalTypeOptions={"exclusiveMaximum": 5})])]),
        "T.a.range",
        "exclusivemaximum",
    ),
    (
        contract_dict(
            schema=[
                schema_object(
                    "T",
                    [
                        prop(
                            "a",
                            "date",
                            quality=[
                                {"metric": "invalidValues", "mustBe": 0, "arguments": {"validValues": ["2020-01-01"]}}
                            ],
                        )
                    ],
                )
            ]
        ),
        "T.a.quality[0]",
        "value lists on date and time columns",
    ),
    (
        contract_dict(
            schema=[schema_object("T", [])],
            slaProperties=[{"property": "latency", "value": 1, "unit": "d", "element": "T"}],
        ),
        "slaProperties[0]",
        "refresh time is not source latency",
    ),
]


@pytest.mark.parametrize("contract,rule_id,keyword", _SKIP_CASES, ids=[c[2] for c in _SKIP_CASES])
def test_a_documented_skip_reason_matches_what_the_mapper_produces(contract, rule_id, keyword):
    given = f"a rule that should stay skipped for {keyword!r}"
    should = "produce a real reason containing that keyword, and docs/contracts.md's prose should say the same thing"

    reason = _reason(contract, rule_id)

    assert (keyword in reason.lower(), keyword in DOCS_PLAIN) == (
        True,
        True,
    ), f"{given}: {should}\nreal reason: {reason!r}"
