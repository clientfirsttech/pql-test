# SPDX-License-Identifier: AGPL-3.0-only
"""Join pql-test ``--output`` JSON results back to contract rule ids.

Written from pql-test's documented ``--output`` format (README, "Save JSON results"):
a top-level ``results`` list whose rows carry ``test_name``, ``passed``, ``skipped``,
and ``error``, plus optional ``suite_name``, ``expected``, ``actual``, ``message``.
When a whole suite cannot run, pql-test reports one failed row whose ``test_name``
is the suite name.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from pql_test.odcs.emit.dax import WARN_SUFFIX, assign_test_names, default_suite_prefix
from pql_test.odcs.ir import ERROR, WARNING, Status

# Rule status precedence when a rule has several assertions: worst first.
STATUSES = ("failed", "error", "not_executed", "passed", "skipped")
# Version of the JSON this report serializes to (see contract-run-result.schema.json).
REPORT_SCHEMA_VERSION = 1
_SUITE_RE = re.compile(r"^(?P<prefix>.+)\.(?P<suite>[A-Za-z]+)\.(?P<env>[A-Za-z0-9_]+)\.Tests$")


class ResultsError(Exception):
    """The results file is unreadable or not pql-test ``--output`` JSON."""


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    status: str  # one of STATUSES; "skipped" means the rule was never mapped to DAX
    severity: str | None
    description: str
    reason: str | None = None
    details: tuple[dict, ...] = ()


@dataclass(frozen=True)
class TraceReport:
    contract_id: str
    rules: list[RuleResult]
    unmatched: list[dict] = field(default_factory=list)

    def summary(self) -> dict:
        return {s: sum(1 for r in self.rules if r.status == s) for s in STATUSES}

    def to_json(self) -> dict:
        return {
            "schemaVersion": REPORT_SCHEMA_VERSION,
            "contract": self.contract_id,
            "summary": self.summary(),
            "rules": [
                {
                    "ruleId": r.rule_id,
                    "status": r.status,
                    "severity": r.severity,
                    "description": r.description,
                    "reason": r.reason,
                    "details": list(r.details),
                }
                for r in self.rules
            ],
            "unmatched": self.unmatched,
        }


def read_results(path: str | Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ResultsError(f"Cannot read results {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise ResultsError(f"{path} is not pql-test --output JSON (no top-level 'results' list).")
    return data


def _row_status(row: Mapping) -> str:
    if row.get("skipped"):
        return "not_executed"
    if row.get("error"):
        return "error"
    return "passed" if row.get("passed") else "failed"


def _detail(row: Mapping) -> dict:
    keys = ("test_name", "passed", "error", "expected", "actual", "message")
    return {k: row.get(k) for k in keys if row.get(k) is not None}


def trace(plan, results: Mapping, *, suite_prefix: str | None = None) -> TraceReport:
    """Map every result row to the contract rules that produced it."""
    contract, outcomes = plan.contract, plan.outcomes
    names = assign_test_names(contract, outcomes)
    by_name = {name: key for key, name in names.items()}
    prefix = suite_prefix or default_suite_prefix(contract)
    assertions = {id(a): a for o in outcomes for a in o.assertions}
    # Fallback join on the "ODCS <contractId> <ruleId>: " prefix, so a result still maps
    # when the description part drifted (edited description, renamed model table or column).
    by_rule = {o.rule_id: id(o.assertions[0]) for o in outcomes if o.assertions}
    rule_ids = sorted(by_rule, key=len, reverse=True)  # longest first: "a.b" before "a"
    name_prefix = f"ODCS {contract.id} "

    def lookup(test_name: str) -> int | None:
        if test_name in by_name:
            return by_name[test_name]
        if not test_name.startswith(name_prefix):
            return None
        rest = test_name[len(name_prefix) :]
        return next((by_rule[r] for r in rule_ids if rest.startswith(f"{r}: ")), None)

    seen: dict[int, list[Mapping]] = {}
    unmatched: list[dict] = []
    for row in results.get("results") or []:
        key = lookup(str(row.get("test_name", "")))
        if key is not None:
            seen.setdefault(key, []).append(row)
            continue
        match = _SUITE_RE.match(str(row.get("test_name", "")))
        is_suite_failure = match and row.get("test_name") == row.get("suite_name") and not row.get("passed")
        if is_suite_failure and match.group("prefix") == prefix:
            warn = match.group("env").endswith(WARN_SUFFIX)
            for k, a in assertions.items():
                if a.suite == match.group("suite") and (a.severity == WARNING) == warn:
                    seen.setdefault(k, []).append({**row, "error": row.get("error") or "suite failed to run"})
            continue
        unmatched.append(dict(row))

    rules = []
    for o in outcomes:
        severity = None
        if o.assertions:
            severity = ERROR if any(a.severity == ERROR for a in o.assertions) else WARNING
        if o.status is Status.SKIPPED:
            rules.append(RuleResult(o.rule_id, "skipped", severity, o.description, o.reason))
            continue
        statuses, details = [], []
        for a in o.assertions:
            rows = seen.get(id(a))
            statuses.extend(_row_status(r) for r in rows or [{"skipped": True}])
            details.extend(_detail(r) for r in rows or [])
        status = next(s for s in STATUSES if s in statuses)
        rules.append(RuleResult(o.rule_id, status, severity, o.description, None, tuple(details)))
    return TraceReport(contract.id, rules, unmatched)


def format_text(report: TraceReport) -> str:
    s = report.summary()
    lines = [
        (
            f"Contract {report.contract_id} — {len(report.rules)} rules: {s['passed']} passed, {s['failed']} failed, "
            f"{s['error']} error, {s['not_executed']} not executed, {s['skipped']} skipped"
        ),
    ]
    width = max([len(r.rule_id) for r in report.rules] + [4])
    for r in report.rules:
        if r.status == "passed":
            continue
        tag = " (warning)" if r.severity == WARNING else ""
        detail = r.reason or "; ".join(
            d.get("error") or f"Expected: {d.get('expected', '?')} | Actual: {d.get('actual', '?')}"
            for d in r.details
            if not d.get("passed")
        )
        lines.append(f"  {r.status:<13}{r.rule_id:<{width + 2}}{detail}{tag}")
    if report.unmatched:
        lines.append(f"Unmatched results ({len(report.unmatched)}): not generated from this contract")
        lines.extend(f"  {u.get('test_name')}" for u in report.unmatched)
    return "\n".join(lines) + "\n"
