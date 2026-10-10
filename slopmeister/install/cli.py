"""Command-line interface for fixed session configuration installation."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
from pathlib import Path
import sys

from slopmeister.install.models import InstallRequest
from slopmeister.install.preflight import refuse, reject_git_context
from slopmeister.install.prepare import prepare
from slopmeister.install.trust import TrustRequest, trust
from slopmeister.session.verify import verify_shipping


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
    return parser


def _trust(argv: Sequence[str]) -> int:
    if len(argv) != 5:
        refuse("invalid native trust operation")
    _, mode, tool, path, workspace = argv
    trust(TrustRequest(mode, Path(path), workspace), tool)
    return 0


def _delivered(argv: Sequence[str]) -> int | None:
    if list(argv) == ["--verify-shipping"]:
        state = json.loads((Path(__file__).resolve().parent / "state.json").read_text())
        verify_shipping(state)
        return 0
    return None


def main(argv: Sequence[str]) -> int:
    try:
        delivered = _delivered(argv)
        if delivered is not None:
            return delivered
        if argv[:1] == ["--trust"]:
            return _trust(argv)
        reject_git_context()
        args = _parser().parse_args(argv)
        request = InstallRequest(
            args.action,
            args.target,
            args.workspace,
            args.allocation,
            args.grant,
            args.dispatcher_jira,
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
