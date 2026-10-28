#!/usr/bin/env python3
# SPDX-License-Identifier: BUSL-1.1
"""
pql-test CLI

Command-line interface for discovering and executing DAX tests stored inside
a PBIP (Power BI Project) semantic model's DAXQueries/ folder.

Tests are *.Tests.dax files executed via ADOMD.NET (pyadomd), mirroring the
Invoke-DQVTesting pattern.  Service principal authentication is supported via
MSAL, enabling row-level security calls from build agents.

Model path formats:
  - <workspace>.Workspace/<model>.SemanticModel
                                Canonical Fabric service path — connect to
                                a remote workspace by display names.
  - <filesystem_path>           Traditional PBIP root directory.
  - local/<model_name>          Connect to a locally-open Power BI
                                Desktop instance by model name.

Connection resolution:
  - When --tenant-id, --workspace-id, and --dataset-id are all provided (or
    set via PQL_* environment variables) the CLI connects to the remote
    Power BI Premium / Fabric XMLA endpoint using a service-principal
    bearer token acquired from Azure AD via MSAL.
  - When using the Fabric-style service path, the CLI connects directly
    using workspace and model display names without GUIDs.
  - Otherwise the CLI auto-detects a locally-open Power BI Desktop instance
    using the local Analysis Services port file.

Usage:
  pql-test check-prereqs
  pql-test retrieve-tests <modelPath> [--test <name>] [--env <environment>]
                           [--verbose]
  pql-test retrieve-test  <modelPath> <name> [--verbose]
  pql-test run-tests      <modelPath> [--test <name>] [--verbose]
                           [--env <environment>]
                           [--output <file>]
                           [--log-format {azuredevops,github}]
                           [--tenant-id <id>] [--workspace-id <id>]
                           [--dataset-id <id>] [--client-id <id>]
                           [--client-secret <secret>]

Environment-specific test discovery (--env):
  Test suites follow the <Suite>.<ENV>.Tests naming convention, e.g.
  Calculations.DEV.Tests, BestPractices.ANY.Tests, ColumnTests.BKUP.Tests.
  --env DEV runs only the *.DEV.Tests suites: live discovery calls
  PQL.Assert.RetrieveTestsV2("DEV"); file scans match the naming convention.

Power BI cloud environment (Public, USGov, China, …):
  Not a per-command flag.  It comes from the credential stored by
  `pql-test auth login --environment <cloud>`, or from the PQL_ENVIRONMENT
  env var when explicit service-principal credentials are supplied
  (e.g. CI pipelines).  Default: Public.

Environment variables (loaded from .env when python-dotenv is installed):
  PQL_TENANT_ID, PQL_WORKSPACE_ID, PQL_DATASET_ID,
  PQL_CLIENT_ID, PQL_CLIENT_SECRET, PQL_ENVIRONMENT, PQL_TEST_ENV
"""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

# Load .env automatically when python-dotenv is available — unless the test
# suite has asked for hermetic mode (no developer-machine state leaking into
# subprocess-launched CLI runs).  See run_cli() in tests/test_pql_test_cli.py.
if not os.environ.get("PQL_TEST_HERMETIC"):
    try:
        from dotenv import load_dotenv  # type: ignore[import-untyped]
        load_dotenv()
    except ImportError:
        pass  # env vars may be set externally (e.g. CI pipeline secrets)

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

import click

from pql_test.runner import (
    HAS_MSAL,
    HAS_PSUTIL,
    Environment,
    PqlTest,
    TestSuite,
    XmlaConnectionOptions,
    category_counts,
    collect_coverage,
    coverage_report_to_dict,
    get_pbi_files_opened,
    has_pyadomd,
    parse_model_identifier,
    resolve_local_xmla_connection_by_name,
    resolve_service_xmla_connection_by_name,
    resolve_xmla_connection,
    retrieve_test_by_name,
    retrieve_tests,
    run_tests_from_model,
    summarize_coverage,
)
from pql_test.runner.cli_format import (
    STATUS_COLORS,
    banner,
    pad,
    table_bottom,
    table_mid,
    table_row,
    table_top,
    truncate,
)
from pql_test.runner.coverage_collector import CoverageReport
from pql_test.runner.coverage_report import CoverageSummary, coverage_percent, coverage_status
from pql_test.contract_run import RunHooks, attach_contract_run
from pql_test.plugins import load_plugins

try:
    _VERSION = _pkg_version("pql-test")
except PackageNotFoundError:
    _VERSION = "0.0.0"


# ---------------------------------------------------------------------------
# Prerequisites check
# ---------------------------------------------------------------------------

def _check_prereqs() -> list[dict]:
    results = []

    major, minor = sys.version_info[:2]
    results.append(
        {
            "name": "Python >= 3.9",
            "ok": (major, minor) >= (3, 9),
            "detail": f"Current: {sys.version.split()[0]}",
        }
    )
    results.append(
        {
            "name": "pyadomd (ADOMD.NET XMLA client)",
            "ok": has_pyadomd(),
            "detail": (
                "pyadomd available"
                if has_pyadomd()
                else "Not installed — pip install pyadomd  "
                     "(requires .NET / ADOMD.NET on Windows)"
            ),
        }
    )
    results.append(
        {
            "name": "msal (Azure AD / service-principal auth)",
            "ok": HAS_MSAL,
            "detail": (
                "msal available"
                if HAS_MSAL
                else "Not installed — pip install msal"
            ),
        }
    )
    results.append(
        {
            "name": "psutil (local Power BI Desktop detection)",
            "ok": HAS_PSUTIL,
            "detail": (
                "psutil available"
                if HAS_PSUTIL
                else "Not installed — pip install psutil  (optional, required for local/<name> discovery)"
            ),
        }
    )
    # Optional: never fails the check. Read from package metadata so pql-odcs is not imported.
    try:
        odcs_version = _pkg_version("pql-odcs")
    except PackageNotFoundError:
        odcs_version = None
    results.append(
        {
            "name": "pql-odcs (optional, `pql-test contract` commands)",
            "ok": True,
            "detail": (
                f"pql-odcs {odcs_version} available — run `pql-test contract doctor` to check a model"
                if odcs_version
                else "Not installed — pip install pql-test[contracts]  (optional, for ODCS data contracts)"
            ),
        }
    )
    return results


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# JSON serializers
# ---------------------------------------------------------------------------

def _test_to_dict(t: PqlTest) -> dict:
    return {
        "name": t.name,
        "description": t.description,
        "file_path": t.file_path,
        "impersonated_user_name": t.impersonated_user_name,
    }


def _suite_to_dict(suite: TestSuite) -> dict:
    return {
        "model_path": suite.model_path,
        "passed": suite.passed,
        "failed": suite.failed,
        "skipped": suite.skipped,
        "total": suite.total,
        "results": [
            {
                "test_name": r.test_name,
                "expected": r.expected,
                "actual": r.actual,
                "passed": r.passed,
                "suite_name": r.suite_name,
                "skipped": r.skipped,
                "error": r.error,
                "duration_ms": r.duration_ms,
            }
            for r in suite.results
        ],
    }


def _print_prereqs(results: list[dict]) -> None:
    click.echo("\nPrerequisites check:")
    for r in results:
        icon = "\u2705" if r["ok"] else "\u274c"
        click.echo(f"  {icon} {r['name']} \u2014 {r['detail']}")
    all_ok = all(r["ok"] for r in results)
    click.echo(
        "\nAll prerequisites met.\n"
        if all_ok
        else "\nSome prerequisites are missing.\n"
    )


def _print_tests(tests: list[PqlTest], verbose: bool) -> None:
    if not tests:
        click.echo("No tests found.")
        return
    click.echo(f"\nFound {len(tests)} DAX test suite(s):\n")
    for t in tests:
        click.echo(f"  \u2022 {t.name}")
        if t.description:
            click.echo(f"    {t.description}")
        if t.impersonated_user_name:
            click.echo(f"    RLS user: {t.impersonated_user_name}")
        if verbose and t.file_path:
            click.echo(f"    File: {t.file_path}")
    click.echo("")


def _print_results(
    suite: TestSuite,
    verbose: bool,
    pre_warnings: list[str] | None = None,
    environment: str | None = None,
) -> None:
    """Print test results in a pytest-style format."""

    click.echo("\n" + banner("test session starts"))
    click.echo(f"model: {suite.model_path}")
    click.echo("")

    failures = [r for r in suite.results if not r.passed and not r.skipped]
    skipped_results = [r for r in suite.results if r.skipped]

    # Roll the per-assertion list up by SUITE and render as a table.  A
    # 60-test run shows ~6 rows (one per suite) with Pass/Fail/Skip counts
    # broken out into their own columns so the eye snaps straight to any
    # non-zero Fail/Skip cell.  `--verbose` additionally expands every
    # suite to show its individual assertions in a Details section below.
    by_suite: dict[str, list] = {}
    for r in suite.results:
        sn = r.suite_name or r.test_name
        by_suite.setdefault(sn, []).append(r)

    if by_suite:
        # ---- column geometry ----
        STATUS_W = 4   # "PASS"/"FAIL"/"SKIP" / header "Stat"
        COUNT_W = 4    # headers "Pass"/"Fail"/"Skip", up to 4-digit counts
        SUITE_MAX = 50
        # Suite column expands to fit the longest name but is capped so
        # one pathological name can't blow past the terminal.  Longer
        # names get an ellipsis truncation.
        suite_width = max(
            len("Suite"),
            min(SUITE_MAX, max(len(sn) for sn in by_suite)),
        )

        widths = [STATUS_W, suite_width, COUNT_W, COUNT_W, COUNT_W]

        # ---- top border + header row ----
        click.echo(table_top(widths))
        click.echo(
            table_row(
                [
                    pad("Stat", STATUS_W),
                    pad("Suite", suite_width),
                    pad("Pass", COUNT_W),
                    pad("Fail", COUNT_W),
                    pad("Skip", COUNT_W),
                ]
            )
        )
        click.echo(table_mid(widths))

        # ---- data rows ----
        for sn, results in by_suite.items():
            n_pass = sum(1 for r in results if r.passed and not r.skipped)
            n_fail = sum(1 for r in results if not r.passed and not r.skipped)
            n_skip = sum(1 for r in results if r.skipped)
            if n_fail:
                tag = "FAIL"
            elif n_skip and not n_pass:
                tag = "SKIP"
            else:
                tag = "PASS"
            # Pad cells using the raw text length first; THEN colorize so
            # ANSI escape codes stay outside the visible-width math and
            # don't break alignment with the borders.
            stat_cell = click.style(pad(tag, STATUS_W), fg=STATUS_COLORS[tag])
            suite_cell = pad(truncate(sn, suite_width), suite_width)
            pass_str = str(n_pass) if n_pass else "-"
            fail_str = str(n_fail) if n_fail else "-"
            skip_str = str(n_skip) if n_skip else "-"
            pass_cell = pad(pass_str, COUNT_W, align="right")
            # Tint Fail red and Skip yellow when non-zero so the eye snaps
            # to the actionable cells.
            fail_cell = pad(fail_str, COUNT_W, align="right")
            if n_fail:
                fail_cell = click.style(fail_cell, fg=STATUS_COLORS["FAIL"])
            skip_cell = pad(skip_str, COUNT_W, align="right")
            if n_skip:
                skip_cell = click.style(skip_cell, fg=STATUS_COLORS["SKIP"])
            click.echo(table_row([stat_cell, suite_cell, pass_cell, fail_cell, skip_cell]))

        click.echo(table_bottom(widths))
        click.echo("")

        # ---- verbose: per-suite expansion of every assertion ----
        if verbose:
            click.echo(banner("Details", "-"))
            for sn, results in by_suite.items():
                click.echo(f"\n  {click.style(sn, bold=True)}")
                for r in results:
                    if r.skipped:
                        rtag = click.style("SKIP", fg=STATUS_COLORS["SKIP"])
                    elif r.passed:
                        rtag = click.style("PASS", fg=STATUS_COLORS["PASS"])
                    else:
                        rtag = click.style("FAIL", fg=STATUS_COLORS["FAIL"])
                    rline = f"    {rtag} {r.test_name}"
                    if r.message:
                        rline += f" -- {r.message}"
                    if r.duration_ms is not None:
                        rline += f" ({r.duration_ms:.0f}ms)"
                    click.echo(rline)
            click.echo("")

    # Detail sections (FAILURES + warnings summary) are --verbose only.
    # The default view is the table + the totals line at the bottom — for
    # everything else, the user opts in with --verbose.
    if verbose:
        if failures:
            click.echo(banner("FAILURES", "-", fg=STATUS_COLORS["FAIL"]))
            # Group failures by suite so related failures cluster together —
            # much easier to scan than a flat list when several suites fail.
            failures_by_suite: dict[str, list] = {}
            for r in failures:
                sn = r.suite_name or r.test_name
                failures_by_suite.setdefault(sn, []).append(r)
            for sn, fs in failures_by_suite.items():
                click.echo(
                    f"\n  {click.style(sn, bold=True)}  "
                    f"({click.style(f'{len(fs)} failed', fg=STATUS_COLORS['FAIL'])})"
                )
                for r in fs:
                    mark = click.style("✗", fg=STATUS_COLORS["FAIL"])
                    msg = r.message or ""
                    if msg:
                        click.echo(f"    {mark} {r.test_name} — {msg}")
                    else:
                        click.echo(f"    {mark} {r.test_name}")
                    if r.error:
                        click.echo(f"        Error: {r.error}")
            click.echo("")

        # Collect all warnings: pre-run messages + skipped-test messages
        # (deduplicated).
        warn_msgs: list[str] = list(pre_warnings or [])
        seen: set[str] = set(warn_msgs)
        for r in skipped_results:
            msg = r.message or r.test_name
            if msg not in seen:
                warn_msgs.append(msg)
                seen.add(msg)

        if warn_msgs:
            click.echo(banner("warnings summary", "-", fg=STATUS_COLORS["SKIP"]))
            for msg in warn_msgs:
                click.echo(f"  {click.style('WARN', fg=STATUS_COLORS['SKIP'])} {msg}")
            click.echo("")

    # When discovery returned nothing, make it obvious instead of producing
    # a confusing "0 passed, 0 failed, 0 total" line that looks like success.
    # See tasks/surface-silent-test-discovery-failures-epic.md.
    if suite.total == 0:
        click.echo(banner("No tests found.", fg=STATUS_COLORS["SKIP"]))
        causes = (
            "  Possible causes:\n"
            "    • The model has no PQL.Assert tests defined.\n"
            "    • Your account doesn't have access to the workspace/model.\n"
            "    • PQL.Assert isn't installed in this model.\n"
            "    • The connection failed (check the warning above)."
        )
        if environment:
            causes += (
                f"\n    • No test suite matches --env {environment} "
                f"(expected names like <Suite>.{environment}.Tests)."
            )
        click.echo(causes)
        click.echo(banner("0 passed, 0 failed, 0 total", fg=STATUS_COLORS["SKIP"]))
        return

    summary = f"{suite.passed} passed, {suite.failed} failed, {suite.total} total"
    if suite.skipped:
        plural = "s" if suite.skipped != 1 else ""
        summary += f", {suite.skipped} warning{plural}"

    if suite.failed > 0:
        summary_color = STATUS_COLORS["FAIL"]
    elif suite.skipped > 0:
        summary_color = STATUS_COLORS["SKIP"]
    else:
        summary_color = STATUS_COLORS["PASS"]
    click.echo(banner(summary, fg=summary_color))


def _print_results_azuredevops(suite: TestSuite, pre_warnings: list[str] | None = None) -> None:
    """Print test results using Azure DevOps pipeline logging commands."""
    click.echo("##[group]pql-test Results")
    click.echo(f"model: {suite.model_path}")
    click.echo("")

    for r in suite.results:
        if r.skipped:
            click.echo(f"##[warning]SKIPPED {r.test_name}: {r.message}")
        elif r.passed:
            click.echo(f"  PASS {r.test_name}")
        else:
            msg = f"FAILED {r.test_name}"
            if r.message:
                msg += f" -- {r.message}"
            click.echo(f"##[error]{msg}")
            if r.error:
                click.echo(f"##[error]  Error: {r.error}")

    for w in (pre_warnings or []):
        click.echo(f"##[warning]{w}")

    click.echo("")
    click.echo("##[endgroup]")

    summary = (
        f"{suite.passed} passed, {suite.failed} failed, "
        f"{suite.skipped} skipped, {suite.total} total"
    )
    result = "Failed" if suite.failed > 0 else "Succeeded"
    click.echo(f"##vso[task.complete result={result};]{summary}")


def _print_results_github(suite: TestSuite, pre_warnings: list[str] | None = None) -> None:
    """Print test results using GitHub Actions workflow commands."""
    click.echo("::group::pql-test Results")
    click.echo(f"model: {suite.model_path}")
    click.echo("")

    for r in suite.results:
        if r.skipped:
            click.echo(f"::warning::{r.test_name}: {r.message}")
        elif r.passed:
            click.echo(f"  PASS {r.test_name}")
        else:
            msg = r.message or ""
            click.echo(f"::error title={r.test_name}::{msg}")
            if r.error:
                click.echo(f"::error title={r.test_name} Error::{r.error}")

    for w in (pre_warnings or []):
        click.echo(f"::warning::{w}")

    click.echo("")
    click.echo("::endgroup::")

    summary = (
        f"{suite.passed} passed, {suite.failed} failed, "
        f"{suite.skipped} skipped, {suite.total} total"
    )
    click.echo(f"::notice::{summary}")


# ---------------------------------------------------------------------------
# Shared connection options decorator
# ---------------------------------------------------------------------------

_conn_options_list = [
    click.option(
        "--tenant-id",
        envvar="PQL_TENANT_ID",
        default=None,
        help="Azure AD tenant ID (or set PQL_TENANT_ID env var).",
    ),
    click.option(
        "--workspace-id",
        envvar="PQL_WORKSPACE_ID",
        default=None,
        help="Power BI workspace GUID (or set PQL_WORKSPACE_ID env var).",
    ),
    click.option(
        "--dataset-id",
        envvar="PQL_DATASET_ID",
        default=None,
        help="Dataset / semantic model GUID (or set PQL_DATASET_ID env var).",
    ),
    click.option(
        "--client-id",
        envvar="PQL_CLIENT_ID",
        default=None,
        help="Service principal client ID (or set PQL_CLIENT_ID env var).",
    ),
    click.option(
        "--client-secret",
        envvar="PQL_CLIENT_SECRET",
        default=None,
        help="Service principal client secret (or set PQL_CLIENT_SECRET env var).",
    ),
]


def conn_options(func):
    """Decorator that attaches all XMLA connection options to a Click command."""
    for option in reversed(_conn_options_list):
        func = option(func)
    return func


# Test-environment selector (--env).  The Power BI *cloud* environment is
# not a per-command flag: it comes from the stored `pql-test auth login
# --environment` credential (or the PQL_ENVIRONMENT env var), so --env here
# unambiguously means the test-suite environment.
_env_option = click.option(
    "--env",
    "test_environment",
    envvar="PQL_TEST_ENV",
    default=None,
    metavar="ENV",
    help=(
        "Only discover/run test suites for this environment (e.g. DEV, PROD, "
        "ANY, BKUP; or set PQL_TEST_ENV env var). Live discovery calls "
        'PQL.Assert.RetrieveTestsV2("<ENV>"); file scans match the '
        "<Suite>.<ENV>.Tests naming convention (case-insensitive, exact — "
        "ANY is a normal token, not a wildcard)."
    ),
)


def _format_local_miss_diagnostic(
    model_name: str,
    instances: list | None = None,
) -> str:
    """Build a multi-line diagnostic when local/<model_name> doesn't resolve.

    Shows every Power BI Desktop instance the CLI could detect (with
    ``<unnamed>`` for instances whose window title couldn't be read — that
    happens with the Microsoft Store build whose process tree is ACL-locked).
    Also lists the common reasons a name lookup misses so the user can
    self-diagnose without having to re-run with --verbose.

    When *instances* is provided, it is used directly — this lets the caller
    enumerate once and share the result with the resolver and any verbose
    printout.  When *instances* is ``None``, the diagnostic enumerates itself
    (preserves the original call signature for other callers).
    """
    lines: list[str] = [
        f"No matching Power BI Desktop instance found for model '{model_name}'.",
        "",
    ]
    if instances is None:
        try:
            instances = get_pbi_files_opened()
        except ImportError:
            lines.append(
                "  (psutil not installed — local detection limited to port-file fallback.)"
            )
            instances = []
    if instances:
        lines.append("Detected Power BI Desktop instances:")
        for inst in instances:
            name = inst.model_name or "<unnamed>"
            lines.append(f"  • '{name}'  →  {inst.server} / {inst.catalog}")
    else:
        lines.append("No Power BI Desktop instances detected on this machine.")
    lines.extend(
        [
            "",
            "Common causes:",
            f"  • The model isn't open yet — open '{model_name}' in Power BI Desktop and retry.",
            "  • Typo or case mismatch in the model name (matching is case-insensitive but exact otherwise).",
            "  • Spaces or parentheses in the name without quotes — wrap the whole argument in",
            '    double quotes, e.g. "local/OLS_Model (1)", so the shell passes it as one argument.',
            "  • Microsoft Store build of Power BI Desktop — its process tree runs under an",
            "    AppContainer ACL that blocks window-title detection, so the instance shows as",
            "    <unnamed>. Use the installer build, or switch to a filesystem path argument.",
        ]
    )
    return "\n".join(lines)


def _make_conn_opts(
    tenant_id: str | None,
    workspace_id: str | None,
    dataset_id: str | None,
    client_id: str | None,
    client_secret: str | None,
) -> XmlaConnectionOptions:
    # The Power BI cloud environment is not a per-command flag.  It defaults
    # to PQL_ENVIRONMENT (kept for CI pipelines that pass explicit
    # service-principal env vars), and the runner's stored-credential bridge
    # overrides it with the cloud recorded by `pql-test auth login`.
    raw_env = os.environ.get("PQL_ENVIRONMENT", "").strip()
    env = Environment.PUBLIC
    if raw_env:
        for e in Environment:
            if e.value.lower() == raw_env.lower():
                env = e
                break
    return XmlaConnectionOptions(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        dataset_id=dataset_id,
        client_id=client_id,
        client_secret=client_secret,
        environment=env,
    )


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group()
@click.version_option(version=_VERSION, prog_name="pql-test")
def cli() -> None:
    """pql-test: Discover and run DAX tests in PBIP semantic models."""


# ---------------------------------------------------------------------------
# check-prereqs
# ---------------------------------------------------------------------------

@cli.command("check-prereqs")
def cmd_check_prereqs() -> None:
    """Verify that all required packages and tools are available."""
    results = _check_prereqs()
    _print_prereqs(results)
    if not all(r["ok"] for r in results):
        sys.exit(1)


# ---------------------------------------------------------------------------
# retrieve-tests
# ---------------------------------------------------------------------------

@cli.command("retrieve-tests")
@click.argument("model_path", metavar="MODEL_PATH")
@click.option(
    "--test",
    "test_name",
    default=None,
    help="Show only the named test suite.",
)
@click.option("--human", is_flag=True, help="Human-readable output instead of JSON.")
@click.option("--verbose", "-v", is_flag=True, help="With --human: show file paths and connection info.")
@_env_option
@conn_options
def cmd_retrieve_tests(
    model_path: str,
    test_name: str | None,
    human: bool,
    verbose: bool,
    test_environment: str | None,
    tenant_id: str | None,
    workspace_id: str | None,
    dataset_id: str | None,
    client_id: str | None,
    client_secret: str | None,
) -> None:
    """List DAX test suites in MODEL_PATH.

    Outputs a JSON array by default. Use --human for formatted text.

    By default, test suites are discovered by scanning the SemanticModel's
    DAXQueries/ folder for *.Tests.dax files.  When XMLA options or the
    local/<model_name> identifier are supplied the live model is queried
    instead via PQL.Assert.RetrieveTestsV2() (falling back to
    PQL.Assert.RetrieveTests()), which returns ALL test functions registered
    in the model including those defined directly in functions.tmdl.

    MODEL_PATH accepts these formats:

    \b
      <workspace>.Workspace/<model>.SemanticModel
                                  Canonical Fabric service path — connect to
                                  a remote workspace by display names.
      local/<model_name>          Connect to a locally-open Power BI
                                  Desktop instance by model name.
      <filesystem_path>           Traditional PBIP root directory.

    Wrap MODEL_PATH in double quotes when the workspace or model name contains
    spaces or parentheses, e.g. "local/OLS_Model (1)" — otherwise the shell
    splits it into multiple arguments and the CLI never sees the full name.

    \b
    Examples:
      pql-test retrieve-tests ../examples
      pql-test retrieve-tests local/SampleModel
      pql-test retrieve-tests ../examples --env DEV
      pql-test retrieve-tests "MyWorkspace.Workspace/MySemanticModel.SemanticModel"
      pql-test retrieve-tests "MyWorkspace.Workspace/MySemanticModel.SemanticModel" --tenant-id ... --client-id ... --client-secret ...
    """
    ident = parse_model_identifier(model_path)
    opts = _make_conn_opts(tenant_id, workspace_id, dataset_id, client_id, client_secret)

    conn = None
    abs_path: str = ""

    if ident.kind == "local":
        # local/<model_name> — resolve local connection by name
        conn = resolve_local_xmla_connection_by_name(ident.model_name)
        if conn is None:
            click.echo(
                "Warning: " + _format_local_miss_diagnostic(ident.model_name),
                err=True,
            )
        abs_path = f"local/{ident.model_name}"

    elif ident.kind == "service":
        # Fabric service path (canonical .Workspace/.SemanticModel form
        # or legacy <workspace>.<model> dot notation)
        conn = resolve_service_xmla_connection_by_name(
            ident.workspace_name, ident.model_name, opts,
        )
        if conn is None:
            click.echo(
                "Error: Service connection requires --tenant-id, --client-id, and --client-secret.",
                err=True,
            )
            sys.exit(1)
        abs_path = ident.raw

    else:
        # Traditional filesystem path
        abs_path = str(Path(model_path).resolve())
        if not Path(abs_path).exists():
            click.echo(f"Error: Model path not found: {abs_path}", err=True)
            sys.exit(1)

        # Derive dataset display name from the .SemanticModel directory so
        # the service path can look it up by name when no --dataset-id is
        # supplied (see cmd_run_tests for the rationale).
        if not opts.dataset_id and not opts.dataset_name:
            _sem_name = Path(abs_path).name
            if _sem_name.endswith(".SemanticModel"):
                opts.dataset_name = _sem_name[: -len(".SemanticModel")]

        # Always attempt connection resolution so local Power BI Desktop is
        # auto-detected even when no flags are supplied — matches cmd_run_tests
        # behavior and the README's "Local Power BI Desktop (auto-detected)"
        # section.  Returns None when nothing is available, in which case the
        # caller falls back to the offline DAXQueries/ file scan.
        conn = resolve_xmla_connection(abs_path, opts)

    if test_name:
        test = retrieve_test_by_name(
            abs_path, test_name, connection=conn, environment=test_environment
        )
        if not test:
            if human:
                click.echo(f'No test found with name: "{test_name}"')
            else:
                click.echo(json.dumps(None))
            sys.exit(1)
        results = [test]
    else:
        results = retrieve_tests(abs_path, connection=conn, environment=test_environment)

    if human:
        _print_tests(results, verbose)
        if verbose:
            if conn:
                click.echo(f"Connection: {conn.server} / {conn.catalog}")
            else:
                click.echo(
                    "Connection: none detected \u2014 open the model in Power BI Desktop "
                    "or supply --tenant-id, --workspace-id, --dataset-id to run tests."
                )
    else:
        click.echo(json.dumps([_test_to_dict(t) for t in results], indent=2))


# ---------------------------------------------------------------------------
# retrieve-test
# ---------------------------------------------------------------------------

@cli.command("retrieve-test")
@click.argument("model_path", metavar="MODEL_PATH")
@click.argument("name")
@click.option("--human", is_flag=True, help="Human-readable output instead of JSON.")
@click.option("--verbose", "-v", is_flag=True, help="With --human: also print the full DAX source.")
@conn_options
def cmd_retrieve_test(
    model_path: str,
    name: str,
    human: bool,
    verbose: bool,
    tenant_id: str | None,
    workspace_id: str | None,
    dataset_id: str | None,
    client_id: str | None,
    client_secret: str | None,
) -> None:
    """Show a specific DAX test suite by name.

    Outputs a JSON object by default. Use --human for formatted text.

    MODEL_PATH accepts these formats:

    \b
      <workspace>.Workspace/<model>.SemanticModel
                                  Canonical Fabric service path — connect to
                                  a remote workspace by display names.
      local/<model_name>          Connect to a locally-open Power BI
                                  Desktop instance by model name.
      <filesystem_path>           Traditional PBIP root directory.

    Wrap MODEL_PATH in double quotes when the workspace or model name contains
    spaces or parentheses, e.g. "local/OLS_Model (1)" — otherwise the shell
    splits it into multiple arguments and the CLI never sees the full name.
    """
    ident = parse_model_identifier(model_path)
    opts = _make_conn_opts(tenant_id, workspace_id, dataset_id, client_id, client_secret)

    conn = None
    abs_path: str = ""

    if ident.kind == "local":
        conn = resolve_local_xmla_connection_by_name(ident.model_name)
        abs_path = f"local/{ident.model_name}"
    elif ident.kind == "service":
        conn = resolve_service_xmla_connection_by_name(
            ident.workspace_name, ident.model_name, opts,
        )
        if conn is None:
            click.echo(
                "Error: Service connection requires --tenant-id, --client-id, and --client-secret.",
                err=True,
            )
            sys.exit(1)
        abs_path = ident.raw
    else:
        abs_path = str(Path(model_path).resolve())
        if not Path(abs_path).exists():
            click.echo(f"Error: Model path not found: {abs_path}", err=True)
            sys.exit(1)

        # Mirror cmd_retrieve_tests / cmd_run_tests: derive dataset name
        # from the .SemanticModel directory stem so a service-principal
        # connection can be built without --dataset-id, and attempt
        # connection resolution so tests declared only in functions.tmdl
        # (no *.Tests.dax file) are still discoverable via live XMLA.
        if not opts.dataset_id and not opts.dataset_name:
            _sem_name = Path(abs_path).name
            if _sem_name.endswith(".SemanticModel"):
                opts.dataset_name = _sem_name[: -len(".SemanticModel")]
        conn = resolve_xmla_connection(abs_path, opts)

    test = retrieve_test_by_name(abs_path, name, connection=conn)
    if not test:
        if human:
            click.echo(f'No test found with name: "{name}"')
        else:
            click.echo(json.dumps(None))
        sys.exit(1)

    if human:
        _print_tests([test], verbose)
        if verbose:
            click.echo("Source:")
            click.echo(test.source)
    else:
        d = _test_to_dict(test)
        if verbose:
            d["source"] = test.source
        click.echo(json.dumps(d, indent=2))


# ---------------------------------------------------------------------------
# run-tests
# ---------------------------------------------------------------------------

@cli.command("run-tests")
@click.argument("model_path", metavar="MODEL_PATH")
@click.option(
    "--test",
    "test_name",
    default=None,
    help="Run only the named test suite.",
)
@click.option("--verbose", "-v", is_flag=True, help="Show per-assertion detail (message and duration) for every result.")
@click.option(
    "--output",
    "output",
    default=None,
    metavar="FILE",
    help="Write full JSON results to FILE in addition to the human-readable output.",
)
@click.option(
    "--log-format",
    "log_format",
    default=None,
    type=click.Choice(["azuredevops", "github"], case_sensitive=False),
    help=(
        "Emit CI-native log annotations instead of human-readable output. "
        "azuredevops: ##[group]/##[error]/##vso[task.complete] commands. "
        "github: ::group::/::error::/::notice:: commands."
    ),
)
@_env_option
@conn_options
def cmd_run_tests(
    model_path: str,
    test_name: str | None,
    verbose: bool,
    output: str | None,
    log_format: str | None,
    test_environment: str | None,
    tenant_id: str | None,
    workspace_id: str | None,
    dataset_id: str | None,
    client_id: str | None,
    client_secret: str | None,
) -> None:
    """Run all DAX test suites in a PBIP model via XMLA.

    Results are printed in a pytest-style format by default.
    Use --output to also save full JSON results to a file.
    Use --log-format to emit CI-native annotations for Azure DevOps or
    GitHub Actions pipelines.
    Use --env to run only the test suites targeting one environment
    (suites follow the <Suite>.<ENV>.Tests naming convention, e.g.
    Calculations.DEV.Tests, BestPractices.ANY.Tests).

    MODEL_PATH accepts these formats:

    \b
      <workspace>.Workspace/<model>.SemanticModel
                                  Canonical Fabric service path — connect to
                                  a remote workspace by display names.
      local/<model_name>          Connect to a locally-open Power BI
                                  Desktop instance by model name.
      <filesystem_path>           Traditional PBIP root directory.

    Wrap MODEL_PATH in double quotes when the workspace or model name contains
    spaces or parentheses, e.g. "local/OLS_Model (1)" — otherwise the shell
    splits it into multiple arguments and the CLI never sees the full name.

    \b
    Examples:
      pql-test run-tests ../examples
      pql-test run-tests local/SampleModel
      pql-test run-tests "MyWorkspace.Workspace/MySemanticModel.SemanticModel"
      pql-test run-tests "MyWorkspace.Workspace/MySemanticModel.SemanticModel" --tenant-id ... --client-id ... --client-secret ...
      pql-test run-tests ../examples/SampleModel.SemanticModel --env DEV
      pql-test run-tests "MyWorkspace.Workspace/MySemanticModel.SemanticModel" --env PROD
      pql-test run-tests ../examples/SampleModel.SemanticModel --output results.json
      pql-test run-tests local/SampleModel --log-format github
    """
    ident = parse_model_identifier(model_path)
    opts = _make_conn_opts(tenant_id, workspace_id, dataset_id, client_id, client_secret)

    pre_warnings: list[str] = []
    conn = None
    abs_path: str = ""

    if ident.kind == "local":
        # local/<model_name> — resolve local connection by name
        abs_path = f"local/{ident.model_name}"

        # Enumerate open Power BI Desktop instances once and share the
        # result with the verbose printout, the resolver, and the miss
        # diagnostic — otherwise a single miss triggers 3+ redundant
        # process/window/port scans (each of which used to run an ADOMD
        # probe per port).  See tasks/speed-up-local-pbi-detection-epic.md.
        instances: list | None
        try:
            instances = get_pbi_files_opened()
        except ImportError:
            instances = None

        if verbose:
            if instances is None:
                click.echo("\npsutil not installed \u2014 local detection limited to port-file fallback.")
            elif instances:
                click.echo("\nDetected Power BI Desktop instances:")
                for inst in instances:
                    name = inst.model_name or "<unnamed>"
                    click.echo(f"  \u2022 '{name}'  \u2192  {inst.server} / {inst.catalog}")
            else:
                click.echo("\nNo Power BI Desktop instances detected.")

        conn = resolve_local_xmla_connection_by_name(ident.model_name, instances=instances)
        if conn:
            click.echo(f"\nLocal XMLA connection: {conn.server} / catalog: {conn.catalog}")
        else:
            diagnostic = _format_local_miss_diagnostic(
                ident.model_name, instances=instances,
            )
            pre_warnings.append(diagnostic)
            click.echo("\nWarning: " + diagnostic, err=True)

    elif ident.kind == "service":
        # Fabric service path (canonical .Workspace/.SemanticModel form
        # or legacy <workspace>.<model> dot notation)
        conn = resolve_service_xmla_connection_by_name(
            ident.workspace_name, ident.model_name, opts,
        )
        abs_path = ident.raw
        if conn:
            click.echo(f"\nXMLA connection: {conn.server} / catalog: {conn.catalog}")
        else:
            click.echo(
                "Error: Service connection requires --tenant-id, --client-id, and --client-secret.",
                err=True,
            )
            sys.exit(1)

    else:
        # Traditional filesystem path
        abs_path = str(Path(model_path).resolve())
        if not Path(abs_path).exists():
            click.echo(f"Error: Model path not found: {abs_path}", err=True)
            sys.exit(1)

        # Derive the dataset display name from the .SemanticModel directory
        # stem so the resolver can look it up by name when no --dataset-id
        # is provided.  Keeps callers from having to store dataset GUIDs as
        # secrets when the deployed dataset's display name matches the
        # local directory.  dataset_id (if supplied) still takes precedence
        # inside the resolver.
        if not opts.dataset_id and not opts.dataset_name:
            _sem_name = Path(abs_path).name
            if _sem_name.endswith(".SemanticModel"):
                opts.dataset_name = _sem_name[: -len(".SemanticModel")]

        conn = resolve_xmla_connection(abs_path, opts)
        if conn:
            click.echo(f"\nXMLA connection: {conn.server} / catalog: {conn.catalog}")
        else:
            pre_warnings.append(
                "No XMLA connection detected. Tests will be reported as skipped. "
                "Pass local/<model_name> to target an open Power BI Desktop instance, "
                "or supply --tenant-id, --workspace-id, --dataset-id."
            )
            click.echo(
                "\nWarning: No XMLA connection detected. Tests will be reported as skipped.\n"
                "Options:\n"
                "  \u2022 Pass local/<model_name> with the model open in Power BI Desktop\n"
                "  \u2022 Supply --tenant-id, --workspace-id, --dataset-id\n"
                "    (and --client-id, --client-secret for service-principal auth)\n",
                err=True,
            )

    if ident.kind == "local" and not conn:
        skip_message = (
            f"No matching Power BI Desktop instance found for model "
            f"'{ident.model_name or ''}'. "
            "Make sure the model is open in Power BI Desktop."
        )
    else:
        skip_message = (
            "No XMLA connection available. "
            "Pass local/<model_name> with the model open in Power BI Desktop, "
            "or supply --tenant-id, --workspace-id, and --dataset-id."
        )

    suite = run_tests_from_model(
        abs_path,
        test_name,
        opts,
        connection=conn,
        skip_message=skip_message,
        environment=test_environment,
        connection_pre_resolved=True,
    )

    if log_format == "azuredevops":
        _print_results_azuredevops(suite, pre_warnings=pre_warnings)
    elif log_format == "github":
        _print_results_github(suite, pre_warnings=pre_warnings)
    else:
        _print_results(suite, verbose, pre_warnings=pre_warnings, environment=test_environment)

    if output:
        out_path = Path(output)
        out_path.write_text(json.dumps(_suite_to_dict(suite), indent=2), encoding="utf-8")
        click.echo(f"\nJSON results written to: {output}")

    # Exit non-zero on hard test failures OR when tests were discovered but
    # none actually ran (every result was skipped because no XMLA connection
    # could be established).  The latter catches CI misconfigurations like a
    # matrix entry whose `.SemanticModel` directory has no matching deployed
    # dataset — without this guard the workflow silently reports the job as
    # passing.  Empty models (zero tests discovered) are still exit 0; that
    # is a legitimate "nothing to do" outcome, not a failure.
    has_failures = suite.failed > 0
    all_skipped = suite.total > 0 and suite.skipped == suite.total
    sys.exit(1 if has_failures or all_skipped else 0)


# ---------------------------------------------------------------------------
# code-coverage
# ---------------------------------------------------------------------------

def _print_coverage_report(
    report: CoverageReport,
    summary: CoverageSummary,
    verbose: bool,
    ident_kind: str = "path",
    min_coverage: float | None = None,
) -> None:
    if report.connection:
        label = "Local XMLA connection" if ident_kind == "local" else "XMLA connection"
        click.echo(f"\n{label}: {report.connection.server} / catalog: {report.connection.catalog}")

    click.echo("\n" + banner("coverage session starts"))
    click.echo(f"model: {report.model_path}")
    click.echo("")
    click.echo(f"Tests discovered: {report.test_count}")
    if report.test_count == 0:
        click.echo(
            "No tests discovered. If PQL.Assert isn't installed in this "
            "model, coverage cannot be measured until it is (see any "
            "discovery warning above)."
        )
    overall_color = STATUS_COLORS[coverage_status(summary.percent, min_coverage)]
    overall = f"{summary.covered}/{summary.eligible} covered ({summary.percent}%)"
    click.echo(f"\nOverall: {click.style(overall, fg=overall_color)}")

    counts = category_counts(report)
    excluded_counts: dict = {}
    for exclusion in report.result.excluded:
        excluded_counts[exclusion.object_type] = excluded_counts.get(exclusion.object_type, 0) + 1
    all_types = sorted(set(counts) | set(excluded_counts), key=lambda t: t.value)

    if all_types:
        # Build (name, covered_str, eligible_str, pct_str, color) rows first so
        # column widths -- including the "%" column, which must also fit
        # "excluded (N)" -- can be sized from the actual data.
        rows: list[tuple[str, str, str, str, str | None]] = []
        for object_type in all_types:
            covered, eligible = counts.get(object_type, (0, 0))
            excluded_n = excluded_counts.get(object_type, 0)
            if eligible:
                pct = coverage_percent(covered, eligible)
                color = STATUS_COLORS[coverage_status(pct, min_coverage)]
                rows.append((object_type.value, str(covered), str(eligible), f"{pct}%", color))
            elif excluded_n:
                rows.append((object_type.value, "-", "-", f"excluded ({excluded_n})", None))
            else:
                rows.append((object_type.value, "0", "0", "-", None))

        CAT_W = max(len("Category"), max(len(r[0]) for r in rows))
        COVERED_W = len("Covered")
        ELIGIBLE_W = len("Eligible")
        PCT_W = max(len("%"), max(len(r[3]) for r in rows))
        widths = [CAT_W, COVERED_W, ELIGIBLE_W, PCT_W]

        click.echo("\nBy category:")
        click.echo(table_top(widths))
        click.echo(
            table_row(
                [
                    pad("Category", CAT_W),
                    pad("Covered", COVERED_W, align="right"),
                    pad("Eligible", ELIGIBLE_W, align="right"),
                    pad("%", PCT_W, align="right"),
                ]
            )
        )
        click.echo(table_mid(widths))
        for name, covered_s, eligible_s, pct_s, color in rows:
            pct_cell = pad(pct_s, PCT_W, align="right")
            if color:
                pct_cell = click.style(pct_cell, fg=color)
            click.echo(
                table_row(
                    [
                        pad(name, CAT_W),
                        pad(covered_s, COVERED_W, align="right"),
                        pad(eligible_s, ELIGIBLE_W, align="right"),
                        pct_cell,
                    ]
                )
            )
        click.echo(table_bottom(widths))

    if report.unavailable:
        click.echo("\nUnavailable categories (not counted as covered or uncovered):")
        for u in report.unavailable:
            click.echo(f"  {u.object_type.value} — {u.reason}")

    if verbose:
        if report.result.covered:
            click.echo("\nCovered objects:")
            for e in sorted(report.result.covered, key=lambda e: (e.object_type.value, e.identifier)):
                click.echo(f"  {e.object_type.value} {e.identifier} — tested by: {', '.join(e.test_names)}")
        if report.result.gaps:
            click.echo("\nUncovered objects (AI test targets):")
            for g in sorted(report.result.gaps, key=lambda g: (g.object_type.value, g.identifier)):
                click.echo(f"  {g.object_type.value} {g.identifier} — {g.test_target_hint}")
        if report.result.excluded:
            click.echo("\nExcluded objects:")
            for ex in sorted(report.result.excluded, key=lambda e: (e.object_type.value, e.identifier)):
                click.echo(f"  {ex.object_type.value} {ex.identifier} — {ex.reason}")


def _validate_finite_min_coverage(
    ctx: click.Context, param: click.Parameter, value: float | None
) -> float | None:
    """Reject non-finite --min-coverage values that FloatRange(0, 100) lets through.

    math.nan compares False against both bounds, so click.FloatRange(0, 100)
    accepts "nan" even though the skill promises malformed thresholds fail
    before any XMLA query; the later ``summary.percent < min_coverage``
    check is also False for NaN, which would silently report success.
    """
    if value is not None and math.isnan(value):
        raise click.BadParameter("must be a finite number between 0 and 100", ctx=ctx, param=param)
    return value


@cli.command("code-coverage")
@click.argument("model_path", metavar="MODEL_PATH")
@click.option(
    "--verbose", "-v", is_flag=True,
    help="List covered objects with their direct test-UDF evidence and uncovered objects with AI-ready test targets.",
)
@click.option(
    "--format", "output_format",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    help="Output format: human-readable text (default) or a stable JSON report.",
)
@click.option(
    "--output", "output",
    default=None, metavar="FILE",
    help="Write the JSON report to FILE. Requires --format json.",
)
@click.option(
    "--min-coverage", "min_coverage",
    type=click.FloatRange(0, 100), default=None, metavar="PERCENT",
    callback=_validate_finite_min_coverage,
    help="Exit non-zero when overall eligible coverage is below PERCENT.",
)
@conn_options
def cmd_code_coverage(
    model_path: str,
    verbose: bool,
    output_format: str,
    output: str | None,
    min_coverage: float | None,
    tenant_id: str | None,
    workspace_id: str | None,
    dataset_id: str | None,
    client_id: str | None,
    client_secret: str | None,
) -> None:
    """Report direct test-UDF coverage for a PBIP model via XMLA.

    A calculated column, measure, or table counts as covered only when a
    discovered test UDF has a direct INFO.CALCDEPENDENCY() edge to it; a
    relationship or role only from evidence explicitly attributable to a
    discovered test UDF (a parsed PQL.Assert.Relationship.ShouldExist call,
    or the test's PQLAssert_RoleName annotation). Partitions have no
    PQL.Assert assertion surface and are always excluded — never counted
    covered or uncovered. See
    tasks/direct-udf-code-coverage-metadata-contract.md for the full
    contract and its limits.

    MODEL_PATH accepts the same three formats as run-tests: a filesystem
    PBIP path, local/<model_name>, or the Fabric-style service path.

    \b
    Examples:
      pql-test code-coverage local/SampleModel
      pql-test code-coverage ../examples/SampleModel.SemanticModel --verbose
      pql-test code-coverage local/SampleModel --format json --output coverage.json
      pql-test code-coverage local/SampleModel --min-coverage 60
    """
    output_format = output_format.lower()
    if output and output_format != "json":
        raise click.UsageError("--output requires --format json.")

    ident = parse_model_identifier(model_path)
    opts = _make_conn_opts(tenant_id, workspace_id, dataset_id, client_id, client_secret)
    abs_path = model_path

    if ident.kind not in ("local", "service"):
        # Traditional filesystem path — fail clearly instead of falling
        # through to the generic "No XMLA connection detected" message,
        # matching cmd_run_tests/cmd_retrieve_tests/cmd_retrieve_test.
        abs_path = str(Path(model_path).resolve())
        if not Path(abs_path).exists():
            click.echo(f"Error: Model path not found: {abs_path}", err=True)
            sys.exit(1)

        # Derive the dataset display name from the .SemanticModel directory
        # stem, same as cmd_run_tests, so the resolver can look it up by
        # name when no --dataset-id is provided.
        if not opts.dataset_id and not opts.dataset_name:
            _sem_name = Path(abs_path).name
            if _sem_name.endswith(".SemanticModel"):
                opts.dataset_name = _sem_name[: -len(".SemanticModel")]

    report = collect_coverage(abs_path, opts)
    if report is None:
        click.echo(
            f"Error: No XMLA connection detected for '{model_path}'. "
            "Pass local/<model_name> with the model open in Power BI Desktop, "
            "or supply --tenant-id, --workspace-id, and --dataset-id "
            "(or --tenant-id, --client-id, --client-secret with the canonical "
            "<workspace>.Workspace/<model>.SemanticModel path).",
            err=True,
        )
        sys.exit(1)

    summary = summarize_coverage(report)

    if output_format == "json":
        payload = coverage_report_to_dict(report)
        text = json.dumps(payload, indent=2)
        if output:
            Path(output).write_text(text, encoding="utf-8")
            click.echo(f"Coverage report written to: {output}")
        else:
            click.echo(text)
    else:
        _print_coverage_report(report, summary, verbose, ident.kind, min_coverage)

    if min_coverage is not None:
        if summary.percent < min_coverage:
            click.echo(
                f"\nError: coverage {summary.percent}% is below the required {min_coverage}% threshold.",
                err=True,
            )
            sys.exit(1)
        # Mirror pytest-cov's "Required test coverage of N% reached" so CI logs
        # show the gate was evaluated. Goes to stderr when JSON is on stdout.
        click.echo(
            f"\nRequired coverage of {min_coverage}% reached. Total coverage: {summary.percent}%",
            err=output_format == "json" and not output,
        )


# ---------------------------------------------------------------------------
# auth command group
# ---------------------------------------------------------------------------

@cli.group("auth")
def auth() -> None:
    """Manage authentication for pql-test."""


@auth.command("login")
@click.option(
    "-u",
    "--user",
    "--client-id",
    "user_or_client",
    help="Username or client ID for authentication",
)
@click.option(
    "-p",
    "--password",
    help="Password, client secret, or certificate password (prompts if not provided)",
)
@click.option(
    "--tenant",
    "--tenant-id",
    "tenant_id",
    help="Azure AD tenant ID",
)
@click.option(
    "--certificate",
    help="Path to certificate file (.pem or .p12) for certificate-based auth",
)
@click.option(
    "--federated-token",
    help="Federated credential token for workload identity",
)
@click.option(
    "--identity",
    is_flag=True,
    help="Use managed identity authentication (Azure VM/Container)",
)
@click.option(
    "--environment",
    type=click.Choice(["Public", "USGov", "USGovHigh", "USGovDoD", "Germany", "China"]),
    default="Public",
    help="Azure cloud environment",
)
def cmd_auth_login(
    user_or_client: str | None,
    password: str | None,
    tenant_id: str | None,
    certificate: str | None,
    federated_token: str | None,
    identity: bool,
    environment: str,
) -> None:
    """
    Log in to pql-test with persistent authentication.

    Examples:

      # Interactive browser login
      pql-test auth login

      # Service principal with secret
      pql-test auth login -u <client-id> -p <secret> --tenant <tenant-id>

      # Service principal with certificate
      pql-test auth login -u <client-id> --certificate cert.pem --tenant <tenant-id>

      # Managed identity (system-assigned)
      pql-test auth login --identity

      # Managed identity (user-assigned)
      pql-test auth login --identity -u <client-id>
    """
    from pql_test.auth import AuthenticationManager, AuthMethod, CredentialConfig

    manager = AuthenticationManager()

    # Determine authentication method from provided arguments
    if identity:
        # Managed identity
        config = CredentialConfig(
            method=AuthMethod.MANAGED_IDENTITY,
            client_id=user_or_client,  # For user-assigned MI
            use_system_assigned_identity=(user_or_client is None),
            environment=environment,
            account_name="Managed Identity",
        )
        click.echo("Authenticating with managed identity...")

    elif federated_token:
        # Federated credential
        if not all([user_or_client, tenant_id]):
            click.echo(
                "Error: Federated credential requires --user (client ID) and --tenant",
                err=True,
            )
            sys.exit(1)

        config = CredentialConfig(
            method=AuthMethod.SERVICE_PRINCIPAL_FEDERATED,
            client_id=user_or_client,
            tenant_id=tenant_id,
            federated_token=federated_token,
            environment=environment,
            account_name=f"SP {user_or_client}",
        )
        click.echo("Authenticating with federated credential...")

    elif certificate:
        # Certificate-based auth
        if not all([user_or_client, tenant_id]):
            click.echo(
                "Error: Certificate auth requires --user (client ID) and --tenant",
                err=True,
            )
            sys.exit(1)

        config = CredentialConfig(
            method=AuthMethod.SERVICE_PRINCIPAL_CERT,
            client_id=user_or_client,
            tenant_id=tenant_id,
            certificate_path=certificate,
            certificate_password=password,  # Optional
            environment=environment,
            account_name=f"SP {user_or_client}",
        )
        click.echo("Authenticating with certificate...")

    elif user_or_client and password:
        # Service principal with secret
        if not tenant_id:
            click.echo(
                "Error: Service principal auth requires --tenant",
                err=True,
            )
            sys.exit(1)

        config = CredentialConfig(
            method=AuthMethod.SERVICE_PRINCIPAL_SECRET,
            client_id=user_or_client,
            client_secret=password,
            tenant_id=tenant_id,
            environment=environment,
            account_name=f"SP {user_or_client}",
        )
        click.echo("Authenticating with service principal...")

    else:
        # No specific method flags provided - prompt the user
        if not any([user_or_client, password, tenant_id]):
            # Fully interactive mode - ask how they want to authenticate
            click.echo("How would you like to authenticate pql-test?")
            click.echo()
            click.echo("  1. Interactive with a web browser (recommended)")
            click.echo("  2. Service principal with secret")
            click.echo()

            choice = click.prompt(
                "Select authentication method",
                type=click.IntRange(1, 2),
                default=1,
            )

            if choice == 1:
                # Interactive browser - no tenant ID needed.  client_id is
                # left at None so the factory uses the bundled pql-test
                # multi-tenant app id (see auth/factory.py).
                config = CredentialConfig(
                    method=AuthMethod.INTERACTIVE,
                    tenant_id=None,  # Let Azure Identity discover from login
                    environment=environment,
                    account_name="Interactive User",
                )
                click.echo("\nLaunching browser for interactive authentication...")

            else:  # choice == 2
                # Service principal with secret
                tenant_id = click.prompt("Azure AD tenant ID", type=str)
                client_id = click.prompt("Client ID", type=str)
                client_secret = click.prompt("Client secret", hide_input=True)

                config = CredentialConfig(
                    method=AuthMethod.SERVICE_PRINCIPAL_SECRET,
                    client_id=client_id,
                    client_secret=client_secret,
                    tenant_id=tenant_id,
                    environment=environment,
                    account_name=f"SP {client_id}",
                )
                click.echo("\nAuthenticating with service principal...")
        else:
            # Partial flags provided but not enough for SPN-secret — interactive.
            # Interactive browser login — no tenant ID needed (Azure Identity
            # discovers it from the sign-in).
            config = CredentialConfig(
                method=AuthMethod.INTERACTIVE,
                tenant_id=None,
                environment=environment,
                account_name="Interactive User",
            )
            click.echo("Launching browser for interactive authentication...")

    try:
        # Create the credential and test it by acquiring a token
        # This triggers the actual authentication flow (browser for interactive, etc.)
        credential = manager._factory.create(config, manager._cloud_config)

        # Get scope for Power BI service
        scope = manager._cloud_config.get_resource_scope(environment)

        # Trigger authentication.  For INTERACTIVE we use authenticate(scopes=...)
        # so we can capture the AuthenticationRecord and store it — future runs
        # then use the persistent MSAL cache silently instead of opening a new
        # browser tab on every CLI invocation.
        click.echo()
        if config.method == AuthMethod.INTERACTIVE and hasattr(credential, "authenticate"):
            record = credential.authenticate(scopes=[scope])
            try:
                config.authentication_record_json = record.serialize()
            except Exception:  # noqa: BLE001
                # If serialization fails the credential still works for this
                # invocation; we just lose the silent-replay optimization.
                pass
            # Account name from the record's username is more accurate than
            # our generic "Interactive User" placeholder.
            if getattr(record, "username", None):
                config.account_name = record.username
        else:
            credential.get_token(scope)

        # Save the configuration after successful authentication.
        manager.save_credential(config)

        click.echo()
        click.echo(f"✅ Successfully authenticated to {environment} cloud")
        click.echo(f"   Method: {config.method.value}")
        if config.account_name:
            click.echo(f"   Account: {config.account_name}")
        click.echo()
        click.echo("Credentials saved. Future commands will use this authentication automatically.")

    except Exception as e:
        click.echo()
        click.echo(f"❌ Authentication failed: {e}", err=True)
        sys.exit(1)


@auth.command("logout")
def cmd_auth_logout() -> None:
    """Log out and clear stored credentials."""
    from pql_test.auth import AuthenticationManager

    manager = AuthenticationManager()

    status = manager.get_status()
    if not status.authenticated:
        click.echo("Not currently authenticated.")
        return

    manager.clear_credential()
    click.echo("✅ Successfully logged out")
    click.echo("   Stored credentials have been cleared.")


@auth.command("status")
def cmd_auth_status() -> None:
    """Show current authentication status."""
    from pql_test.auth import AuthenticationManager

    manager = AuthenticationManager()
    status = manager.get_status()

    if not status.authenticated:
        click.echo("Status: Not authenticated")
        click.echo("\nTo log in, run: pql-test auth login")
        return

    click.echo("Status: Authenticated")
    click.echo(f"  Method: {status.method.value if status.method else 'Unknown'}")
    if status.account_name:
        click.echo(f"  Account: {status.account_name}")
    if status.tenant_id:
        click.echo(f"  Tenant: {status.tenant_id}")
    if status.client_id:
        click.echo(f"  Client ID: {status.client_id}")
    click.echo(f"  Environment: {status.environment}")


# ---------------------------------------------------------------------------
# skill helpers
# ---------------------------------------------------------------------------

def _get_harness_paths() -> dict[str, Path]:
    """Return the target paths for each harness."""
    return {
        'claude': Path('.claude/skills/pql-test'),
        'copilot': Path('.github'),  # Copilot uses copilot-instructions.md
        'cursor': Path('.cursor/skills/pql-test'),
        'windsurf': Path('.windsurf/skills/pql-test'),
    }


def _install_skills(harness: str | None, install_all: bool, dry_run: bool, force: bool = False) -> None:
    """Install skills to specified harness(es)."""
    import re as _re

    from pql_test.skills_resolver import list_available_skills
    
    harnesses = _get_harness_paths()
    valid_harnesses = list(harnesses.keys())
    
    # Validate harness name if specified
    if harness and harness not in valid_harnesses:
        click.echo(f"Error: Unknown harness '{harness}'", err=True)
        click.echo(f"Valid harnesses: {', '.join(valid_harnesses)}", err=True)
        sys.exit(1)
    
    # Determine which harnesses to install to
    if install_all:
        targets = valid_harnesses
    elif harness:
        targets = [harness]
    else:
        click.echo("Error: Must specify --install HARNESS or --all", err=True)
        sys.exit(1)
    
    skills = list_available_skills()
    created_count = 0
    updated_count = 0
    unchanged_count = 0
    preserved_count = 0

    marker_regex = _re.compile(r"<!--\s*Installed by pql-test skill v([0-9][0-9A-Za-z.\-]*)\s*-->")

    def _write_decision(target_file: Path, new_content: str) -> str:
        """Return one of 'create', 'update', 'unchanged', 'preserve-customized', 'preserve-unmanaged'."""
        if not target_file.exists():
            return "create"
        existing = target_file.read_text(encoding="utf-8")
        if existing == new_content:
            return "unchanged"
        if force:
            return "update"
        m = marker_regex.search(existing)
        if m is None:
            return "preserve-unmanaged"
        if m.group(1) == _VERSION:
            return "preserve-customized"
        return "update"

    for target_harness in targets:
        target_path = harnesses[target_harness]
        
        if target_harness == 'copilot':
            # Copilot uses a single copilot-instructions.md file
            instructions_file = target_path / 'copilot-instructions.md'
            content = _generate_copilot_instructions(skills)
            decision = _write_decision(instructions_file, content)
            
            if dry_run:
                if decision == "create":
                    click.echo(f"Would create: {instructions_file}")
                    created_count += 1
                elif decision == "update":
                    click.echo(f"Would update: {instructions_file}")
                    updated_count += 1
                elif decision == "unchanged":
                    click.echo(f"Unchanged: {instructions_file}")
                    unchanged_count += 1
                else:
                    click.echo(f"Would preserve: {instructions_file} (use --force to overwrite)")
                    preserved_count += 1
            else:
                if decision in ("create", "update"):
                    instructions_file.parent.mkdir(parents=True, exist_ok=True)
                    instructions_file.write_text(content, encoding='utf-8')
                if decision == "create":
                    click.echo(f"Created: {instructions_file}")
                    created_count += 1
                elif decision == "update":
                    click.echo(f"Updated: {instructions_file}")
                    updated_count += 1
                elif decision == "unchanged":
                    click.echo(f"Unchanged: {instructions_file}")
                    unchanged_count += 1
                elif decision == "preserve-customized":
                    click.echo(
                        f"Preserved (customized, v{_VERSION} marker present): {instructions_file} "
                        f"— use --force to overwrite"
                    )
                    preserved_count += 1
                else:  # preserve-unmanaged
                    click.echo(
                        f"Preserved (no pql-test marker found): {instructions_file} "
                        f"— use --force to overwrite"
                    )
                    preserved_count += 1
        else:
            # Claude, Cursor, Windsurf use skill directories
            for skill in skills:
                from pql_test.skills_resolver import resolve_skill_dir
                skill_dir = resolve_skill_dir(skill['name'])
                skill_md = skill_dir / 'SKILL.md'
                
                target_skill_dir = target_path / skill['name']
                target_skill_file = target_skill_dir / 'SKILL.md'
                
                content = skill_md.read_text(encoding='utf-8')
                # Add installation marker
                marker = f"<!-- Installed by pql-test skill v{_VERSION} -->\n"
                if not content.startswith('<!--'):
                    content = marker + content
                elif 'Installed by pql-test skill' not in content:
                    # Insert marker after existing frontmatter comment
                    lines = content.split('\n')
                    insert_idx = 0
                    for i, line in enumerate(lines):
                        if line.strip().endswith('-->'):
                            insert_idx = i + 1
                            break
                    lines.insert(insert_idx, marker.rstrip())
                    content = '\n'.join(lines)
                
                decision = _write_decision(target_skill_file, content)

                if dry_run:
                    if decision == "create":
                        click.echo(f"Would create: {target_skill_file}")
                        created_count += 1
                    elif decision == "update":
                        click.echo(f"Would update: {target_skill_file}")
                        updated_count += 1
                    elif decision == "unchanged":
                        unchanged_count += 1
                    else:
                        click.echo(f"Would preserve: {target_skill_file} (use --force to overwrite)")
                        preserved_count += 1
                else:
                    if decision in ("create", "update"):
                        target_skill_dir.mkdir(parents=True, exist_ok=True)
                        target_skill_file.write_text(content, encoding='utf-8')
                    if decision == "create":
                        click.echo(f"Created: {target_skill_file}")
                        created_count += 1
                    elif decision == "update":
                        click.echo(f"Updated: {target_skill_file}")
                        updated_count += 1
                    elif decision == "unchanged":
                        unchanged_count += 1
                    elif decision == "preserve-customized":
                        click.echo(
                            f"Preserved (customized, v{_VERSION} marker present): {target_skill_file} "
                            f"— use --force to overwrite"
                        )
                        preserved_count += 1
                    else:  # preserve-unmanaged
                        click.echo(
                            f"Preserved (no pql-test marker found): {target_skill_file} "
                            f"— use --force to overwrite"
                        )
                        preserved_count += 1
    
    # Summary
    if dry_run:
        click.echo(
            f"\nDry run summary: {created_count} would be created, "
            f"{updated_count} would be updated, {preserved_count} would be preserved"
        )
    else:
        click.echo(
            f"\nInstallation complete: {created_count} created, {updated_count} updated, "
            f"{unchanged_count} unchanged, {preserved_count} preserved"
        )


def _generate_copilot_instructions(skills: list[dict[str, str]]) -> str:
    """Generate copilot-instructions.md content from skills."""
    lines = [
        f"<!-- Installed by pql-test skill v{_VERSION} -->",
        "",
        "# pql-test Skills",
        "",
        "This workspace has pql-test skills installed for DAX testing with Power BI semantic models.",
        "",
        "## Available Skills",
        "",
    ]
    
    for skill in skills:
        lines.append(f"### {skill['name']}")
        lines.append(f"{skill['description']}")
        lines.append("")
    
    lines.extend([
        "## Usage",
        "",
        "Use these skills when working with:",
        "- Power BI semantic model testing",
        "- DAX query execution",
        "- PBIP project structure",
        "- XMLA endpoint connections",
        "",
        "Run `pql-test --help` for CLI documentation.",
    ])
    
    return '\n'.join(lines)


def _show_install_status() -> None:
    """Show installation status for all harnesses."""
    from pql_test.skills_resolver import list_available_skills
    
    harnesses = _get_harness_paths()
    skills = list_available_skills()
    
    click.echo("Installation status:\n")
    
    for harness_name, harness_path in harnesses.items():
        if harness_name == 'copilot':
            instructions_file = harness_path / 'copilot-instructions.md'
            if instructions_file.exists():
                content = instructions_file.read_text(encoding='utf-8')
                version = _extract_version_from_marker(content)
                status = "✅ installed" if version else "⚠️  installed (no version marker)"
                if version and version != _VERSION:
                    status += f" (version mismatch: {version} vs {_VERSION})"
                click.echo(f"  {harness_name:<12} {status}")
            else:
                click.echo(f"  {harness_name:<12} ❌ not installed")
        else:
            # Check if any skills are installed
            installed_skills = 0
            mismatched = False
            for skill in skills:
                skill_file = harness_path / skill['name'] / 'SKILL.md'
                if skill_file.exists():
                    installed_skills += 1
                    content = skill_file.read_text(encoding='utf-8')
                    version = _extract_version_from_marker(content)
                    if version and version != _VERSION:
                        mismatched = True
            
            if installed_skills == len(skills):
                status = "✅ installed"
                if mismatched:
                    status += " (version mismatch detected)"
                click.echo(f"  {harness_name:<12} {status}")
            elif installed_skills > 0:
                click.echo(f"  {harness_name:<12} ⚠️  partially installed ({installed_skills}/{len(skills)} skills)")
            else:
                click.echo(f"  {harness_name:<12} ❌ not installed")


def _uninstall_skills(dry_run: bool) -> None:
    """Uninstall all pql-test skills."""
    harnesses = _get_harness_paths()
    removed_count = 0
    
    for harness_name, harness_path in harnesses.items():
        if harness_name == 'copilot':
            instructions_file = harness_path / 'copilot-instructions.md'
            if instructions_file.exists():
                content = instructions_file.read_text(encoding='utf-8')
                if 'Installed by pql-test skill' in content:
                    if dry_run:
                        click.echo(f"Would remove: {instructions_file}")
                        removed_count += 1
                    else:
                        instructions_file.unlink()
                        click.echo(f"Removed: {instructions_file}")
                        removed_count += 1
        else:
            if harness_path.exists():
                for skill_dir in harness_path.iterdir():
                    if skill_dir.is_dir():
                        skill_file = skill_dir / 'SKILL.md'
                        if skill_file.exists():
                            content = skill_file.read_text(encoding='utf-8')
                            if 'Installed by pql-test skill' in content:
                                if dry_run:
                                    click.echo(f"Would remove: {skill_file}")
                                    removed_count += 1
                                else:
                                    skill_file.unlink()
                                    click.echo(f"Removed: {skill_file}")
                                    removed_count += 1
                                    # Remove empty directories
                                    if not any(skill_dir.iterdir()):
                                        skill_dir.rmdir()
                # Remove pql-test directory if empty
                if harness_path.exists() and not any(harness_path.iterdir()) and not dry_run:
                    harness_path.rmdir()
    
    if dry_run:
        click.echo(f"\nDry run summary: {removed_count} files would be removed")
    else:
        if removed_count > 0:
            click.echo(f"\nUninstallation complete: {removed_count} files removed")
        else:
            click.echo("\nNo pql-test skills found to uninstall")


def _extract_version_from_marker(content: str) -> str | None:
    """Extract version from installation marker comment."""
    import re
    match = re.search(r'Installed by pql-test skill v([\d.]+)', content)
    return match.group(1) if match else None


# ---------------------------------------------------------------------------
# skill
# ---------------------------------------------------------------------------

@cli.command("skill")
@click.argument("name", required=False)
@click.option("--format", type=click.Choice(['text', 'json']), default='text', help="Output format (text or json)")
@click.option("--list", is_flag=True, help="List skill names only (one per line)")
@click.option("--version", is_flag=True, help="Print package version")
@click.option("--install", metavar="HARNESS", help="Install skills to specified harness (claude, copilot, cursor, windsurf)")
@click.option("--all", "install_all", is_flag=True, help="Install to all harnesses")
@click.option("--show", is_flag=True, help="Show installation status for all harnesses")
@click.option("--uninstall", is_flag=True, help="Uninstall all pql-test skills")
@click.option("--dry-run", is_flag=True, help="Show what would be installed/uninstalled without making changes")
@click.option(
    "--force",
    is_flag=True,
    help=(
        "Overwrite skill files even if the installed marker version matches the "
        "current package (useful after a manual customization you want to discard)."
    ),
)
def cmd_skill(name: str | None, format: str, list: bool, version: bool, 
              install: str | None, install_all: bool, show: bool, uninstall: bool,
              dry_run: bool, force: bool) -> None:
    """Manage pql-test skill files.
    
    With no arguments, lists all available skills with descriptions.
    With a NAME argument, prints that skill's content.
    With --install HARNESS, installs skills to the specified harness.
    With --show, displays installation status across all harnesses.
    With --uninstall, removes all installed pql-test skills.
    """
    from pql_test.skills_resolver import list_available_skills, resolve_skill_dir
    
    if version:
        click.echo(_VERSION)
        return
    
    # Handle --show
    if show:
        _show_install_status()
        return
    
    # Handle --uninstall
    if uninstall:
        _uninstall_skills(dry_run)
        return
    
    # Handle --install
    if install or install_all:
        _install_skills(install if install else None, install_all, dry_run, force)
        return
    
    if list:
        skills = list_available_skills()
        for skill in skills:
            click.echo(skill['name'])
        return
    
    if name is None:
        # List all skills with descriptions
        skills = list_available_skills()
        if not skills:
            click.echo("No skills found.")
            return
        
        click.echo("Available pql-test skills:\n")
        for skill in skills:
            click.echo(f"  {skill['name']:<20} {skill['description']}")
            if skill['source'] == 'local':
                click.echo(f"{' ' * 22}(local override)")
        return
    
    # Print specific skill
    try:
        skill_dir = resolve_skill_dir(name)
        skill_md = skill_dir / "SKILL.md"
        content = skill_md.read_text(encoding='utf-8')
        
        if format == 'json':
            metadata = {'name': name, 'version': 'unknown'}
            try:
                metadata['version'] = _pkg_version('pql-test')
            except Exception:
                # Fall back to the skill file's frontmatter when package metadata is unavailable.
                import re
                frontmatter_match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
                if frontmatter_match:
                    frontmatter = frontmatter_match.group(1)
                    ver_match = re.search(r'^version:\s*(.+)$', frontmatter, re.MULTILINE)
                    if ver_match:
                        metadata['version'] = ver_match.group(1).strip()

            metadata['content'] = content
            metadata['source_path'] = str(skill_dir)
            click.echo(json.dumps(metadata, indent=2))
        else:
            click.echo(content)
            
    except FileNotFoundError as e:
        click.echo(str(e), err=True)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Plugins (pql_test.commands entry points, e.g. `contract` from pql-odcs)
# ---------------------------------------------------------------------------

load_plugins(cli)
attach_contract_run(
    cli,
    RunHooks(
        conn_options=conn_options,
        make_conn_opts=_make_conn_opts,
        print_results=_print_results,
        print_azuredevops=_print_results_azuredevops,
        print_github=_print_results_github,
        suite_to_dict=_suite_to_dict,
    ),
)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    # Windows default codepage (cp1252) can't encode the ✅ / ❌ status markers
    # we emit. Force UTF-8 so the CLI works in a default PowerShell session.
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            reconfigure = getattr(stream, "reconfigure", None)
            if reconfigure is not None:
                reconfigure(encoding="utf-8", errors="replace")
    cli()


if __name__ == "__main__":
    main()
