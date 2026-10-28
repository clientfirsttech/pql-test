# SPDX-License-Identifier: AGPL-3.0-only
"""Property-based tests: random valid contracts never crash the pipeline, and every rule gets a status."""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from pql_test.odcs.api import plan_contract, render
from pql_test.odcs.coverage import build_report
from pql_test.odcs.ir import Status
from pql_test.odcs.results import trace

NAMES = st.from_regex(r"[A-Za-z][A-Za-z0-9_ ']{0,12}", fullmatch=True)
NUMBER = st.integers(min_value=-5, max_value=10_000) | st.floats(min_value=0, max_value=1e6, allow_nan=False)
OPERATORS = st.sampled_from(
    ["mustBe", "mustNotBe", "mustBeGreaterThan", "mustBeGreaterOrEqualTo", "mustBeLessThan", "mustBeLessOrEqualTo"]
)


@st.composite
def quality_rule(draw, on_property: bool):
    kind = draw(st.sampled_from(["library", "library", "library", "sql", "text", "custom"]))
    severity = draw(st.sampled_from([None, "error", "warning", "info"]))
    if kind == "sql":
        rule = {"type": "sql", "query": "SELECT 1", draw(OPERATORS): draw(NUMBER)}
    elif kind == "text":
        rule = {"type": "text", "description": draw(NAMES)}
    elif kind == "custom":
        rule = {"type": "custom", "engine": "soda", "implementation": "x"}
    else:
        metrics = ["nullValues", "missingValues", "invalidValues", "duplicateValues"] if on_property else ["rowCount"]
        rule = {"metric": draw(st.sampled_from(metrics))}
        if draw(st.booleans()):
            low = draw(st.integers(0, 100))
            rule[draw(st.sampled_from(["mustBeBetween", "mustNotBeBetween"]))] = [low, low + draw(st.integers(1, 100))]
        else:
            rule[draw(OPERATORS)] = draw(NUMBER)
    if severity:
        rule["severity"] = severity
    return rule


@st.composite
def schema_object(draw):
    names = draw(st.lists(NAMES, min_size=0, max_size=5, unique=True))
    props = []
    for name in names:
        p = {"name": name, "logicalType": draw(st.sampled_from(["string", "integer", "number", "date", "object"]))}
        for flag in ("required", "unique", "primaryKey"):
            if draw(st.booleans()):
                p[flag] = True
        if draw(st.booleans()):
            p["quality"] = draw(st.lists(quality_rule(on_property=True), max_size=3))
        props.append(p)
    obj = {"name": draw(NAMES), "properties": props}
    if draw(st.booleans()):
        obj["quality"] = draw(st.lists(quality_rule(on_property=False), max_size=3))
    return obj


@st.composite
def contracts(draw):
    return {
        "apiVersion": draw(st.sampled_from(["v3.0.2", "v3.1.0", "v3.2.0"])),
        "kind": "DataContract",
        "id": draw(NAMES),
        "name": draw(NAMES),
        "version": "1.0.0",
        "status": "active",
        "schema": draw(st.lists(schema_object(), max_size=4, unique_by=lambda o: o["name"])),
    }


def _upgrade_for_3_0(data: dict) -> dict:
    """ODCS 3.0 names the library metric `rule`; keep generated 3.0 contracts valid."""
    if data["apiVersion"] != "v3.0.2":
        return data
    for obj in data["schema"]:
        for holder in [obj, *obj["properties"]]:
            for rule in holder.get("quality") or []:
                if "metric" in rule:
                    rule["type"] = "library"
                    rule["rule"] = rule.pop("metric")
    return data


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(contracts(), st.booleans())
def test_random_contracts_map_render_and_trace_without_crashing(data, closed_schema):
    plan = plan_contract(_upgrade_for_3_0(data), closed_schema=closed_schema)

    files = render(plan, env="DEV")
    report = build_report(plan.contract, plan.outcomes)
    traced = trace(plan, {"results": []})

    ids = [o.rule_id for o in plan.outcomes]
    assert len(ids) == len(set(ids)), "every rule should have a unique id"
    assert all(o.status is Status.MAPPED or o.reason for o in plan.outcomes), "unmapped rules need a reason"
    assert report["summary"]["total"] == len(plan.outcomes), "coverage should list every rule"
    assert len(traced.rules) == len(plan.outcomes), "trace should report every rule"
    assert all(f.content.endswith("\n") and "\r" not in f.content for f in files), "suites should be LF text"
