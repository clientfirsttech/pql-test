"""Entry point for the pql-test CLI."""

import argparse
import sys

from pql_test import __version__
from pql_test.commands.auth import add_auth_parser, handle_auth


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="pql-test",
        description="CLI to run Fabric artifact testing.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"pql-test {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command")
    add_auth_parser(subparsers)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Main entry point for the CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "auth":
        return handle_auth(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
