"""Plot declaration queries and their command-line interface."""

import argparse
from collections.abc import Sequence
from pathlib import Path
import sys

from slopmeister.paths import plot_declarations
from slopmeister.plots.declaration import NAME, fail, load_all, safe, slot_rows
from slopmeister.plots.declare import declare


def list_rows(directory: Path) -> list[str]:
    declarations = load_all(directory)
    rows = []
    for plot in sorted(path for path in directory.iterdir() if path.is_dir()):
        if plot.name.startswith("."):
            continue
        name, data = plot.name, declarations.get(plot.name, {})
        if "target" not in data:
            rows.append(f"{name}\ttemplate\t-\t-")
            continue
        target = data["target"]
        repository = target.get("repository", {})
        rows.append(
            "\t".join(
                (
                    name,
                    "inject" if repository else "-",
                    target["tasks"],
                    repository.get("commit", "-"),
                )
            )
        )
    return rows


def query(directory: Path, name: str, option: str | None) -> str:
    data = load_all(directory).get(name)
    path = directory / name / "plot.toml"
    if data is None or "target" not in data:
        fail(path, "target", "no launchable plot declared; use task plot -- --declare <name>")
    target = data["target"]
    repository = target.get("repository", {})
    if option == "slots":
        if not repository:
            fail(path, "slots", "requires target.repository")
        return "\n".join(slot_rows(data))
    values = {
        "shipping": repository.get("shipping", "deny"),
        "tasks": target["tasks"],
        "commit": repository.get("commit", "-"),
        None: "inject" if repository else "-",
    }
    return values[option]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="slopmeister plots")
    group = parser.add_mutually_exclusive_group()
    for option in ("tasks", "commit", "shipping", "slots", "list", "declare"):
        group.add_argument("--" + option, action="store_true")
    parser.add_argument("name", nargs="?")
    return parser


def _selected(args: argparse.Namespace) -> str | None:
    names = ("tasks", "commit", "shipping", "slots")
    return next((name for name in names if getattr(args, name)), None)


def _report(error: Exception, path: Path) -> int:
    message = str(error)
    if isinstance(error, EOFError):
        message = f"{safe(path)}: <document>.<confirmation>: input ended, nothing declared"
    elif isinstance(error, OSError):
        message = f"{safe(path)}: <document>.<path>: {safe(error.strerror)}"
    print(message, file=sys.stderr)
    return 1


def main(argv: Sequence[str]) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.list == bool(args.name):
        parser.error("use --list alone, or provide one plot name")
    directory = plot_declarations()
    path = directory / (args.name or "") / "plot.toml"
    try:
        if args.name and not NAME.fullmatch(args.name):
            fail(path, "<document>.<name>", "plot name must match [a-z0-9][a-z0-9-]*")
        if args.list:
            output = "\n".join(list_rows(directory))
        elif args.declare:
            output = declare(directory, args.name)
        else:
            output = query(directory, args.name, _selected(args))
        print(output)
        return 0
    except (ValueError, EOFError, OSError) as error:
        return _report(error, path)
