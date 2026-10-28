# SPDX-License-Identifier: AGPL-3.0-only
"""The file-only commands of ``pql-test contract``: init, generate, coverage, lint, trace.

``run`` and ``doctor`` connect to a model, so they live in ``pql_test.contract_run`` and are
added to this group by ``pql_test.cli``. Exit codes: 0 success; 1 contract invalid, lint
problems, or ``--fail-on-skipped`` triggered; 2 usage error (bad option, MODEL_PATH, or a suite
file pql-test would overwrite).
"""

from __future__ import annotations

import json
from pathlib import Path

import click

_CONTRACT = click.argument("contract_path", metavar="CONTRACT", type=click.Path(exists=True, dir_okay=False))
_CLOSED = click.option(
    "--closed-schema", is_flag=True, help="Also fail when a table has columns the contract does not list."
)
_PQL_ASSERT = click.option(
    "--pql-assert",
    "pql_assert",
    type=click.Choice(["0.7", "0.8"]),
    default="0.7",
    show_default=True,
    help="PQL.Assert version to target. 0.8 maps more rules exactly but needs a model with PQL.Assert 0.8.0+.",
)
_GENERATE_PQL_ASSERT = click.option(
    "--pql-assert",
    "pql_assert",
    type=click.Choice(["0.7", "0.8", "auto"]),
    default="0.7",
    show_default=True,
    help=(
        "PQL.Assert version to target. 0.8 maps more rules exactly but needs a model with PQL.Assert 0.8.0+. "
        "auto reads the model folder's functions.tmdl (see `pql-test contract doctor`)."
    ),
)
_FAIL_ON_SKIPPED = click.option(
    "--fail-on-skipped", is_flag=True, help="Exit 1 when any contract rule is skipped (strict CI)."
)


def _plan(contract_path: str, closed_schema: bool, pql_assert: str = "0.7"):
    from pql_test.odcs.api import plan_contract
    from pql_test.odcs.loader import ContractError

    try:
        return plan_contract(contract_path, closed_schema=closed_schema, pql_assert=pql_assert)
    except ContractError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise click.exceptions.Exit(1) from None


def _report(plan) -> dict:
    from pql_test.odcs.coverage import build_report

    return build_report(plan.contract, plan.outcomes, catalog=plan.catalog)


def _fail_if_skipped(report: dict, fail_on_skipped: bool) -> None:
    skipped = [r["ruleId"] for r in report["rules"] if r["status"] == "skipped"]
    if fail_on_skipped and skipped:
        click.echo(f"--fail-on-skipped: {len(skipped)} rule(s) skipped: {', '.join(skipped)}", err=True)
        raise click.exceptions.Exit(1)


@click.group(name="contract")
def contract() -> None:
    """Generate, check, and trace PQL.Assert tests from ODCS data contracts."""


def _model_pql_assert(model_path: str) -> str:
    """The catalog MODEL_PATH's PQL.Assert functions support, read offline from its TMDL."""
    from pql_test.odcs.doctor import recommend_catalog
    from pql_test.odcs.pbip import ModelPathError, require_semantic_model_dir
    from pql_test.odcs.udf import model_functions

    try:
        choice, _ = recommend_catalog(model_functions(require_semantic_model_dir(model_path)))
    except ModelPathError as exc:
        raise click.UsageError(str(exc)) from None
    if choice is None:
        click.echo(
            "--pql-assert auto: the model's functions.tmdl lacks functions every catalog calls (run `pql-test contract doctor`); "
            "using 0.7.",
            err=True,
        )
        return "0.7"
    click.echo(f"--pql-assert auto: {choice} (read from the model's functions.tmdl).", err=True)
    return choice


@contract.command("generate")
@_CONTRACT
@click.argument("model_path", metavar="MODEL_PATH")
@click.option("--env", "env", required=True, help="Environment token for suite names, e.g. DEV.")
@click.option("--suite-prefix", help="Suite name prefix (default: from the contract's dataProduct, then name).")
@_CLOSED
@_GENERATE_PQL_ASSERT
@_FAIL_ON_SKIPPED
@click.option("--dry-run", is_flag=True, help="Print the DAX to stdout instead of writing files.")
@click.option("--force", is_flag=True, help="Overwrite suite files that pql-test did not generate.")
def generate_cmd(
    contract_path, model_path, env, suite_prefix, closed_schema, pql_assert, fail_on_skipped, dry_run, force
):
    """Write *.Tests.dax suites for CONTRACT into MODEL_PATH/DAXQueries/ (a PBIP model)."""
    from pql_test.odcs.api import GenerateError, generate, render
    from pql_test.odcs.emit.dax import EmitError
    from pql_test.odcs.pbip import ModelPathError

    if pql_assert == "auto":
        pql_assert = _model_pql_assert(model_path)
    plan = _plan(contract_path, closed_schema, pql_assert)
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


@contract.command("init")
@click.argument("model_path", metavar="MODEL_PATH")
@click.option("--table", "tables", multiple=True, metavar="NAME", help="Describe only this table (repeatable).")
@click.option("--id", "contract_id", help="Contract id (default: the model name, lowercased with dashes).")
@click.option("--output", "-o", type=click.Path(dir_okay=False), help="Write the contract to FILE instead of stdout.")
@click.option("--force", is_flag=True, help="With --output: overwrite an existing file.")
def init_cmd(model_path, tables, contract_id, output, force):
    """Start an ODCS contract from MODEL_PATH: its tables, columns, and types, read from the TMDL.

    The starter passes against the model as is; add the quality rules the data must meet.
    It only reads the model, and prints to stdout unless --output is given.

    \b
    Examples:
      pql-test contract init ./MyModel > mymodel.odcs.yaml
      pql-test contract init local/MyModel --table Sales --table Customer -o sales.odcs.yaml
    """
    from pql_test.odcs.pbip import ModelPathError, require_semantic_model_dir
    from pql_test.odcs.scaffold import InitError, render_starter, starter_contract

    if force and not output:
        raise click.UsageError("--force goes with --output.")
    try:
        semantic_model_dir = require_semantic_model_dir(model_path)
        text = render_starter(starter_contract(semantic_model_dir, tables, contract_id), semantic_model_dir.name)
    except (ModelPathError, InitError) as exc:
        raise click.UsageError(str(exc)) from None
    if not output:
        click.echo(text, nl=False)
        return
    path = Path(output)
    if path.exists() and not force:
        raise click.UsageError(f"{path} exists; pass --force to overwrite it.")
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    click.echo(f"wrote   {path}", err=True)


@contract.command("coverage")
@_CONTRACT
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text", show_default=True)
@_CLOSED
@_PQL_ASSERT
@_FAIL_ON_SKIPPED
def coverage_cmd(contract_path, fmt, closed_schema, pql_assert, fail_on_skipped):
    """List every rule in CONTRACT as mapped, approximated, or skipped."""
    from pql_test.odcs.coverage import format_text

    report = _report(_plan(contract_path, closed_schema, pql_assert))
    click.echo(json.dumps(report, indent=2) if fmt == "json" else format_text(report), nl=fmt == "json")
    _fail_if_skipped(report, fail_on_skipped)


@contract.command("lint")
@_CONTRACT
@click.argument("model_path", metavar="[MODEL_PATH]", required=False)
def lint_cmd(contract_path, model_path):
    """Schema-validate CONTRACT and check that its names resolve (in MODEL_PATH, when given)."""
    from pql_test.odcs.api import plan_contract
    from pql_test.odcs.datatypes import tmdl_model_type
    from pql_test.odcs.loader import ContractError
    from pql_test.odcs.mapping.context import is_column
    from pql_test.odcs.naming import DATA_TYPE_KEY
    from pql_test.odcs.pbip import (
        ModelPathError,
        model_columns,
        require_semantic_model_dir,
    )

    problems: list[str] = []
    try:
        plan = plan_contract(contract_path)
    except ContractError as exc:
        plan, problems = None, exc.problems or [str(exc)]
    if plan is not None:
        problems.extend(plan.names.problems())
        problems.extend(
            f"{o.rule_id}: {o.reason}"
            for o in plan.outcomes
            if o.rule_id.endswith(".type") and (o.reason or "").startswith(DATA_TYPE_KEY)
        )
        if model_path:
            try:
                model = model_columns(require_semantic_model_dir(model_path))
            except ModelPathError as exc:
                raise click.UsageError(str(exc)) from None
            # DAX object names are case-insensitive.
            model_ci = {t.lower(): {c.lower(): dt for c, dt in cols.items()} for t, cols in model.items()}
            for obj in plan.contract.schema_objects:
                table = plan.names.table(obj)
                if table.lower() not in model_ci:
                    problems.append(f"{obj['name']}: table {table!r} not found in model")
                    continue
                for prop in obj.get("properties") or []:
                    column = plan.names.column(obj, prop)
                    if is_column(prop) and column.lower() not in model_ci[table.lower()]:
                        problems.append(
                            f"{obj['name']}.{prop['name']}: column {column!r} not found in model table {table!r}"
                        )
            problems.extend(_type_problems(plan, model_ci, tmdl_model_type))
    if problems:
        for p in problems:
            click.echo(f"  {p}", err=True)
        click.echo(f"{Path(contract_path).name}: {len(problems)} problem(s).", err=True)
        raise click.exceptions.Exit(1)
    n = len(plan.outcomes)
    click.echo(f"{Path(contract_path).name}: valid ODCS v{plan.contract.api_version}, {n} rules, names resolve.")


def _type_problems(plan, model_ci: dict, tmdl_model_type) -> list[str]:
    """Type checks whose column has a different data type in the model's TMDL."""
    problems = []
    for outcome in plan.outcomes:
        for a in outcome.assertions:
            if a.op != "tbl.column_type":
                continue
            tmdl = model_ci.get(a.target.table.lower(), {}).get((a.target.column or "").lower())
            actual = tmdl_model_type(tmdl) if tmdl else None
            if actual and actual not in a.args["types"]:
                expected = " or ".join(a.args["types"])
                problems.append(
                    f"{outcome.rule_id}: column {a.target.column!r} is {actual} in the model, the contract expects "
                    f"{expected} (set pbiDataType to pin another model type)"
                )
    return problems


@contract.command("trace")
@_CONTRACT
@click.argument("results_path", metavar="RESULTS_JSON", type=click.Path(exists=True, dir_okay=False))
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text", show_default=True)
@click.option("--suite-prefix", help="Suite prefix used at generate time (default: derived from the contract).")
@_CLOSED
@_PQL_ASSERT
def trace_cmd(contract_path, results_path, fmt, suite_prefix, closed_schema, pql_assert):
    """Join a pql-test --output RESULTS_JSON back to CONTRACT's rule ids."""
    from pql_test.odcs.results import ResultsError, format_text, read_results, trace

    plan = _plan(contract_path, closed_schema, pql_assert)
    try:
        results = read_results(results_path)
    except ResultsError as exc:
        raise click.BadParameter(str(exc), param_hint="RESULTS_JSON") from None
    report = trace(plan, results, suite_prefix=suite_prefix)
    if fmt == "json":
        click.echo(json.dumps(report.to_json(), indent=2))
    else:
        click.echo(format_text(report), nl=False)
