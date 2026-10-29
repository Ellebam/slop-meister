"""Command-line interface for fixed session configuration installation."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import sys

from slopmeister.install.models import InstallRequest
from slopmeister.install.preflight import reject_git_context
from slopmeister.install.prepare import prepare


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare and validate the fixed Slopmeister configuration used by every "
            "launcher entry point."
        )
    )
    actions = parser.add_mutually_exclusive_group(required=True)
    for name in ("preflight", "prepare", "directory", "check"):
        actions.add_argument("--" + name, dest="action", action="store_const", const="--" + name)
    parser.add_argument("target")
    parser.add_argument("workspace")
    parser.add_argument("allocation", nargs="?")
    parser.add_argument("--grant", action="append", default=[])
    parser.add_argument("--dispatcher-jira", action="store_true")
    parser.add_argument("--manager", action="store_true")
    return parser


def main(argv: Sequence[str]) -> int:
    try:
        reject_git_context()
        args = _parser().parse_args(argv)
        request = InstallRequest(
            args.action,
            args.target,
            args.workspace,
            args.allocation,
            args.grant,
            args.dispatcher_jira,
            args.manager,
        )
        prepare(request)
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(
            "config-install: "
            + str(error)
            + "; preserve this workspace and report the refusal to the operator",
            file=sys.stderr,
        )
        return 1
