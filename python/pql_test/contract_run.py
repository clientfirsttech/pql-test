# SPDX-License-Identifier: BUSL-1.1
"""
`pql-test contract run`: generate PQL.Assert suites from an ODCS contract, run
them, and trace the results back to contract rule ids -- in one step.

The `contract` group itself comes from pql-odcs (MIT) through the
``pql_test.commands`` entry point. This module (BUSL-1.1) adds `run`, which
needs pql-test's XMLA runner. Dependencies point one way: this module imports
pql_odcs; pql_odcs never imports pql_test.

Generated suites run from their own ``DEFINE FUNCTION ... EVALUATE`` text with
``run_tests()``. ``run_tests_from_model`` would only run suites already
registered in the live model, which skips suites that were just generated.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import click

from pql_test.runner import (
    TestResult,
    TestSuite,
    resolve_xmla_connection,
    run_tests,
)
from pql_test.runner.cli_format import STATUS_COLORS, banner
from pql_test.runner.model_path import _parse_dax_test_file

# trace status -> cli_format status color key
_TRACE_COLORS = {"failed": "FAIL", "error": "FAIL", "not_executed": "SKIP", "skipped": "SKIP"}


@dataclass(frozen=True)
class RunHooks:
    """pql-test CLI helpers that `contract run` reuses, injected by cli.py."""

    conn_options: Callable  # click decorator adding --tenant-id/--client-id/...
    make_conn_opts: Callable  # (tenant, workspace, dataset, client_id, secret) -> options
    print_results: Callable  # default human-readable printer
    print_azuredevops: Callable
    print_github: Callable
    suite_to_dict: Callable  # TestSuite -> --output JSON dict


def summarise(model_path: str, tests: list, results: list[TestResult]) -> TestSuite:
    """Build a TestSuite with the same counting rules as run_tests_from_model."""
    passed = sum(1 for r in results if r.passed)
    skipped = sum(1 for r in results if r.skipped)
    failed = sum(1 for r in results if not r.passed and not r.skipped)
    return TestSuite(model_path, tests, results, passed, failed, skipped, len(results))


def exit_code(results: list[TestResult], blocking_suites: set[str]) -> int:
    """1 when a blocking (non-WARN) suite failed, or when nothing ran at all; else 0."""
    blocking_failed = any(
        not r.passed and not r.skipped and r.suite_name in blocking_suites for r in results
    )
    all_skipped = bool(results) and all(r.skipped for r in results)
    return 1 if blocking_failed or all_skipped else 0


def _rule_detail(rule) -> str:
    return rule.reason or "; ".join(
        d.get("error") or f"Expected: {d.get('expected', '?')} | Actual: {d.get('actual', '?')}"
        for d in rule.details
        if not d.get("passed")
    )


def print_trace_annotations(report, log_format: str) -> None:
    """Failed/errored contract rules as CI annotations (warning-severity rules as warnings)."""
    for rule in report.rules:
        if rule.status not in ("failed", "error"):
            continue
        level = "warning" if rule.severity == "warning" else "error"
        text = f"ODCS rule {rule.rule_id} {rule.status}: {_rule_detail(rule)}".replace("\n", " ")
        if log_format == "github":
            click.echo(f"::{level} title=ODCS rule {rule.rule_id}::{text}")
        else:
            click.echo(f"##vso[task.logissue type={level}]{text}")


def print_trace(report) -> None:
    """Contract-rule view of the run: every rule that did not pass, grouped by rule id."""
    summary = report.summary()
    click.echo("")
    click.echo(banner("contract rules"))
    for rule in report.rules:
        if rule.status == "passed":
            continue
        label = rule.status.upper().replace("_", " ")
        colored = click.style(f"{label:<13}", fg=STATUS_COLORS[_TRACE_COLORS[rule.status]])
        warn = " (warning, non-blocking)" if rule.severity == "warning" else ""
        detail = _rule_detail(rule)
        click.echo(f"  {colored}{rule.rule_id}{warn}")
        if detail:
            click.echo(f"      {detail}")
    if report.unmatched:
        click.echo(f"  {len(report.unmatched)} result(s) did not come from this contract.")
    click.echo(
        banner(
            f"{summary['passed']} passed, {summary['failed']} failed, {summary['error']} error, "
            f"{summary['not_executed']} not executed, {summary['skipped']} skipped"
        )
    )


def make_run_command(hooks: RunHooks) -> click.Command:
    """Build the `contract run` click command around pql-test's injected CLI helpers."""

    @click.command("run")
    @click.argument("contract_path", metavar="CONTRACT", type=click.Path(exists=True, dir_okay=False))
    @click.argument("model_path", metavar="MODEL_PATH")
    @click.option("--env", "env", required=True, help="Environment token for the generated suites, e.g. DEV.")
    @click.option("--suite-prefix", help="Suite name prefix (default: from the contract's dataProduct, then name).")
    @click.option("--closed-schema", is_flag=True, help="Also fail when a table has columns the contract does not list.")
    @click.option("--force", is_flag=True, help="Overwrite suite files that pql-odcs did not generate.")
    @click.option("--verbose", "-v", is_flag=True, help="Show per-assertion detail for every result.")
    @click.option("--output", default=None, metavar="FILE", help="Write full JSON results to FILE.")
    @click.option(
        "--log-format",
        default=None,
        type=click.Choice(["azuredevops", "github"], case_sensitive=False),
        help="Emit CI-native log annotations instead of human-readable output.",
    )
    @hooks.conn_options
    def run(
        contract_path: str,
        model_path: str,
        env: str,
        suite_prefix: str | None,
        closed_schema: bool,
        force: bool,
        verbose: bool,
        output: str | None,
        log_format: str | None,
        tenant_id: str | None,
        workspace_id: str | None,
        dataset_id: str | None,
        client_id: str | None,
        client_secret: str | None,
    ) -> None:
        """Generate suites from CONTRACT into a PBIP MODEL_PATH, run them, and trace results to rule ids.

        Warning-severity rules run in <ENV>WARN suites: they are reported but do not fail the run.

        \b
        Examples:
          pql-test contract run orders.odcs.yaml ./MyModel --env DEV
          pql-test contract run orders.odcs.yaml ./MyModel --env DEV --output results.json --log-format github
        """
        from pql_odcs.api import GenerateError, generate, plan_contract
        from pql_odcs.emit.dax import EmitError
        from pql_odcs.loader import ContractError
        from pql_odcs.pbip import ModelPathError
        from pql_odcs.results import trace

        try:
            plan = plan_contract(contract_path, closed_schema=closed_schema)
        except ContractError as exc:
            click.echo(f"Error: {exc}", err=True)
            sys.exit(1)
        try:
            generated = generate(plan, model_path, env=env, suite_prefix=suite_prefix, force=force)
        except (EmitError, ModelPathError, GenerateError) as exc:
            raise click.UsageError(str(exc)) from None
        click.echo(f"Generated {len(generated.written)} suite(s) in {generated.target_dir}")

        opts = hooks.make_conn_opts(tenant_id, workspace_id, dataset_id, client_id, client_secret)
        semantic_model_dir = generated.target_dir.parent
        if not opts.dataset_id and not opts.dataset_name:
            opts.dataset_name = semantic_model_dir.name[: -len(".SemanticModel")]
        abs_path = str(Path(model_path).resolve())
        conn = resolve_xmla_connection(abs_path, opts)
        pre_warnings: list[str] = []
        if conn:
            click.echo(f"\nXMLA connection: {conn.server} / catalog: {conn.catalog}")
        else:
            pre_warnings.append("No XMLA connection detected. Tests will be reported as skipped.")
            click.echo(
                "\nWarning: No XMLA connection detected. Open the model in Power BI Desktop, or supply "
                "--tenant-id, --workspace-id, --dataset-id (and --client-id, --client-secret).",
                err=True,
            )

        tests = [_parse_dax_test_file(str(p)) for p in generated.written]
        results = run_tests(
            tests,
            conn,
            skip_message="No XMLA connection available; generated suites were written but not run.",
        )
        suite = summarise(abs_path, tests, results)
        if log_format == "azuredevops":
            hooks.print_azuredevops(suite, pre_warnings=pre_warnings)
        elif log_format == "github":
            hooks.print_github(suite, pre_warnings=pre_warnings)
        else:
            hooks.print_results(suite, verbose, pre_warnings=pre_warnings, environment=env)

        suite_json = hooks.suite_to_dict(suite)
        report = trace(plan, suite_json, suite_prefix=suite_prefix)
        if output:
            # run-tests' documented shape, plus the per-rule trace under "contract".
            Path(output).write_text(json.dumps({**suite_json, "contract": report.to_json()}, indent=2), encoding="utf-8")
            click.echo(f"\nJSON results written to: {output}")
        if log_format:
            print_trace_annotations(report, log_format.lower())
        else:
            print_trace(report)

        blocking = {f.function_name for f in generated.files if f.blocking}
        sys.exit(exit_code(results, blocking))

    return run


def extend_contract_group(base: click.Group, run: click.Command) -> click.Group:
    """A copy of pql-odcs's `contract` group with `run` added (the original stays untouched)."""
    group = click.Group(
        name=base.name,
        commands=dict(base.commands),
        callback=base.callback,
        params=list(base.params),
        help=base.help,
        context_settings=base.context_settings,
        no_args_is_help=base.no_args_is_help,
    )
    group.add_command(run)
    return group


def attach_contract_run(cli: click.Group, hooks: RunHooks) -> bool:
    """Replace the plugin `contract` group with one that also has `run`, when pql-odcs provides it."""
    base = cli.commands.get("contract")
    if not isinstance(base, click.Group) or not (base.callback and base.callback.__module__.startswith("pql_odcs")):
        return False
    cli.add_command(extend_contract_group(base, make_run_command(hooks)), "contract")
    return True
