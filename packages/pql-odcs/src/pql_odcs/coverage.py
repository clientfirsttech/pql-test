# SPDX-License-Identifier: MIT
"""Coverage report: every contract rule with its status (mapped / approximated / skipped).

JSON shape (``schemaVersion`` 1)::

    {
      "schemaVersion": 1,
      "generator": "pql-odcs 0.1.0",
      "catalog": {"library": "PQL.Assert", "minVersion": "0.7.1"},
      "contract": {"id": "...", "name": "...", "apiVersion": "3.1.0", "source": "x.odcs.yaml"},
      "summary": {"total": 4, "mapped": 3, "approximated": 0, "skipped": 1},
      "rules": [
        {"ruleId": "T.id.primaryKey", "status": "mapped", "description": "...",
         "assertions": 1, "functions": ["<catalog fn for col.distinct>"],
         "severity": "error", "reason": null}
      ]
    }
"""

from __future__ import annotations

from collections.abc import Sequence

from pql_odcs import __version__
from pql_odcs.catalog import Catalog, load_catalog
from pql_odcs.ir import RuleOutcome, Status
from pql_odcs.loader import Contract

SCHEMA_VERSION = 1


def build_report(
    contract: Contract,
    outcomes: Sequence[RuleOutcome],
    *,
    catalog: Catalog | None = None,
    version: str = __version__,
) -> dict:
    """Build the JSON-serialisable coverage report for *outcomes*."""
    catalog = catalog or load_catalog()
    rules = []
    for o in outcomes:
        severities = sorted({a.severity for a in o.assertions})
        rules.append(
            {
                "ruleId": o.rule_id,
                "status": o.status.value,
                "description": o.description,
                "assertions": len(o.assertions),
                "functions": [catalog.op(a.op).fn for a in o.assertions],
                "severity": severities[0] if len(severities) == 1 else None,
                "reason": o.reason,
            }
        )
    summary = {"total": len(outcomes)}
    summary.update({s.value: sum(1 for o in outcomes if o.status is s) for s in Status})
    return {
        "schemaVersion": SCHEMA_VERSION,
        "generator": f"pql-odcs {version}",
        "catalog": {"library": catalog.library, "minVersion": catalog.min_version},
        "contract": {
            "id": contract.id,
            "name": contract.name,
            "apiVersion": contract.api_version,
            "source": contract.source,
        },
        "summary": summary,
        "rules": rules,
    }


def skipped_count(report: dict) -> int:
    return report["summary"]["skipped"]


def format_text(report: dict) -> str:
    """Plain-text table: one line per rule; mapped rules show their functions, others the reason."""
    c, s = report["contract"], report["summary"]
    lines = [
        (
            f"Contract {c['id']} (ODCS v{c['apiVersion']}) — {s['total']} rules: "
            f"{s['mapped']} mapped, {s['approximated']} approximated, {s['skipped']} skipped"
        ),
        "",
    ]
    width = max([len(r["ruleId"]) for r in report["rules"]] + [4])
    lines.append(f"  {'STATUS':<13}{'RULE':<{width + 2}}DETAIL")
    for r in report["rules"]:
        detail = r["reason"] if r["status"] != Status.MAPPED.value else ", ".join(r["functions"])
        if r["status"] == Status.MAPPED.value and r["severity"] == "warning":
            detail += " (warning)"
        lines.append(f"  {r['status']:<13}{r['ruleId']:<{width + 2}}{detail}")
    return "\n".join(lines) + "\n"
