"""`slopmeister workstation doctor|diff|drift|install|glab-login`, this machine's setup."""

import argparse
from collections.abc import Sequence
from dataclasses import asdict
import difflib
import json
from pathlib import Path

from slopmeister.errors import EXIT_USAGE
from slopmeister.workstation import (
    codex_config,
    doctor,
    drift,
    glab_login,
    install,
    manifest,
    op_setup,
    orca,
    rules,
    state,
)


def _change(item: state.Item, home: Path) -> str:
    if item.name in (manifest.CODEX_CONFIG, orca.NAME):
        change = codex_config.change if item.name == manifest.CODEX_CONFIG else orca.change
        return change(home)
    if item.entry is None:
        return f"  would build: {item.name} (osacompile)"
    live = home / item.name
    if not live.is_file():
        return f"--- {item.name} ---\n  (new file)"
    expected = item.entry.expected(home).decode(errors="replace").splitlines(keepends=True)
    current = live.read_text(errors="replace").splitlines(keepends=True)
    lines = difflib.unified_diff(current, expected, f"~/{item.name}", item.entry.source)
    return f"--- {item.name} ---\n" + "".join(lines).rstrip("\n")


def _diff(home: Path) -> int:
    """Show what install would change against the live files, write nothing."""
    pending = state.pending(home)
    for item in state.items(home):
        print(state.skipped(item) or _change(item, home))
    print("=== allow rules, reported by status only, edited by the operator ===")
    print("\n".join(rules.report(home)))
    print(f"\n{len(pending)} file(s) differ. Nothing written.")
    return 0


def _install(home: Path, names: list[str], everything: bool) -> int:
    if not names and not everything:
        print("name the entries to install, or pass --all:")
        print("\n".join(f"  {item.status}: {item.name}" for item in state.pending(home)))
        return EXIT_USAGE
    chosen = set(manifest.names()) if everything else install.select(names)
    install.install(home, chosen)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="slopmeister workstation")
    commands = parser.add_subparsers(dest="command", required=True)
    report = commands.add_parser("doctor", help="one JSON result per requirement, write nothing")
    report.add_argument("--vault")
    commands.add_parser("diff", help="show what install would change, write nothing")
    check = commands.add_parser(
        "drift", help="home notices in linked worktrees, exit 1 on other drift"
    )
    check.add_argument("vault", nargs="?", help="accepted from the check runner and unused")
    setup = commands.add_parser("install", help="write the named entries, backups kept")
    setup.add_argument("names", nargs="*")
    setup.add_argument("--all", action="store_true", dest="everything")
    commands.add_parser("glab-login", help="sign glab in from the environment op run fills")
    tokens = commands.add_parser("op-setup", help="install the session op's tokens or its route")
    tokens.add_argument("part", choices=("tokens", "approval"))
    return parser


def _doctor(home: Path, args: argparse.Namespace) -> int:
    print(json.dumps([asdict(found) for found in doctor.doctor(home, args.vault)], indent=1))
    return 0


COMMANDS = {
    "doctor": _doctor,
    "diff": lambda home, args: _diff(home),
    "drift": lambda home, args: drift.drift(home),
    "install": lambda home, args: _install(home, args.names, args.everything),
    "glab-login": lambda home, args: glab_login.login(),
    "op-setup": lambda home, args: op_setup.setup(args.part),
}


def main(argv: Sequence[str]) -> int:
    args = _parser().parse_args(argv)
    return COMMANDS[args.command](Path.home(), args)
