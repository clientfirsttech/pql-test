# SPDX-License-Identifier: AGPL-3.0-only
"""
The `pql-test contract` commands that can connect to a model: `run` (generate PQL.Assert
suites from an ODCS contract, run them, and trace the results back to contract rule ids),
`doctor` (file checks plus the deployed or open model's library), and `coverage` (which
model objects the contract covers, from files or, with --live, from the model).

The file-only commands live in ``pql_test.odcs.cli``; ``register_contract_commands``
adds these three to that group.

`run` never changes the PBIP project: it renders the suites in memory and runs them
from their own ``DEFINE FUNCTION ... EVALUATE`` text with ``run_tests()``. Writing them
into ``DAXQueries/`` is a separate act (``generate``, or ``run --write``). ``run_tests_from_model`` would only run suites already
registered in the live model, which skips suites that were just generated.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

import click

from pql_test.cli_options import (
    emit_result,
    format_option,
    min_coverage_option,
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
from pql_test.runner.cli_format import (
    STATUS_COLORS,
    azure_text,
    banner,
    github_data,
    github_property,
    pad,
    table_bottom,
    table_mid,
    table_row,
    table_top,
)
from pql_test.runner.model_path import parse_model_identifier
from pql_test.runner.models import PqlTest

# trace status -> cli_format status color key
_TRACE_COLORS = {"failed": "FAIL", "error": "FAIL", "not_executed": "SKIP", "skipped": "SKIP"}


@dataclass(frozen=True)
class RunHooks:
    """pql-test CLI helpers that `contract run` reuses, injected by cli.py."""

    conn_options: Callable  # click decorator adding --tenant-id/--client-id/...
    make_conn_opts: Callable  # (tenant, workspace, dataset, client_id, secret) -> options
    name_dataset: Callable  # (options, model dir): the folder's model, unless --dataset-id was typed
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
            title = github_property(f"ODCS rule {rule.rule_id}")
            click.echo(f"::{level} title={title}::{github_data(text)}")
        else:
            click.echo(f"##vso[task.logissue type={level}]{azure_text(text, vso_data=True)}")


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


_VERSION_TEXT = re.compile(r"\d+(\.\d+){1,3}[0-9A-Za-z.+-]{0,16}")


def deployed_library_version(conn) -> str | None:
    """The connected model's ``PQL.Assert.LibraryVersion()``, or ``None`` when that call fails.

    ``LibraryVersion`` only exists from 0.8.0, so ``None`` means 0.7.x or older, no library,
    or an unreachable model.
    """
    if conn is None:
        return None
    try:
        rows = _execute_dax_query(conn, "EVALUATE { PQL.Assert.LibraryVersion() }")
        version = str(next(iter(rows[0].values())))
    except Exception:  # noqa: BLE001 - any failure means "no LibraryVersion()"
        return None
    # The model supplies this text and it is echoed into logs (CI annotations included), so
    # accept only a version-shaped string; anything else is treated as "no usable version".
    return version if _VERSION_TEXT.fullmatch(version) else None


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
            "and publish the model (see `pql-test contract mapping --pql-assert`)."
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
    # local/<name> stays as is: the resolver connects to that open Desktop model and nothing else.
    is_local = parse_model_identifier(model_path).kind == "local"
    if semantic_model_dir is not None and not is_local:
        hooks.name_dataset(opts, semantic_model_dir)
    abs_path = model_path if is_local else str(Path(model_path).resolve())
    if xmla_unavailable():
        return abs_path, None
    return abs_path, resolve_xmla_connection(abs_path, opts)


def isolate_failed_suites(files, results: list[TestResult], conn) -> list[TestResult]:
    """*results*, with each suite that failed to run as a whole re-run one call at a time.

    A suite runs as one query, so one call that cannot run (a contract DAX expression with a
    type error, a function the model lacks) fails the query, and every rule in the suite would
    show that one error. Run alone, each call reports its own result, and the error lands on
    the call that has it. Suites that ran, and suites of one call, are not run again.
    """
    by_name = {f.function_name: f for f in files}
    isolated: list[TestResult] = []
    for result in results:
        suite = by_name.get(result.test_name)
        if suite is None or result.suite_name != suite.function_name or not result.error or len(suite.calls) < 2:
            isolated.append(result)
            continue
        for test_name, call in suite.calls:
            alone = PqlTest(name=suite.function_name, file_path="", source=f"EVALUATE {call}\n")
            for row in run_tests([alone], conn):
                # A call that cannot run alone either: name its rule instead of the suite.
                isolated.append(replace(row, test_name=test_name) if row.test_name == suite.function_name else row)
    return isolated


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
        results = isolate_failed_suites(files, results, conn)
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
        click.echo(f"Use --pql-assert {report.recommended} with generate, mapping, and trace for this model.")


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


_LEVEL_COLUMNS = (("Tested", "values_tested"), ("Listed", "listed"), ("Not enforced", "listed_not_enforced"))


def _coverage_table(report, min_coverage: float | None) -> list[str]:
    """The "By category" table: per kind, how many objects sit at each level, and the covered share."""
    from pql_test.odcs.coverage import Kind
    from pql_test.runner.coverage_report import coverage_status

    headers = ["Category", *(h for h, _ in _LEVEL_COLUMNS), "Covered", "Eligible", "%"]
    rows = []
    for kind in Kind:
        counts = report.counts(kind)
        if not counts.eligible:
            rows.append((kind.value, *(["0"] * (len(headers) - 2)), "-", None))
            continue
        cells = [str(getattr(counts, attr)) for _, attr in _LEVEL_COLUMNS]
        color = STATUS_COLORS[coverage_status(counts.percent, min_coverage)]
        rows.append((kind.value, *cells, str(counts.covered), str(counts.eligible), f"{counts.percent}%", color))
    widths = [max(len(headers[i]), *(len(r[i]) for r in rows)) for i in range(len(headers))]

    def cells_of(values) -> list[str]:
        return [pad(v, w, "left" if i == 0 else "right") for i, (v, w) in enumerate(zip(values, widths))]

    lines = [table_top(widths), table_row(cells_of(headers)), table_mid(widths)]
    for *values, color in rows:
        padded = cells_of(values)
        if color:
            padded[-1] = click.style(padded[-1], fg=color)
        lines.append(table_row(padded))
    lines.append(table_bottom(widths))
    return lines


def _listing(title: str, items: list[str]) -> None:
    if items:
        click.echo(f"\n{title} ({len(items)}):")
        for item in items:
            click.echo(f"  {item}")


def print_coverage(report, verbose: bool, min_coverage: float | None = None) -> None:
    """The coverage report in code-coverage's layout, then what the contract does not cover."""
    from pql_test.odcs.coverage import CALCULATED_GAP, NOT_COUNTED, Level
    from pql_test.runner.coverage_report import coverage_status

    c = report.contract
    click.echo("\n" + banner("contract coverage session starts"))
    click.echo(f"contract: {c['id']} (ODCS {c['apiVersion']}), PQL.Assert {report.pql_assert}")
    if report.live:
        click.echo(f"model: {report.model} (the connected model; contract DAX read by its engine)")
    else:
        click.echo(f"model: {report.model} (TMDL; contract DAX read by a text scan)")
    _listing("Not checked", list(report.unavailable))
    total = report.counts()
    overall = f"{total.covered}/{total.eligible} covered ({total.percent}%), {total.values_tested} with values tested"
    record_summary(f"Overall: {overall}")
    click.echo(f"\nOverall: {click.style(overall, fg=STATUS_COLORS[coverage_status(total.percent, min_coverage)])}")
    click.echo("\nBy category:")
    for line in _coverage_table(report, min_coverage):
        click.echo(line)

    by_level = {level: [o for o in report.objects if o.level is level] for level in Level}
    _listing("Not covered", [f"{o.obj.kind.value} {o.obj.identifier}" for o in by_level[Level.NOT_COVERED]])
    _listing(
        "Listed, but every rule on it is skipped",
        [f"{o.obj.kind.value} {o.obj.identifier} (in {', '.join(o.rules)})" for o in by_level[Level.LISTED_NOT_ENFORCED]],
    )
    _listing(CALCULATED_GAP[0].upper() + CALCULATED_GAP[1:], list(report.calculated_without_value_rule))
    _listing(
        "Names in contract DAX that match nothing in the model (not counted)",
        [f"{u.rule_id}: {u.reference}" for u in report.unresolved],
    )
    _listing("In the contract but not matching the model (the checks lint makes)", list(report.mismatches))
    if verbose:
        for level in (Level.VALUES_TESTED, Level.LISTED):
            _listing(
                level.label.capitalize(),
                [f"{o.obj.kind.value} {o.obj.identifier}: {', '.join(o.rules)}" for o in by_level[level]],
            )
        _listing("Left out", [f"{e.kind.value} {e.identifier}: {e.reason}" for e in report.excluded])
    elif report.excluded:
        left_out = "automatic date tables, measure tables, calculation groups"
        click.echo(f"\n{len(report.excluded)} object(s) left out ({left_out}); -v lists them.")
    if report.suggestions:
        click.echo(f"\nTo cover them, add to the contract ({len(report.suggestions)}):")
        for s in report.suggestions:
            click.echo(f"\n  # {s.kind.value} {s.identifier}, {s.where}")
            if s.ids:
                click.echo("  # (a name has a character a table.property reference cannot hold, so it references ids)")
                click.echo("  # first give these elements an id:")
                for owner, prop_name, element_id in s.ids:
                    element = f"schema object {owner!r}" if prop_name is None else f"property {prop_name!r} of {owner!r}"
                    click.echo(f"  #   {element}: id: {element_id}")
            for line in s.yaml.rstrip("\n").splitlines():
                click.echo(f"  {line}")
    click.echo(f"\n{NOT_COUNTED}")


MAPPING_MOVED = (
    "`contract coverage` compares CONTRACT with a model and needs MODEL_PATH. For the rule-by-rule report "
    "(mapped / approximated / skipped), use `pql-test contract mapping CONTRACT`."
)


def _fail(message: str) -> None:
    click.echo(f"Error: {message}", err=True)
    sys.exit(1)


def _file_coverage(contract, model_path: str, pql_assert: str):
    """The coverage report from the PBIP folder's TMDL and a text scan of contract DAX: no connection."""
    from pql_test.odcs.api import plan_contract
    from pql_test.odcs.cli import _model_pql_assert
    from pql_test.odcs.coverage import build_coverage, model_inventory
    from pql_test.odcs.pbip import ModelPathError, require_semantic_model_dir

    try:
        semantic_model_dir = require_semantic_model_dir(model_path)
    except ModelPathError as exc:
        raise click.UsageError(str(exc)) from None
    if pql_assert == "auto":
        pql_assert = _model_pql_assert(str(semantic_model_dir))
    plan = plan_contract(contract, pql_assert=pql_assert)
    return build_coverage(plan, model_inventory(semantic_model_dir), model=str(semantic_model_dir), pql_assert=pql_assert)


def _moved_to_mapping(flag: str) -> Callable:
    """A hidden flag of the old rule report: given to `coverage`, it fails pointing to `contract mapping`."""

    def moved(_ctx: click.Context, _param: click.Parameter, value: bool) -> None:
        if value:
            raise click.UsageError(f"{flag} belongs to the rule report. {MAPPING_MOVED}")

    return click.option(flag, is_flag=True, hidden=True, expose_value=False, callback=moved)


def _model_dir_or_none(model_path: str) -> Path | None:
    """The ``*.SemanticModel`` folder for MODEL_PATH (``local/<name>`` searches this repository), or None."""
    from pql_test.odcs.pbip import ModelPathError, require_semantic_model_dir

    try:
        return require_semantic_model_dir(model_path)
    except ModelPathError:
        return None


def _live_coverage(contract, model_path: str, pql_assert: str, hooks: RunHooks, credentials: tuple):
    """The coverage report from the connected model's INFO functions and its engine's reading of contract DAX.

    Connects exactly as `contract run` does, and only runs read-only queries.
    """
    from functools import partial

    from pql_test.odcs.api import plan_contract
    from pql_test.odcs.coverage import build_coverage
    from pql_test.odcs.coverage_live import batched_dependencies, engine_dax_evidence, live_inventory
    from pql_test.odcs.pbip import ModelPathError, require_semantic_model_dir
    from pql_test.runner.xmla import summarize_xmla_exception

    unavailable = xmla_unavailable()
    if unavailable:
        _fail(f"--live needs XMLA: {unavailable}. Leave out --live to count from the PBIP folder.")
    folder, target = resolve_model_target(model_path, None)
    semantic_model_dir = None
    if not target.startswith("local/"):
        try:
            semantic_model_dir = require_semantic_model_dir(folder)
        except ModelPathError as exc:
            raise click.UsageError(str(exc)) from None
    _, conn = _connect(target, hooks, credentials, semantic_model_dir)
    if conn is None:
        _fail(
            _no_local_connection(target)
            or "No XMLA connection for --live. Open the model in Power BI Desktop, or supply --tenant-id, "
            "--workspace-id, --dataset-id (and --client-id, --client-secret)."
        )
    click.echo(f"XMLA connection: {conn.server} / catalog: {conn.catalog}")
    if pql_assert == "auto":
        pql_assert = detect_pql_assert(conn)
        click.echo(f"PQL.Assert {pql_assert} catalog selected (detected from the model; override with --pql-assert).")

    def query(dax: str) -> list[dict]:
        return _execute_dax_query(conn, dax)

    try:
        inventory = live_inventory(query)
    except Exception as exc:  # noqa: BLE001 - say why the model's objects could not be listed
        # INFO functions need write permission on the model: without it, count from the files instead.
        reason = f"the model refused its INFO queries ({summarize_xmla_exception(exc)}); they need write permission"
        folder_dir = semantic_model_dir or _model_dir_or_none(target)
        if folder_dir is None:
            _fail(f"Could not list the model's objects over XMLA: {reason}, and no PBIP folder was found to count from.")
        click.echo(f"Warning: {reason}. Counting from the PBIP folder and a text scan instead.", err=True)
        report = _file_coverage(contract, str(folder_dir), pql_assert)
        return replace(report, unavailable=(f"{reason}. Counted from the PBIP folder {folder_dir.name} and a text scan.",))
    plan = plan_contract(contract, pql_assert=pql_assert)
    dax = engine_dax_evidence(plan, inventory, partial(batched_dependencies, query, describe=summarize_xmla_exception))
    # A Desktop connection has no catalog name: name the model by its MODEL_PATH instead.
    label = f"{conn.server} / {conn.catalog}" if conn.catalog else f"{target} at {conn.server}"
    return build_coverage(plan, inventory, model=label, pql_assert=pql_assert, dax=dax)


def make_coverage_command(hooks: RunHooks) -> click.Command:
    """`contract coverage`: which model objects CONTRACT covers, from the files or, with --live, the model."""

    @click.command("coverage")
    @click.argument("contract_path", metavar="CONTRACT", type=click.Path(exists=True, dir_okay=False))
    @click.argument("model_path", metavar="MODEL_PATH", required=False)
    @click.option(
        "--live",
        is_flag=True,
        help="Read the model's objects from the connected model, and ask its engine what contract DAX references "
        "(XMLA, Windows; needs write permission on the model). Only reads: it never changes the model.",
    )
    @click.option(
        "--pql-assert",
        "pql_assert",
        type=click.Choice(["auto", "0.7", "0.8", "0.9"]),
        default="auto",
        show_default=True,
        help="PQL.Assert version whose rules count as enforced. auto reads the model folder's functions.tmdl "
        "(with --live, asks the model).",
    )
    @min_coverage_option("Exit 1 when the share of model objects with at least one enforced rule is below PERCENT.")
    @format_option(help="Output format: the coverage report (text), or the JSON report on stdout.")
    @output_option("Also write the JSON report to FILE.")
    @verbosity_options(verbose_help="Also list covered objects with their rules, and the objects left out.")
    @_moved_to_mapping("--fail-on-skipped")
    @_moved_to_mapping("--closed-schema")
    @hooks.conn_options
    def coverage(
        contract_path: str,
        model_path: str | None,
        live: bool,
        pql_assert: str,
        min_coverage: float | None,
        output_format: str,
        output: str | None,
        verbose: bool,
        tenant_id: str | None,
        workspace_id: str | None,
        dataset_id: str | None,
        client_id: str | None,
        client_secret: str | None,
    ) -> None:
        """Show which tables, columns, relationships, and measures in MODEL_PATH CONTRACT covers.

        Each model object is values tested (a rule checks its data), listed (a schema check runs),
        listed but not enforced (every rule on it is skipped), or not covered. Only direct references
        count: a rule on a measure does not cover what that measure uses. By default it reads the
        contract and the model's TMDL only, so it also runs on Linux. --live reads the deployed or
        open model instead, and asks its engine what the contract's DAX references. Neither writes
        to the model.

        \b
        Examples:
          pql-test contract coverage orders.odcs.yaml ./SalesModel
          pql-test contract coverage orders.odcs.yaml ./SalesModel --format json --output coverage.json
          pql-test contract coverage orders.odcs.yaml ./SalesModel --min-coverage 80
          pql-test contract coverage orders.odcs.yaml local/SalesModel --live
        """
        from pql_test.odcs.loader import ContractError, load_contract

        if not model_path:
            raise click.UsageError(MAPPING_MOVED)
        try:
            contract = load_contract(contract_path)
        except ContractError as exc:
            _fail(str(exc))
        if live:
            credentials = (tenant_id, workspace_id, dataset_id, client_id, client_secret)
            report = _live_coverage(contract, model_path, pql_assert, hooks, credentials)
        else:
            report = _file_coverage(contract, model_path, pql_assert)

        payload = json.dumps(report.to_json(), indent=2)
        if output_format == "json":
            emit_result(payload)
        else:
            print_coverage(report, verbose, min_coverage)
        if output:
            Path(output).write_text(payload, encoding="utf-8")
            click.echo(f"\nCoverage report written to: {output}")
        if min_coverage is None:
            return
        percent = report.counts().percent
        if percent < min_coverage:
            click.echo(f"\nError: coverage {percent}% is below the required {min_coverage}% threshold.", err=True)
            sys.exit(1)
        click.echo(f"\nRequired coverage of {min_coverage}% reached. Total coverage: {percent}%")

    return coverage


def register_contract_commands(cli: click.Group, hooks: RunHooks) -> None:
    """Add `pql-test contract` to *cli*: the file-only commands plus `run`, `doctor`, and `coverage`."""
    from pql_test.odcs.cli import contract

    contract.add_command(make_run_command(hooks))
    contract.add_command(make_doctor_command(hooks))
    contract.add_command(make_coverage_command(hooks))
    cli.add_command(contract)
