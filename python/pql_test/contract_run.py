# SPDX-License-Identifier: AGPL-3.0-only
"""
The connected `pql-test contract` commands: `run` (generate PQL.Assert suites
from an ODCS contract, run them, and trace the results back to contract rule
ids) and `doctor` (file checks plus the deployed or open model's library).

The file-only commands live in ``pql_test.odcs.cli``; ``register_contract_commands``
adds these two to that group.

`run` never changes the PBIP project: it renders the suites in memory and runs them
from their own ``DEFINE FUNCTION ... EVALUATE`` text with ``run_tests()``. Writing them
into ``DAXQueries/`` is a separate act (``generate``, or ``run --write``). ``run_tests_from_model`` would only run suites already
registered in the live model, which skips suites that were just generated.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import click

from pql_test.cli_options import (
    emit_result,
    format_option,
    output_option,
    record_summary,
    verbosity_options,
)
from pql_test.runner import (
    TestResult,
    TestSuite,
    _execute_dax_query,
    resolve_xmla_connection,
    run_tests,
)
from pql_test.runner.cli_format import STATUS_COLORS, banner
from pql_test.runner.model_path import parse_model_identifier
from pql_test.runner.models import PqlTest

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
    line = (
        f"{summary['passed']} passed, {summary['failed']} failed, {summary['error']} error, "
        f"{summary['not_executed']} not executed, {summary['skipped']} skipped"
    )
    record_summary(f"Contract {report.contract_id}: {line}")
    click.echo(banner(line))


def deployed_library_version(conn) -> str | None:
    """The connected model's ``PQL.Assert.LibraryVersion()``, or ``None`` when that call fails.

    ``LibraryVersion`` only exists from 0.8.0, so ``None`` means 0.7.x or older, no library,
    or an unreachable model.
    """
    if conn is None:
        return None
    try:
        rows = _execute_dax_query(conn, "EVALUATE { PQL.Assert.LibraryVersion() }")
        return str(next(iter(rows[0].values())))
    except Exception:  # noqa: BLE001 - any failure means "no LibraryVersion()"
        return None


def _catalog_for_version(version: str | None) -> str:
    """The newest catalog whose minimum version a LibraryVersion() report satisfies, else ``"0.7"``."""
    try:
        major, minor = (int(part) for part in (version or "").split(".")[:2])
    except ValueError:
        return "0.7"
    if (major, minor) >= (0, 9):
        return "0.9"
    return "0.8" if (major, minor) >= (0, 8) else "0.7"


def _version_key(catalog: str) -> tuple[int, ...]:
    return tuple(int(part) for part in catalog.split("."))


def pql_assert_version_warning(deployed_version: str | None, selected: str) -> str | None:
    """Why the deployed PQL.Assert is too old for this run, or None when it is current enough.

    Two cases: the chosen ``--pql-assert`` is newer than the model supports (the suites call
    functions the model lacks, so they error), or the model supports an older catalog than the
    newest one pql-test knows (rules that need the newer functions are approximated or skipped).
    """
    from pql_test.odcs.catalog import LATEST_PQL_ASSERT

    deployed = _catalog_for_version(deployed_version)
    reported = deployed_version or "0.7.x or older (no PQL.Assert.LibraryVersion())"
    if _version_key(selected) > _version_key(deployed):
        return (
            f"--pql-assert {selected} needs PQL.Assert {selected} or later, but the deployed model has "
            f"{reported}. The generated suites call functions the model lacks and will error: update "
            f"PQL.Assert from DAX Lib and publish the model, or use --pql-assert {deployed}."
        )
    if _version_key(deployed) < _version_key(LATEST_PQL_ASSERT):
        return (
            f"the deployed model has PQL.Assert {reported}; pql-test supports up to {LATEST_PQL_ASSERT}. "
            f"Rules that need newer functions are approximated or skipped: update PQL.Assert from DAX Lib "
            "and publish the model (see `pql-test contract coverage --pql-assert`)."
        )
    return None


def detect_pql_assert(conn) -> str:
    """The newest catalog the model's reported PQL.Assert version supports, else ``"0.7"``."""
    return _catalog_for_version(deployed_library_version(conn))


def xmla_unavailable() -> str | None:
    """Why this machine cannot query a model over XMLA (no pyadomd / ADOMD.NET), or None when it can."""
    # Checked first: off Windows there is nothing to load, so never start the ADOMD.NET loader.
    if sys.platform != "win32":
        return "XMLA needs ADOMD.NET, which runs on Windows only"
    from pql_test.runner import HAS_PYADOMD

    if HAS_PYADOMD:
        return None
    return "ADOMD.NET is not available (pyadomd or its assemblies are missing); run `pql-test check-prereqs`"


def _connect(model_path: str, hooks: RunHooks, credentials: tuple, semantic_model_dir: Path | None):
    """``(absolute model path, connection or None)``, resolved like `run-tests` (dataset name from the folder).

    None without looking for a model when XMLA is unavailable here (see ``xmla_unavailable``).
    """
    opts = hooks.make_conn_opts(*credentials)
    if semantic_model_dir is not None and not opts.dataset_id and not opts.dataset_name:
        opts.dataset_name = semantic_model_dir.name[: -len(".SemanticModel")]
    # local/<name> stays as is: the resolver connects to that open Desktop model and nothing else.
    is_local = parse_model_identifier(model_path).kind == "local"
    abs_path = model_path if is_local else str(Path(model_path).resolve())
    if xmla_unavailable():
        return abs_path, None
    return abs_path, resolve_xmla_connection(abs_path, opts)


def resolve_model_target(model_path: str, model_dir: str | None) -> tuple[str, str]:
    """``(PBIP folder, connection target)`` for MODEL_PATH.

    A PBIP path is both. ``local/<name>`` connects only to that model open in Power BI Desktop and
    takes its folder from --model-dir, else from the one ``<name>.SemanticModel`` in the repository.
    """
    from pql_test.odcs.pbip import local_model_name

    name = local_model_name(model_path)
    if name is None:
        if model_dir:
            raise click.UsageError("--model-dir goes with a local/<model_name> MODEL_PATH; pass the folder as MODEL_PATH instead.")
        return model_path, model_path
    # One spelling (local/<name>, never local\<name>), so the resolver connects to that open model only.
    target = f"local/{name}"
    return model_dir or target, target


def suite_test(suite_file) -> PqlTest:
    """A runnable test for one rendered suite: its own ``DEFINE FUNCTION ... EVALUATE`` text, no file needed."""
    return PqlTest(
        name=Path(suite_file.file_name).stem,
        file_path="",
        source=suite_file.content,
        description=f"DAX function: {suite_file.function_name}",
    )


def _model_dir_option(command: Callable) -> Callable:
    return click.option(
        "--model-dir",
        metavar="DIR",
        help="PBIP folder of a local/<model_name> MODEL_PATH (default: the <model_name>.SemanticModel in this repository).",
    )(command)


def _no_local_connection(target: str) -> str | None:
    """pql-test's 'which Desktop instances are open' diagnostic when local/<name> did not connect."""
    ident = parse_model_identifier(target)
    if ident.kind != "local":
        return None
    # cli imports this module, so import it late.
    from pql_test.cli import _format_local_miss_diagnostic

    return _format_local_miss_diagnostic(ident.model_name)


def make_run_command(hooks: RunHooks) -> click.Command:
    """Build the `contract run` click command around pql-test's injected CLI helpers."""

    @click.command("run")
    @click.argument("contract_path", metavar="CONTRACT", type=click.Path(exists=True, dir_okay=False))
    @click.argument("model_path", metavar="MODEL_PATH")
    @click.option("--env", "env", required=True, help="Environment token for the generated suites, e.g. DEV.")
    @click.option("--suite-prefix", help="Suite name prefix (default: from the contract's dataProduct, then name).")
    @click.option("--closed-schema", is_flag=True, help="Also fail when a table has columns the contract does not list.")
    @click.option(
        "--pql-assert",
        "pql_assert",
        type=click.Choice(["auto", "0.7", "0.8", "0.9"]),
        default="auto",
        show_default=True,
        help="PQL.Assert version to generate for. auto asks the model (PQL.Assert.LibraryVersion).",
    )
    @click.option(
        "--write",
        is_flag=True,
        help="Also save the suites into the model's DAXQueries/ folder (like `generate`). Off by default: run "
        "leaves the PBIP project untouched.",
    )
    @click.option("--force", is_flag=True, help="With --write: overwrite suite files that pql-test did not generate.")
    @format_option(help="Output format: the test and rule report (text), or the JSON results on stdout.")
    @verbosity_options(
        result_on_stdout=lambda kw: bool(kw.get("log_format")),
        verbose_help="Show per-assertion detail for every result.",
    )
    @output_option("Write the full JSON results (with the per-rule trace) to FILE, as well as the report.")
    @click.option(
        "--log-format",
        default=None,
        type=click.Choice(["azuredevops", "github"], case_sensitive=False),
        help="Emit CI-native log annotations instead of human-readable output.",
    )
    @_model_dir_option
    @hooks.conn_options
    def run(
        contract_path: str,
        model_path: str,
        model_dir: str | None,
        env: str,
        suite_prefix: str | None,
        closed_schema: bool,
        pql_assert: str,
        write: bool,
        force: bool,
        output_format: str,
        verbose: bool,
        output: str | None,
        log_format: str | None,
        tenant_id: str | None,
        workspace_id: str | None,
        dataset_id: str | None,
        client_id: str | None,
        client_secret: str | None,
    ) -> None:
        """Generate suites from CONTRACT, run them against the model, and trace results to rule ids.

        The suites are built in memory: run never changes the PBIP project or the model. Pass
        --write to also save them into DAXQueries/ (or use `pql-test contract generate`).
        MODEL_PATH is a PBIP path, or local/<model_name> to run against that model open in
        Power BI Desktop. Warning-severity rules run in <ENV>WARN suites: they are reported but
        do not fail the run.

        \b
        Examples:
          pql-test contract run orders.odcs.yaml ./MyModel --env DEV
          pql-test contract run orders.odcs.yaml local/MyModel --env DEV
          pql-test contract run orders.odcs.yaml ./MyModel --env DEV --output results.json --log-format github
          pql-test contract run orders.odcs.yaml ./MyModel --env DEV --write
        """
        from pql_test.odcs.api import GenerateError, generate, plan_contract, render
        from pql_test.odcs.emit.dax import EmitError
        from pql_test.odcs.loader import ContractError, load_contract
        from pql_test.odcs.pbip import ModelPathError, require_semantic_model_dir
        from pql_test.odcs.results import trace

        try:
            contract = load_contract(contract_path)
        except ContractError as exc:
            click.echo(f"Error: {exc}", err=True)
            sys.exit(1)
        if output_format == "json" and log_format:
            raise click.UsageError("Use only one of --format json and --log-format.")
        if not write and (force or model_dir):
            raise click.UsageError(f"{'--force' if force else '--model-dir'} goes with --write: run writes no files otherwise.")
        folder, target = resolve_model_target(model_path, model_dir)
        # A PBIP folder is checked (and names the dataset); local/<name> needs one only to --write into.
        semantic_model_dir = None
        if write or not target.startswith("local/"):
            try:
                semantic_model_dir = require_semantic_model_dir(folder)
            except ModelPathError as exc:
                raise click.UsageError(str(exc)) from None

        # The connection comes first: `--pql-assert auto` asks the model which PQL.Assert it has.
        credentials = (tenant_id, workspace_id, dataset_id, client_id, client_secret)
        abs_path, conn = _connect(target, hooks, credentials, semantic_model_dir)
        pre_warnings: list[str] = []
        if conn:
            click.echo(f"XMLA connection: {conn.server} / catalog: {conn.catalog}")
        else:
            pre_warnings.append("No XMLA connection detected. Tests will be reported as skipped.")
            unavailable = xmla_unavailable()
            click.echo(
                f"Warning: {unavailable}. The suites are not run."
                if unavailable
                else _no_local_connection(target)
                or "Warning: No XMLA connection detected. Open the model in Power BI Desktop, or supply "
                "--tenant-id, --workspace-id, --dataset-id (and --client-id, --client-secret).",
                err=True,
            )
        deployed_version = deployed_library_version(conn)
        if pql_assert == "auto":
            pql_assert = _catalog_for_version(deployed_version)
            source = "detected from the model" if conn else "no XMLA connection to ask the model"
            click.echo(f"PQL.Assert {pql_assert} catalog selected ({source}; override with --pql-assert).")
        # Only a connected model can be too old; with no connection the suites are not run anyway.
        version_warning = pql_assert_version_warning(deployed_version, pql_assert) if conn else None
        if version_warning:
            pre_warnings.append(f"PQL.Assert: {version_warning}")
            click.echo(f"Warning: PQL.Assert: {version_warning}", err=True)

        plan = plan_contract(contract, closed_schema=closed_schema, pql_assert=pql_assert)
        try:
            if write:
                generated = generate(plan, folder, env=env, suite_prefix=suite_prefix, force=force)
                files = generated.files
                click.echo(f"Wrote {len(generated.written)} suite(s) to {generated.target_dir}")
            else:
                files = render(plan, env=env, suite_prefix=suite_prefix)
                click.echo(f"Generated {len(files)} suite(s) in memory; no files were written (--write saves them).")
        except (EmitError, ModelPathError, GenerateError) as exc:
            raise click.UsageError(str(exc)) from None

        tests = [suite_test(f) for f in files]
        results = run_tests(tests, conn, skip_message="No XMLA connection available; the suites were not run.")
        suite = summarise(abs_path, tests, results)
        suite_json = hooks.suite_to_dict(suite)
        report = trace(plan, suite_json, suite_prefix=suite_prefix)
        # run-tests' documented shape, plus the per-rule trace under "contract".
        payload = json.dumps({**suite_json, "contract": report.to_json()}, indent=2)
        if output_format == "json":
            emit_result(payload)
        elif log_format == "azuredevops":
            hooks.print_azuredevops(suite, pre_warnings=pre_warnings)
        elif log_format == "github":
            hooks.print_github(suite, pre_warnings=pre_warnings)
        else:
            hooks.print_results(suite, verbose, pre_warnings=pre_warnings, environment=env)

        if output:
            Path(output).write_text(payload, encoding="utf-8")
            click.echo(f"\nJSON results written to: {output}")
        if log_format:
            print_trace_annotations(report, log_format.lower())
        elif output_format != "json":
            print_trace(report)

        blocking = {f.function_name for f in files if f.blocking}
        sys.exit(exit_code(results, blocking))

    return run


# doctor status -> (cli_format status color key, label pql-test prints)
_DOCTOR_STATUS = {"ok": ("PASS", "PASS"), "warn": ("SKIP", "WARN"), "fail": ("FAIL", "FAIL")}


def live_doctor_checks(conn, recommended: str | None, local_miss: str | None = None) -> list:
    """Checks against the deployed model: the connection, its PQL.Assert, and drift from the model folder.

    *local_miss* is the diagnostic for a local/<name> MODEL_PATH: asking for one open model and
    not finding it fails, where finding no connection at all only warns.
    """
    from pql_test.odcs.doctor import FAIL, OK, WARN, Check

    if conn is None and local_miss:
        return [Check("XMLA connection", FAIL, local_miss)]
    if conn is None:
        return [
            Check(
                "XMLA connection",
                WARN,
                "none, so the deployed model was not checked. Open the model in Power BI Desktop, or supply "
                "--tenant-id, --workspace-id, --dataset-id (and --client-id, --client-secret).",
            )
        ]
    try:
        _execute_dax_query(conn, "EVALUATE { 1 }")
    except Exception as exc:  # noqa: BLE001 - report any failure as the check's detail
        return [Check("XMLA connection", FAIL, f"{conn.server} / catalog: {conn.catalog}, but a test query failed: {exc}")]
    checks = [Check("XMLA connection", OK, f"{conn.server} / catalog: {conn.catalog}")]
    version = deployed_library_version(conn)
    if version is None:
        # Before 0.8.0 there is no LibraryVersion(): check that some PQL.Assert is deployed at all.
        try:
            _execute_dax_query(conn, 'EVALUATE PQL.Assert.ShouldBeTrue("pql-test contract doctor", TRUE())')
        except Exception:  # noqa: BLE001 - the function is missing (or unusable) in the deployed model
            checks.append(
                Check(
                    "Deployed PQL.Assert",
                    FAIL,
                    "not found in the deployed model: install PQL.Assert from DAX Lib and publish the model",
                )
            )
            return checks
    checks.append(Check("Deployed PQL.Assert", OK, version or "0.7.x or older (no PQL.Assert.LibraryVersion())"))
    deployed = _catalog_for_version(version)
    if recommended is None:
        return checks
    if deployed == recommended:
        checks.append(Check("Deployed vs. model folder", OK, f"both support --pql-assert {deployed}"))
    else:
        checks.append(
            Check(
                "Deployed vs. model folder",
                WARN,
                f"the model folder supports --pql-assert {recommended} but the deployed model supports {deployed}. "
                f"Publish the model, or generate with --pql-assert {deployed}; `contract run` follows the "
                "deployed model.",
            )
        )
    return checks


def print_doctor(report, conn=None, model_path: str | None = None) -> None:
    """The doctor report in pql-test's CLI style (connection line, session banner, model line, rows)."""
    if conn is not None:
        click.echo(f"XMLA connection: {conn.server} / catalog: {conn.catalog}")
    click.echo(banner("contract doctor session starts"))
    if model_path:
        click.echo(f"model: {model_path}")
        click.echo("")
    for check in report.checks:
        color, label = _DOCTOR_STATUS[check.status]
        click.echo(f"  {click.style(label.ljust(5), fg=STATUS_COLORS[color])}{check.name}: {check.detail}")
    failed = sum(c.status == "fail" for c in report.checks)
    summary = f"{failed} check(s) failed" if failed else "all checks passed"
    record_summary(f"contract doctor: {summary}")
    click.echo(banner(summary))
    if report.recommended:
        click.echo(f"Use --pql-assert {report.recommended} with generate, coverage, and trace for this model.")


def make_doctor_command(hooks: RunHooks) -> click.Command:
    """`contract doctor`: the file checks plus live checks against the deployed or open model."""

    @click.command("doctor")
    @click.argument("model_path", metavar="[MODEL_PATH]", required=False)
    @format_option()
    @_model_dir_option
    @verbosity_options()
    @hooks.conn_options
    def doctor(
        model_path: str | None,
        output_format: str,
        model_dir: str | None,
        tenant_id: str | None,
        workspace_id: str | None,
        dataset_id: str | None,
        client_id: str | None,
        client_secret: str | None,
    ) -> None:
        """Check the environment and, given a PBIP MODEL_PATH, its PQL.Assert library and deployed model.

        MODEL_PATH may also be local/<model_name>: the model open in Power BI Desktop, with its
        folder from --model-dir or the <model_name>.SemanticModel in this repository.
        Recommends the --pql-assert value the model folder supports, and warns when the
        deployed model supports a different one. Exits 1 when a check fails.
        """
        from pql_test.odcs.doctor import run_doctor
        from pql_test.odcs.pbip import require_semantic_model_dir

        folder, target = resolve_model_target(model_path, model_dir) if model_path else (None, None)
        from pql_test.odcs.doctor import FAIL, WARN, Check
        from pql_test.odcs.pbip import local_model_name

        report, conn = run_doctor(folder), None
        unavailable = xmla_unavailable() if folder and report.ok else None
        if unavailable:
            # local/<name> asks for the open model, so not reaching it fails; otherwise the live checks are optional.
            status = FAIL if local_model_name(target) else WARN
            report.checks.append(Check("XMLA connection", status, f"{unavailable}; the live checks were skipped"))
        elif folder and report.ok:
            credentials = (tenant_id, workspace_id, dataset_id, client_id, client_secret)
            _, conn = _connect(target, hooks, credentials, require_semantic_model_dir(folder))
            report.checks.extend(live_doctor_checks(conn, report.recommended, local_miss=_no_local_connection(target)))
        if output_format == "json":
            emit_result(json.dumps(report.to_json(), indent=2))
        else:
            print_doctor(report, conn, model_path)
        if not report.ok:
            sys.exit(1)

    return doctor


def register_contract_commands(cli: click.Group, hooks: RunHooks) -> None:
    """Add `pql-test contract` to *cli*: the file-only commands plus `run` and `doctor`."""
    from pql_test.odcs.cli import contract

    contract.add_command(make_run_command(hooks))
    contract.add_command(make_doctor_command(hooks))
    cli.add_command(contract)
