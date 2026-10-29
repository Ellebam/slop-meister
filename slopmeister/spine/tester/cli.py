"""Launch one isolated opposite-tool tester and collect its persisted evidence."""

import argparse
from collections.abc import Sequence
from pathlib import Path
import subprocess
import sys

from slopmeister.review.redact import redact
from slopmeister.spine.tester.collect import collect
from slopmeister.spine.tester.launch import launch
from slopmeister.spine.tester.supervise import supervise
from slopmeister.spine.tester.validate import check_draft

MAX_WAIT_SECONDS = 300


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="slopmeister tester", description=__doc__)
    sub = result.add_subparsers(dest="command", required=True)
    start = sub.add_parser("launch")
    start.add_argument("--worker-tool", choices=["claude", "codex", "opencode"], required=True)
    start.add_argument(
        "--tester-tool",
        choices=["claude", "codex", "opencode"],
        help="Explicit tester tool, default is the opposite of the worker tool.",
    )
    start.add_argument("--tester-model", help="provider/model for the opencode tester only.")
    for field in ("task", "guide", "validation"):
        start.add_argument(f"--{field}", required=True)
    start.add_argument("--cwd")
    start.add_argument("--commit")
    start.add_argument("--candidate", action="store_true")
    start.add_argument("--subject-manifest")
    start.add_argument("--slot-target")
    for command in ("collect", "_supervise", "validate"):
        child = sub.add_parser(command)
        child.add_argument("--run", type=Path, required=True)
        if command == "collect":
            child.add_argument("--wait-seconds", type=float, default=0)
        elif command == "validate":
            child.add_argument("--draft", type=Path, required=True)
    return result


def main(argv: Sequence[str]) -> int:
    args = parser().parse_args(argv)
    try:
        return run(args)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        label = "INVALID DRAFT" if args.command == "validate" else "BLOCKED"
        print(f"{label}: {redact(str(error))}", file=sys.stderr)
        return 1


def run(args: argparse.Namespace) -> int:
    if args.command == "launch":
        root = launch(args)
        print(root)
        return collect(root, 0) if (root / "result.json").exists() else 0
    if args.command == "_supervise":
        return supervise(args.run.resolve())
    if args.command == "validate":
        outcome = check_draft(args.run.resolve(), args.draft.resolve())
        print(f"VALID DRAFT (outcome: {outcome}; not test proof)")
        return 0
    if not 0 <= args.wait_seconds <= MAX_WAIT_SECONDS:
        raise ValueError(f"collection wait must be between 0 and {MAX_WAIT_SECONDS} seconds")
    return collect(args.run.resolve(), args.wait_seconds)
