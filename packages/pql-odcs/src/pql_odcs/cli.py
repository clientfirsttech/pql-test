# SPDX-License-Identifier: MIT
"""The ``contract`` click group, mounted as ``pql-odcs`` and as ``pql-test contract``.

Exit codes: 0 success; 1 contract invalid, lint problems, or ``--fail-on-skipped``
triggered; 2 usage error (bad option, MODEL_PATH, or a file pql-odcs would overwrite).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from pql_odcs import __version__

_CONTRACT = click.argument("contract_path", metavar="CONTRACT", type=click.Path(exists=True, dir_okay=False))
_MAPPING = click.option(
    "--mapping",
    type=click.Path(exists=True, dir_okay=False),
    help="Sidecar YAML mapping ODCS names to semantic model tables/columns.",
)
_CLOSED = click.option(
    "--closed-schema", is_flag=True, help="Also fail when a table has columns the contract does not list."
)
_FAIL_ON_SKIPPED = click.option(
    "--fail-on-skipped", is_flag=True, help="Exit 1 when any contract rule is skipped (strict CI)."
)


def _plan(contract_path: str, mapping: str | None, closed_schema: bool):
    from pql_odcs.api import plan_contract
    from pql_odcs.loader import ContractError
    from pql_odcs.naming import MappingError

    try:
        return plan_contract(contract_path, mapping=mapping, closed_schema=closed_schema)
    except (ContractError, MappingError) as exc:
        click.echo(f"Error: {exc}", err=True)
        raise click.exceptions.Exit(1) from None


def _report(plan) -> dict:
    from pql_odcs.coverage import build_report

    return build_report(plan.contract, plan.outcomes)


def _fail_if_skipped(report: dict, fail_on_skipped: bool) -> None:
    skipped = [r["ruleId"] for r in report["rules"] if r["status"] == "skipped"]
    if fail_on_skipped and skipped:
        click.echo(f"--fail-on-skipped: {len(skipped)} rule(s) skipped: {', '.join(skipped)}", err=True)
        raise click.exceptions.Exit(1)


@click.group(name="contract")
@click.version_option(version=__version__, prog_name="pql-odcs")
def contract() -> None:
    """Generate, check, and trace PQL.Assert tests from ODCS data contracts."""


@contract.command("generate")
@_CONTRACT
@click.argument("model_path", metavar="MODEL_PATH")
@click.option("--env", "env", required=True, help="Environment token for suite names, e.g. DEV.")
@click.option("--suite-prefix", help="Suite name prefix (default: from the contract's dataProduct, then name).")
@_MAPPING
@_CLOSED
@_FAIL_ON_SKIPPED
@click.option("--dry-run", is_flag=True, help="Print the DAX to stdout instead of writing files.")
@click.option("--force", is_flag=True, help="Overwrite suite files that pql-odcs did not generate.")
def generate_cmd(contract_path, model_path, env, suite_prefix, mapping, closed_schema, fail_on_skipped, dry_run, force):
    """Write *.Tests.dax suites for CONTRACT into MODEL_PATH/DAXQueries/ (a PBIP model)."""
    from pql_odcs.api import GenerateError, generate, render
    from pql_odcs.emit.dax import EmitError
    from pql_odcs.pbip import ModelPathError

    plan = _plan(contract_path, mapping, closed_schema)
    try:
        if dry_run:
            for f in render(plan, env=env, suite_prefix=suite_prefix):
                click.echo(f"// ===== {f.file_name} =====")
                click.echo(f.content)
        else:
            result = generate(plan, model_path, env=env, suite_prefix=suite_prefix, force=force)
            for path in result.written:
                click.echo(f"wrote   {path}")
            for path in result.removed:
                click.echo(f"removed {path} (no rules left for this suite)")
    except (EmitError, ModelPathError, GenerateError) as exc:
        raise click.UsageError(str(exc)) from None
    report = _report(plan)
    s = report["summary"]
    click.echo(
        f"Coverage: {s['mapped']} mapped, {s['approximated']} approximated, {s['skipped']} skipped "
        f"of {s['total']} rules (run `coverage` for details).",
        err=True,
    )
    _fail_if_skipped(report, fail_on_skipped)


@contract.command("coverage")
@_CONTRACT
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text", show_default=True)
@_MAPPING
@_CLOSED
@_FAIL_ON_SKIPPED
def coverage_cmd(contract_path, fmt, mapping, closed_schema, fail_on_skipped):
    """List every rule in CONTRACT as mapped, approximated, or skipped."""
    from pql_odcs.coverage import format_text

    report = _report(_plan(contract_path, mapping, closed_schema))
    click.echo(json.dumps(report, indent=2) if fmt == "json" else format_text(report), nl=fmt == "json")
    _fail_if_skipped(report, fail_on_skipped)


@contract.command("lint")
@_CONTRACT
@_MAPPING
@click.option(
    "--model",
    "model_path",
    metavar="MODEL_PATH",
    help="PBIP model to check that every resolved table and column exists.",
)
def lint_cmd(contract_path, mapping, model_path):
    """Schema-validate CONTRACT and check that its names resolve."""
    from pql_odcs.api import plan_contract
    from pql_odcs.loader import ContractError
    from pql_odcs.mapping.context import is_column
    from pql_odcs.naming import MappingError
    from pql_odcs.pbip import ModelPathError, model_names, require_semantic_model_dir

    problems: list[str] = []
    try:
        plan = plan_contract(contract_path, mapping=mapping)
    except ContractError as exc:
        plan, problems = None, exc.problems or [str(exc)]
    except MappingError as exc:
        plan, problems = None, [str(exc)]
    if plan is not None:
        problems.extend(plan.names.problems())
        if model_path:
            try:
                model = model_names(require_semantic_model_dir(model_path))
            except ModelPathError as exc:
                raise click.UsageError(str(exc)) from None
            for obj in plan.contract.schema_objects:
                table = plan.names.table(obj)
                if table not in model:
                    problems.append(f"{obj['name']}: table {table!r} not found in model")
                    continue
                for prop in obj.get("properties") or []:
                    column = plan.names.column(obj, prop)
                    if is_column(prop) and column not in model[table]:
                        problems.append(
                            f"{obj['name']}.{prop['name']}: column {column!r} not found in model table {table!r}"
                        )
    if problems:
        for p in problems:
            click.echo(f"  {p}", err=True)
        click.echo(f"{Path(contract_path).name}: {len(problems)} problem(s).", err=True)
        raise click.exceptions.Exit(1)
    n = len(plan.outcomes)
    click.echo(f"{Path(contract_path).name}: valid ODCS v{plan.contract.api_version}, {n} rules, names resolve.")


@contract.command("trace")
@_CONTRACT
@click.argument("results_path", metavar="RESULTS_JSON", type=click.Path(exists=True, dir_okay=False))
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text", show_default=True)
@click.option("--suite-prefix", help="Suite prefix used at generate time (default: derived from the contract).")
@_MAPPING
@_CLOSED
def trace_cmd(contract_path, results_path, fmt, suite_prefix, mapping, closed_schema):
    """Join pql-test --output RESULTS_JSON back to CONTRACT's rule ids."""
    from pql_odcs.results import ResultsError, format_text, read_results, trace

    plan = _plan(contract_path, mapping, closed_schema)
    try:
        results = read_results(results_path)
    except ResultsError as exc:
        raise click.BadParameter(str(exc), param_hint="RESULTS_JSON") from None
    report = trace(plan, results, suite_prefix=suite_prefix)
    if fmt == "json":
        click.echo(json.dumps(report.to_json(), indent=2))
    else:
        click.echo(format_text(report), nl=False)


def main() -> None:
    # Windows consoles default to cp1252, which cannot encode the em dash in reports.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (OSError, ValueError):  # pragma: no cover - exotic streams
                pass
    contract(prog_name="pql-odcs")
