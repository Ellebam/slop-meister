"""Argument surface retained from the legacy issue claims command."""

import argparse
from collections.abc import Sequence
from pathlib import Path

from slopmeister.claims import github

ACTIONS = (
    "eligible",
    "association",
    "target",
    "lock-path",
    "lock",
    "preflight",
    "initialize",
    "bind",
    "confirm",
    "inspect",
    "backlog",
    "reconcile",
    "abandon-prepare",
    "abandon-complete",
    "close",
)
REPOSITORY_ACTIONS = {"target", "lock-path", "lock", "backlog", "preflight", "initialize"}


def parse(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GitHub claim labels backed by worker evidence.")
    parser.add_argument("action", choices=ACTIONS)
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--plot")
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--issue-id", type=github.issue_number)
    parser.add_argument("--lock-fd", type=int)
    parser.add_argument("--redispatch", action="store_true")
    parser.add_argument("--kickoff", type=Path)
    parser.add_argument("--tool", choices=("claude", "codex", "opencode"))
    parser.add_argument("--session")
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--pid", type=int)
    parser.add_argument("--handoff", type=Path)
    parser.add_argument("--reason", choices=("completed", "not-planned"), default="completed")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)
