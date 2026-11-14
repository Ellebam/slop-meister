"""Freeze, inspect or verify the current repository candidate."""

import argparse
from collections.abc import Sequence
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys

from slopmeister.session import launch_identity, repositories
from slopmeister.spine import candidate


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    for name in ("freeze", "status"):
        command = commands.add_parser(name)
        command.add_argument("--cwd", type=Path, default=Path.cwd())
    verify = commands.add_parser("verify-commit")
    verify.add_argument("--cwd", type=Path, default=Path.cwd())
    verify.add_argument("--commit", required=True)
    return result


def run(args: argparse.Namespace) -> dict:
    cwd = args.cwd.resolve(strict=True)
    selected = cwd
    if args.command == "verify-commit" and repositories.state_path(cwd).exists():
        cwd = Path(repositories.read(cwd).get("session", cwd))
        if selected not in repositories.workspaces(cwd):
            raise ValueError(f"repository is not a member of this session: {selected}")
    task = launch_identity.read(cwd)["task"]
    frozen = candidate.freeze(cwd, task) if args.command == "freeze" else candidate.load(cwd, task)
    value = {
        key: str(item) if isinstance(item, Path) else item for key, item in asdict(frozen).items()
    }
    value["identity"] = frozen.identity
    if args.command == "verify-commit":
        value["commit"] = candidate.verify_commit(frozen, args.commit, workspace=selected)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    try:
        print(json.dumps(run(parser().parse_args(argv)), sort_keys=True, default=str))
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(f"BLOCKED: {error}", file=sys.stderr)
        return 1
