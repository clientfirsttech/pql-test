#!/usr/bin/env python3
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
  - <workspace>.<model>         Legacy dot notation (deprecated — still
                                accepted, emits a one-line warning).

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
  pql-test retrieve-tests <modelPath> [--test <name>] [--verbose]
  pql-test retrieve-test  <modelPath> <name> [--verbose]
  pql-test run-tests      <modelPath> [--test <name>] [--verbose]
                           [--output <file>]
                           [--log-format {azuredevops,github}]
                           [--tenant-id <id>] [--workspace-id <id>]
                           [--dataset-id <id>] [--client-id <id>]
                           [--client-secret <secret>]

Environment variables (loaded from .env when python-dotenv is installed):
  PQL_TENANT_ID, PQL_WORKSPACE_ID, PQL_DATASET_ID,
  PQL_CLIENT_ID, PQL_CLIENT_SECRET, PQL_ENVIRONMENT
"""

from __future__ import annotations

import json
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

import click

from pql_test.runner import (
    HAS_MSAL,
    HAS_PSUTIL,
    HAS_PYADOMD,
    Environment,
    ModelIdentifier,
    PqlTest,
    TestSuite,
    XmlaConnectionOptions,
    get_pbi_files_opened,
    parse_model_identifier,
    resolve_local_xmla_connection_by_name,
    resolve_service_xmla_connection_by_name,
    resolve_xmla_connection,
    retrieve_test_by_name,
    retrieve_tests,
    run_tests_from_model,
)

from importlib.metadata import version as _pkg_version, PackageNotFoundError
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
            "ok": HAS_PYADOMD,
            "detail": (
                "pyadomd available"
                if HAS_PYADOMD
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


def _print_results(suite: TestSuite, verbose: bool, pre_warnings: list[str] | None = None) -> None:
    """Print test results in a pytest-style format."""
    width = 72

    def _sep(title: str = "", char: str = "=", fg: str | None = None) -> str:
        if not title:
            line = char * width
        else:
            inner = f" {title} "
            left = max(0, (width - len(inner)) // 2)
            right = max(0, width - left - len(inner))
            line = char * left + inner + char * right
        return click.style(line, fg=fg) if fg else line

    click.echo("\n" + _sep("test session starts"))
    click.echo(f"model: {suite.model_path}")
    click.echo("")

    failures = [r for r in suite.results if not r.passed and not r.skipped]
    skipped_results = [r for r in suite.results if r.skipped]

    # Always list every result by name with a PASS/FAIL/SKIP tag so the
    # user can see exactly which tests had which outcome without needing
    # --verbose.  --verbose additionally appends the per-assertion message
    # and duration to each line.
    for r in suite.results:
        if r.skipped:
            tag = click.style("SKIP", fg="yellow")
        elif r.passed:
            tag = click.style("PASS", fg="green")
        else:
            tag = click.style("FAIL", fg="red")
        line = f"  {tag} {r.test_name}"
        if verbose:
            if r.message:
                line += f" -- {r.message}"
            if r.duration_ms is not None:
                line += f" ({r.duration_ms:.0f}ms)"
        click.echo(line)
    if suite.results:
        click.echo("")

    if failures:
        click.echo(_sep("FAILURES", "-", fg="red"))
        for r in failures:
            click.echo(f"\n  {click.style('FAILED', fg='red')} {r.test_name}")
            click.echo(f"  {r.message}")
            if r.error:
                click.echo(f"  Error: {r.error}")
        click.echo("")

    # Collect all warnings: pre-run messages + skipped-test messages (deduplicated)
    warn_msgs: list[str] = list(pre_warnings or [])
    seen: set[str] = set(warn_msgs)
    for r in skipped_results:
        msg = r.message or r.test_name
        if msg not in seen:
            warn_msgs.append(msg)
            seen.add(msg)

    if warn_msgs:
        click.echo(_sep("warnings summary", "-", fg="yellow"))
        for msg in warn_msgs:
            click.echo(f"  {click.style('WARN', fg='yellow')} {msg}")
        click.echo("")

    # When discovery returned nothing, make it obvious instead of producing
    # a confusing "0 passed, 0 failed, 0 total" line that looks like success.
    # See tasks/surface-silent-test-discovery-failures-epic.md.
    if suite.total == 0:
        click.echo(_sep("No tests found.", fg="yellow"))
        click.echo(
            "  Possible causes:\n"
            "    • The model has no PQL.Assert tests defined.\n"
            "    • Your account doesn't have access to the workspace/model.\n"
            "    • PQL.Assert isn't installed in this model.\n"
            "    • The connection failed (check the warning above)."
        )
        click.echo(_sep("0 passed, 0 failed, 0 total", fg="yellow"))
        return

    summary = f"{suite.passed} passed, {suite.failed} failed, {suite.total} total"
    if suite.skipped:
        plural = "s" if suite.skipped != 1 else ""
        summary += f", {suite.skipped} warning{plural}"

    if suite.failed > 0:
        summary_color = "red"
    elif suite.skipped > 0:
        summary_color = "yellow"
    else:
        summary_color = "green"
    click.echo(_sep(summary, fg=summary_color))


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
    click.option(
        "--environment",
        "environment",
        envvar="PQL_ENVIRONMENT",
        default=Environment.PUBLIC.value,
        type=click.Choice([e.value for e in Environment], case_sensitive=False),
        help="Power BI cloud environment (or set PQL_ENVIRONMENT env var). Default: Public.",
    ),
]


def conn_options(func):
    """Decorator that attaches all XMLA connection options to a Click command."""
    for option in reversed(_conn_options_list):
        func = option(func)
    return func


def _format_local_miss_diagnostic(model_name: str) -> str:
    """Build a multi-line diagnostic when local/<model_name> doesn't resolve.

    Shows every Power BI Desktop instance the CLI could detect (with
    ``<unnamed>`` for instances whose window title couldn't be read — that
    happens with the Microsoft Store build whose process tree is ACL-locked).
    Also lists the common reasons a name lookup misses so the user can
    self-diagnose without having to re-run with --verbose.
    """
    lines: list[str] = [
        f"No matching Power BI Desktop instance found for model '{model_name}'.",
        "",
    ]
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
    environment: str | None = None,
) -> XmlaConnectionOptions:
    env = Environment(environment) if environment else Environment.PUBLIC
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
@conn_options
def cmd_retrieve_tests(
    model_path: str,
    test_name: str | None,
    human: bool,
    verbose: bool,
    tenant_id: str | None,
    workspace_id: str | None,
    dataset_id: str | None,
    client_id: str | None,
    client_secret: str | None,
    environment: str,
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
      <workspace>.<model>         Legacy dot notation (deprecated — still
                                  accepted, emits a one-line warning).

    Wrap MODEL_PATH in double quotes when the workspace or model name contains
    spaces or parentheses, e.g. "local/OLS_Model (1)" — otherwise the shell
    splits it into multiple arguments and the CLI never sees the full name.

    \b
    Examples:
      pql-test retrieve-tests ../examples
      pql-test retrieve-tests local/SampleModel
      pql-test retrieve-tests "MyWorkspace.Workspace/MySemanticModel.SemanticModel"
      pql-test retrieve-tests "MyWorkspace.Workspace/MySemanticModel.SemanticModel" --tenant-id ... --client-id ... --client-secret ...
    """
    ident = parse_model_identifier(model_path)
    opts = _make_conn_opts(tenant_id, workspace_id, dataset_id, client_id, client_secret, environment)

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
        test = retrieve_test_by_name(abs_path, test_name, connection=conn)
        if not test:
            if human:
                click.echo(f'No test found with name: "{test_name}"')
            else:
                click.echo(json.dumps(None))
            sys.exit(1)
        results = [test]
    else:
        results = retrieve_tests(abs_path, connection=conn)

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
    environment: str,
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
      <workspace>.<model>         Legacy dot notation (deprecated — still
                                  accepted, emits a one-line warning).

    Wrap MODEL_PATH in double quotes when the workspace or model name contains
    spaces or parentheses, e.g. "local/OLS_Model (1)" — otherwise the shell
    splits it into multiple arguments and the CLI never sees the full name.
    """
    ident = parse_model_identifier(model_path)
    opts = _make_conn_opts(tenant_id, workspace_id, dataset_id, client_id, client_secret, environment)

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
@conn_options
def cmd_run_tests(
    model_path: str,
    test_name: str | None,
    verbose: bool,
    output: str | None,
    log_format: str | None,
    tenant_id: str | None,
    workspace_id: str | None,
    dataset_id: str | None,
    client_id: str | None,
    client_secret: str | None,
    environment: str,
) -> None:
    """Run all DAX test suites in a PBIP model via XMLA.

    Results are printed in a pytest-style format by default.
    Use --output to also save full JSON results to a file.
    Use --log-format to emit CI-native annotations for Azure DevOps or
    GitHub Actions pipelines.

    MODEL_PATH accepts these formats:

    \b
      <workspace>.Workspace/<model>.SemanticModel
                                  Canonical Fabric service path — connect to
                                  a remote workspace by display names.
      local/<model_name>          Connect to a locally-open Power BI
                                  Desktop instance by model name.
      <filesystem_path>           Traditional PBIP root directory.
      <workspace>.<model>         Legacy dot notation (deprecated — still
                                  accepted, emits a one-line warning).

    Wrap MODEL_PATH in double quotes when the workspace or model name contains
    spaces or parentheses, e.g. "local/OLS_Model (1)" — otherwise the shell
    splits it into multiple arguments and the CLI never sees the full name.

    \b
    Examples:
      pql-test run-tests ../examples
      pql-test run-tests local/SampleModel
      pql-test run-tests "MyWorkspace.Workspace/MySemanticModel.SemanticModel"
      pql-test run-tests "MyWorkspace.Workspace/MySemanticModel.SemanticModel" --tenant-id ... --client-id ... --client-secret ...
      pql-test run-tests ../examples/SampleModel.SemanticModel --output results.json
      pql-test run-tests local/SampleModel --log-format github
    """
    ident = parse_model_identifier(model_path)
    opts = _make_conn_opts(tenant_id, workspace_id, dataset_id, client_id, client_secret, environment)

    pre_warnings: list[str] = []
    conn = None
    abs_path: str = ""

    if ident.kind == "local":
        # local/<model_name> — resolve local connection by name
        abs_path = f"local/{ident.model_name}"

        if verbose:
            try:
                instances = get_pbi_files_opened()
                if instances:
                    click.echo("\nDetected Power BI Desktop instances:")
                    for inst in instances:
                        name = inst.model_name or "<unnamed>"
                        click.echo(f"  \u2022 '{name}'  \u2192  {inst.server} / {inst.catalog}")
                else:
                    click.echo("\nNo Power BI Desktop instances detected.")
            except ImportError:
                click.echo("\npsutil not installed \u2014 local detection limited to port-file fallback.")

        conn = resolve_local_xmla_connection_by_name(ident.model_name)
        if conn:
            click.echo(f"\nLocal XMLA connection: {conn.server} / catalog: {conn.catalog}")
        else:
            diagnostic = _format_local_miss_diagnostic(ident.model_name)
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

    suite = run_tests_from_model(abs_path, test_name, opts, connection=conn, skip_message=skip_message)

    if log_format == "azuredevops":
        _print_results_azuredevops(suite, pre_warnings=pre_warnings)
    elif log_format == "github":
        _print_results_github(suite, pre_warnings=pre_warnings)
    else:
        _print_results(suite, verbose, pre_warnings=pre_warnings)

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
