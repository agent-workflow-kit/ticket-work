"""Command-line entry point for ticket-work."""

from __future__ import annotations

import argparse
import sys

from . import __version__

PROG = "ticket-work"
DESCRIPTION = (
    "Own the lifecycle of a worked ticket: claim, transition, launch an implement "
    "agent, link the PR, and follow it to done."
)
USAGE_ERROR = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=DESCRIPTION,
    )
    parser.add_argument("--version", action="version", version=f"{PROG} {__version__}")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON output")
    parser.add_subparsers(dest="command", metavar="<command>")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command: str | None = args.command
    if command is None:
        parser.print_help(sys.stderr)
        return USAGE_ERROR
    return 0
