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

from pql_test.cli_options import (
    emit_result,
    format_option,
    output_option,
    record_summary,
    verbosity_options,
)

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
@verbosity_options(result_on_stdout=lambda kw: kw.get("dry_run"))
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
            record_summary(f"Wrote {len(result.written)} suite(s) to {result.target_dir}")
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
@output_option("Write the contract to FILE instead of stdout.", type=click.Path(dir_okay=False))
@click.option("--force", is_flag=True, help="With --output: overwrite an existing file.")
@verbosity_options(result_on_stdout=lambda kw: True)  # the contract (or the note on stderr) is the result
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
    if semantic_model_dir.resolve() in path.resolve().parents:
        # Only generate (and run --write) change the project; a contract file never goes into the model.
        raise click.UsageError(f"{path} is inside {semantic_model_dir.name}; write the contract outside the model folder.")
    try:
        with path.open("w" if force else "x", encoding="utf-8", newline="\n") as f:
            f.write(text)
    except FileExistsError:
        raise click.UsageError(f"{path} exists; pass --force to overwrite it.") from None
    except OSError as exc:
        raise click.UsageError(f"Cannot write {path}: {exc.strerror or exc}.") from None
    click.echo(f"wrote   {path}", err=True)


@contract.command("coverage")
@_CONTRACT
@format_option()
@_CLOSED
@_PQL_ASSERT
@_FAIL_ON_SKIPPED
@verbosity_options()
def coverage_cmd(contract_path, output_format, closed_schema, pql_assert, fail_on_skipped):
    """List every rule in CONTRACT as mapped, approximated, or skipped."""
    from pql_test.odcs.coverage import format_text

    report = _report(_plan(contract_path, closed_schema, pql_assert))
    if output_format == "json":
        emit_result(json.dumps(report, indent=2))
    else:
        text = format_text(report)
        record_summary(text.splitlines()[0])
        click.echo(text, nl=False)
    _fail_if_skipped(report, fail_on_skipped)


@contract.command("lint")
@_CONTRACT
@click.argument("model_path", metavar="[MODEL_PATH]", required=False)
@format_option()
@verbosity_options()
def lint_cmd(contract_path, model_path, output_format):
    """Schema-validate CONTRACT and check that its names resolve (in MODEL_PATH, when given)."""
    from pql_test.odcs.api import plan_contract
    from pql_test.odcs.catalog import LATEST_PQL_ASSERT
    from pql_test.odcs.datatypes import tmdl_model_type
    from pql_test.odcs.ir import CONTRACT_DAX, Status
    from pql_test.odcs.loader import ContractError
    from pql_test.odcs.mapping.context import is_column
    from pql_test.odcs.naming import DATA_TYPE_KEY
    from pql_test.odcs.pbip import (
        ModelPathError,
        model_columns,
        model_relationships,
        require_semantic_model_dir,
    )

    problems: list[str] = []
    try:
        # The newest catalog, so a rule that only an older PQL.Assert cannot run is not a problem.
        plan = plan_contract(contract_path, pql_assert=LATEST_PQL_ASSERT)
    except ContractError as exc:
        plan, problems = None, exc.problems or [str(exc)]
    if plan is not None:
        problems.extend(plan.names.problems())
        problems.extend(
            f"{o.rule_id}: {o.reason}" for o in plan.outcomes if o.source == CONTRACT_DAX and o.status is Status.SKIPPED
        )
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
            problems.extend(_relationship_problems(plan, model_relationships(require_semantic_model_dir(model_path))))
    name = Path(contract_path).name
    if output_format == "json":
        emit_result(
            json.dumps(
                {
                    "ok": not problems,
                    "contract": name,
                    "apiVersion": plan.contract.api_version if plan else None,
                    "rules": len(plan.outcomes) if plan else 0,
                    "problems": problems,
                },
                indent=2,
            )
        )
        if problems:
            raise click.exceptions.Exit(1)
        return
    if problems:
        for p in problems:
            click.echo(f"  {p}", err=True)
        click.echo(f"{name}: {len(problems)} problem(s).", err=True)
        raise click.exceptions.Exit(1)
    summary = f"{name}: valid ODCS v{plan.contract.api_version}, {len(plan.outcomes)} rules, names resolve."
    record_summary(summary)
    click.echo(summary)


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


def _relationship_problems(plan, model: set[tuple[str, str, str, str]]) -> list[str]:
    """Contract relationships (any catalog) that the model's TMDL does not define, from foreign key to key."""
    from pql_test.odcs.mapping.relationships import relationship_entries, resolve

    defined = {tuple(n.lower() for n in r) for r in model}
    problems = []
    for obj, prop, scope, index, rel in relationship_entries(plan.contract):
        found = resolve(plan.contract, plan.names, obj, prop, rel)
        if isinstance(found, str):
            continue  # reported as skipped by `coverage`
        key = tuple(n.lower() for n in found)
        if key in defined:
            continue
        where = "is defined from the key side in the model" if key[2:] + key[:2] in defined else "is not in the model"
        problems.append(
            f"{scope}.relationships[{index}]: relationship {found.from_table}[{found.from_column}] -> "
            f"{found.to_table}[{found.to_column}] {where}"
        )
    return problems


@contract.command("trace")
@_CONTRACT
@click.argument("results_path", metavar="RESULTS_JSON", type=click.Path(exists=True, dir_okay=False))
@format_option()
@click.option("--suite-prefix", help="Suite prefix used at generate time (default: derived from the contract).")
@_CLOSED
@_PQL_ASSERT
@verbosity_options()
def trace_cmd(contract_path, results_path, output_format, suite_prefix, closed_schema, pql_assert):
    """Join a pql-test --output RESULTS_JSON back to CONTRACT's rule ids."""
    from pql_test.odcs.results import ResultsError, format_text, read_results, trace

    plan = _plan(contract_path, closed_schema, pql_assert)
    try:
        results = read_results(results_path)
    except ResultsError as exc:
        raise click.BadParameter(str(exc), param_hint="RESULTS_JSON") from None
    report = trace(plan, results, suite_prefix=suite_prefix)
    if output_format == "json":
        emit_result(json.dumps(report.to_json(), indent=2))
    else:
        text = format_text(report)
        record_summary(text.splitlines()[0])
        click.echo(text, nl=False)
