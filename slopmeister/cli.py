"""Command registry. Each command lives in its own module with a main(argv) function.

This module must import under an older python3, so the floor check below can speak.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
import importlib
import sys

from slopmeister.errors import EXIT_USAGE, SlopmeisterError

PYTHON_FLOOR = (3, 14)

COMMANDS: dict[str, tuple[str, str]] = {
    "candidate": ("slopmeister.spine.candidate_cli", "freeze or inspect repository state"),
    "check": ("slopmeister.check.cli", "the deterministic gate, every check once with its layer"),
    "claims": ("slopmeister.claims.cli", "manage GitHub issue ownership"),
    "dispatch": ("slopmeister.dispatch.cli", "open a standing dispatcher"),
    "install": ("slopmeister.install.cli", "prepare and validate fixed session configuration"),
    "kickoff": (
        "slopmeister.workstation.kickoff",
        "decide whether a kickoff adheres to its contract",
    ),
    "occupants": ("slopmeister.threads.occupants", "list the workers occupying a worktree"),
    "plot-session": ("slopmeister.launch.cli", "launch or recover a worker session"),
    "plots": ("slopmeister.plots.query", "look up or declare a plot"),
    "quality": (
        "slopmeister.quality.cli",
        "budgets, imports, the allowlist, field identifiers and plot style",
    ),
    "render": ("slopmeister.render.build", "render src and plots into dist"),
    "sandbox": ("slopmeister.sandbox.cli", "the opt-in local Jira and Confluence sandbox"),
    "secret-ask": (
        "slopmeister.secret_ask.cli",
        "request approval for an installed secret workflow",
    ),
    "review": ("slopmeister.review.cli", "run, replay or replace one cross-tool review"),
    "slots": ("slopmeister.slots.cli", "allocate, inspect and release target slots"),
    "spine-timing": (
        "slopmeister.threads.timing.cli",
        "where spine worker sessions spent their time",
    ),
    "startup-context": ("slopmeister.threads.startup_context", "a transcript's startup context"),
    "tester": ("slopmeister.spine.tester.cli", "launch or collect one opposite-tool tester"),
    "vault": ("slopmeister.vault.runtime", "initialize, lint and write vault history"),
    "workstation": ("slopmeister.workstation.cli", "diagnose, compare and install this machine"),
    "workspace-remove": ("slopmeister.workspace_removal", "remove one retired workspace safely"),
}


def usage() -> str:
    rows = [f"  {name:<12} {summary}" for name, (_, summary) in sorted(COMMANDS.items())]
    return "usage: slopmeister <command> [args]\n\n" + "\n".join(rows) + "\n"


def resolve(name: str) -> Callable[[Sequence[str]], int]:
    module_name, _ = COMMANDS[name]
    return importlib.import_module(module_name).main


def python_problem(version: tuple[int, ...]) -> str | None:
    """On a new Mac python3 is the system's older one, and no command module would even import."""
    if tuple(version[:2]) < PYTHON_FLOOR:
        return "Python 3.14 or newer is required, python3 here is " + ".".join(
            map(str, version[:3])
        )
    return None


def main(argv: Sequence[str]) -> int:
    problem = python_problem(tuple(sys.version_info))
    if problem:
        sys.stderr.write(f"slopmeister: {problem}\n")
        return EXIT_USAGE
    if not argv or argv[0] in ("-h", "--help") or argv[0] not in COMMANDS:
        sys.stderr.write(usage())
        return 0 if argv and argv[0] in ("-h", "--help") else EXIT_USAGE
    try:
        return resolve(argv[0])(argv[1:])
    except SlopmeisterError as error:
        sys.stderr.write(f"slopmeister {argv[0]}: {error}\n")
        return error.exit_code
