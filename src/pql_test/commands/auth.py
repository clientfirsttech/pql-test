"""Auth command implementations for pql-test CLI.

Handles login, logout, and status subcommands for authentication.
Supports user (interactive), service principal, and managed identity flows.
"""

import argparse
import sys
from typing import Optional

from pql_test.core.auth import AuthError, PqlAuth


def add_auth_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'auth' command and its subcommands."""
    auth_parser = subparsers.add_parser(
        "auth",
        help="Authenticate with Microsoft Fabric.",
    )
    auth_subparsers = auth_parser.add_subparsers(
        dest="auth_command",
        help="Authentication commands",
    )

    # --- login ---
    login_parser = auth_subparsers.add_parser(
        "login",
        help="Sign in to a Fabric account.",
    )
    login_parser.add_argument(
        "-u", "--username",
        help="Client ID for service principal authentication.",
    )
    login_parser.add_argument(
        "-p", "--password",
        help="Client secret for service principal authentication.",
    )
    login_parser.add_argument(
        "-t", "--tenant",
        help="Tenant ID for authentication.",
    )
    login_parser.add_argument(
        "--identity",
        action="store_true",
        default=False,
        help="Use managed identity for authentication.",
    )

    # --- logout ---
    auth_subparsers.add_parser(
        "logout",
        help="Sign out and clear cached credentials.",
    )

    # --- status ---
    auth_subparsers.add_parser(
        "status",
        help="Display the current authentication status.",
    )


def handle_auth(args: argparse.Namespace, auth: Optional[PqlAuth] = None) -> int:
    """Dispatch auth subcommands. Returns exit code."""
    if auth is None:
        auth = PqlAuth()

    if args.auth_command == "login":
        return _handle_login(args, auth)
    elif args.auth_command == "logout":
        return _handle_logout(auth)
    elif args.auth_command == "status":
        return _handle_status(auth)
    else:
        print("Usage: pql-test auth {login,logout,status}", file=sys.stderr)
        return 1


def _handle_login(args: argparse.Namespace, auth: PqlAuth) -> int:
    """Handle the login subcommand."""
    try:
        if args.identity:
            # Managed identity authentication
            client_id = getattr(args, "username", None)
            result = auth.login_managed_identity(client_id=client_id)
            identity_label = "managed identity"
            if client_id:
                identity_label = f"user-assigned managed identity ({client_id})"
            print(f"Logged in with {identity_label}.")
            return 0

        if args.username and args.password:
            # Service principal authentication with secret
            tenant = args.tenant
            if not tenant:
                print(
                    "Error: --tenant/-t is required for service principal authentication.",
                    file=sys.stderr,
                )
                return 1
            auth.login_service_principal(
                client_id=args.username,
                client_secret=args.password,
                tenant=tenant,
            )
            print(f"Logged in as service principal ({args.username}).")
            return 0

        if args.username and not args.password:
            print(
                "Error: --password/-p is required when --username/-u is provided.",
                file=sys.stderr,
            )
            return 1

        # Interactive browser login (default)
        auth.login_user(tenant=args.tenant)
        print("Logged in with interactive browser authentication.")
        return 0

    except AuthError as e:
        print(f"Authentication error: {e.message}", file=sys.stderr)
        return 1


def _handle_logout(auth: PqlAuth) -> int:
    """Handle the logout subcommand."""
    auth.logout()
    print("Logged out successfully.")
    return 0


def _handle_status(auth: PqlAuth) -> int:
    """Handle the status subcommand."""
    status = auth.status()

    if not status["logged_in"]:
        print("Not logged in.")
        return 0

    print(f"Logged in: Yes")
    print(f"Identity type: {status['identity_type']}")
    if status.get("tenant_id"):
        print(f"Tenant ID: {status['tenant_id']}")
    if status.get("client_id"):
        print(f"Client ID: {status['client_id']}")
    return 0
