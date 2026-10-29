"""Argument parsing for the installed vault runtime."""

import argparse
from collections.abc import Sequence
import sys

from . import lint, obsidian, repository, retro_legacy


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="slopmeister-vault")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="create or restore the external bare repository")
    init.add_argument("--from-bundle", type=str)
    init.add_argument("vault", nargs="?")
    lint_parser = commands.add_parser("lint", help="check the vault or one area")
    lint_parser.add_argument("--area")
    lint_parser.add_argument("--shallow", action="store_true", help="skip the area's subfolders")
    retro_parser = commands.add_parser("retro", help="explicitly append to a legacy log")
    for name in ("repo", "task", "title", "tool", "model"):
        retro_parser.add_argument(f"--{name}", required=True)
    retro_parser.add_argument(
        "--note", required=True, help="append to an existing legacy log and replay its spills"
    )
    commands.add_parser("commit", help="commit only explicitly named vault paths")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "commit":
        return repository.commit_cli(args[1:])
    if args and args[0] == "obsidian":
        return obsidian.cli(args[1:])
    parser = _parser()
    parsed = parser.parse_args(args)
    commands = {
        "init": lambda: repository.init_cli(parsed.vault, parsed.from_bundle),
        "lint": lambda: lint.run(parsed.area, parsed.shallow),
        "retro": lambda: retro_legacy.run(parsed),
    }
    return commands[parsed.command]()


if __name__ == "__main__":
    raise SystemExit(main())
