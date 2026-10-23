"""Argument parsing for the installed vault runtime."""

import argparse
from collections import Counter
from collections.abc import Sequence
import re
import sys

from . import conflicts, lint, obsidian, repository, retro, retro_legacy


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="slopmeister-vault")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="create or restore the external bare repository")
    init.add_argument("--from-bundle", type=str)
    init.add_argument("vault", nargs="?")
    lint_parser = commands.add_parser("lint", help="check the vault or one area")
    lint_parser.add_argument("--area")
    lint_parser.add_argument("--shallow", action="store_true", help="skip the area's subfolders")
    retro_parser = commands.add_parser("retro", help="write and commit one new retro file")
    for name in ("repo", "task", "title", "tool", "model"):
        retro_parser.add_argument(f"--{name}", required=True)
    retro_parser.add_argument(
        "--note", help="append to an existing legacy log and replay its spills"
    )
    commands.add_parser("retro-count", help="count retro files per repository")
    commands.add_parser("commit", help="commit only explicitly named vault paths")
    return parser


def repository_label(value: str) -> str:
    """Use the repository name for short names, owner/name, URLs and checkout paths."""
    value = value.strip().rstrip("/").casefold()
    value = value.split("/.worktrees/", 1)[0]
    return value.rsplit("/", 1)[-1].removesuffix(".git")


def counts() -> int:
    totals: Counter[str] = Counter()
    vault = repository.vault_path()
    directory = vault / retro.DIRECTORY
    try:
        if directory.is_symlink():
            raise OSError("retro directory must not be a symlink")
        for path in sorted(directory.glob("*.md")):
            if path.name in {"README.md", "_INDEX.md"} or conflicts.COPY.search(path.name):
                continue
            numbered = conflicts.NUMBERED.fullmatch(path.name)
            if numbered and path.with_name("".join(numbered.groups())).is_file():
                continue
            _, content = repository.note_bytes(str(path.relative_to(vault)), vault)
            labels = re.findall(
                r"^\| Repository \| Tool \| Model \|[^\n]*\n\|[-| ]+\n\| ([^|\n]+) \|",
                content.decode(),
                re.MULTILINE,
            )
            if len(labels) != 1:
                raise OSError(f"retro file must contain exactly one repository table: {path.name}")
            totals.update(repository_label(value) for value in labels)
    except (OSError, UnicodeError) as error:
        print(f"retro count unavailable: {error}", file=sys.stderr)
        return 1
    for label, count in sorted(totals.items()):
        print(f"{label}\t{count}")
    return 0


def run_retro(args: argparse.Namespace) -> int:
    if args.note is not None:
        return retro_legacy.run(args)
    if retro_legacy._owed():
        print(
            "legacy retro spills remain pending; recover them with an explicit --note "
            "call for their original target and RETRO_SPILL_DIR",
            file=sys.stderr,
        )
    return retro.run(args)


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
        "retro": lambda: run_retro(parsed),
        "retro-count": counts,
    }
    return commands[parsed.command]()


if __name__ == "__main__":
    raise SystemExit(main())
