"""Roll, clean, and add Obsidian Tasks in this vault."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
import re

TASK_DIR = "To-Do"
TASK_DIR_INDEX = "README.md"

TASK_DATE = re.compile(r"📅\s*(\d{4}-\d{2}-\d{2})")
DONE_DATE = re.compile(r"✅\s*(\d{4}-\d{2}-\d{2})")


@dataclass
class Result:
    field: str
    rolled: int = 0
    moved_done: int = 0
    added: list[str] = field(default_factory=list)
    changed: bool = False


def find_root(start: Path) -> Path:
    for path in [start, *start.parents]:
        if (path / "_system").is_dir() and (path / "To-Do").is_dir():
            return path
    raise SystemExit("Could not find vault root with _system/ and To-Do/.")


def task_files(root: Path) -> dict[str, Path]:
    # A run must never write through a link to a file outside the vault.
    return {
        path.stem.lower(): path
        for path in sorted((root / TASK_DIR).glob("*.md"))
        if path.name != TASK_DIR_INDEX and path.is_file() and path.resolve().is_relative_to(root)
    }


def section_bounds(lines: list[str], heading: str) -> tuple[int, int]:
    start = None
    for index, line in enumerate(lines):
        if line.strip() == heading:
            start = index
            break
    if start is None:
        raise ValueError(f"Missing section {heading}")
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break
    return start, end


def parse_add(add_text: str | None) -> dict[str, list[str]]:
    parsed: dict[str, list[str]] = {}
    if not add_text:
        return parsed
    for group in add_text.split(";"):
        if not group.strip():
            continue
        if ":" not in group:
            raise SystemExit(f"Invalid add group, expected 'field: task': {group}")
        field, tasks = group.split(":", 1)
        key = field.strip().lower()
        parsed.setdefault(key, [])
        parsed[key].extend(task.strip() for task in tasks.split(",") if task.strip())
    return parsed


def _done_date(block: list[str]) -> str:
    match = DONE_DATE.search(block[0]) or TASK_DATE.search(block[0])
    return match.group(1) if match else "0000-00-00"


def _roll_line(line: str, today: date, result: Result) -> str:
    if not line.startswith("- [ ]") or "🔁" in line:
        return line
    match = TASK_DATE.search(line)
    if match and date.fromisoformat(match.group(1)) < today:
        result.rolled += 1
        result.changed = True
        return TASK_DATE.sub(f"📅 {today.isoformat()}", line, count=1)
    return line


def _roll_active(
    active: list[str], today: date, result: Result
) -> tuple[list[str], list[list[str]]]:
    kept: list[str] = []
    moved: list[list[str]] = []
    in_finished = False
    for line in active:
        if line.startswith("- [x]"):
            moved.append([line])
            in_finished = True
            result.moved_done += 1
            result.changed = True
        elif in_finished and line.startswith((" ", "\t")):
            moved[-1].append(line)
        else:
            in_finished = False
            kept.append(_roll_line(line, today, result))
    return kept, moved


def _add_tasks(active: list[str], additions: list[str], *context) -> list[str]:
    today, result = context
    if not additions:
        return active
    insertion = [f"- [ ] {task} 📅 {today.isoformat()}" for task in additions]
    result.added = insertion
    result.changed = True
    while active and active[0] == "":
        active.pop(0)
    return insertion + ([""] if active else []) + active


def process_file(path: Path, field_name: str, *change) -> tuple[Result, str]:
    today, additions = change
    result = Result(field=field_name)
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines()
    trailing_newline = original.endswith("\n")

    active_start, active_end = section_bounds(lines, "## Active")
    done_start, done_end = section_bounds(lines, "## Done")
    if done_start < active_start:
        raise ValueError("## Done must come after ## Active")
    active = lines[active_start + 1 : active_end]
    done = lines[done_start + 1 : done_end]

    new_active, moved = _roll_active(active, today, result)
    new_active = _add_tasks(new_active, additions, today, result)

    # Existing Done lines keep their bytes, the moved blocks go in below the heading's blank lines.
    top = next((index for index, line in enumerate(done) if line), len(done))
    newest_first = sorted(moved, key=_done_date, reverse=True)
    done = done[:top] + [line for block in newest_first for line in block] + done[top:]

    rebuilt = lines[: active_start + 1] + new_active
    rebuilt += lines[active_end : done_start + 1] + done + lines[done_end:]
    suffix = "\n" if trailing_newline else ""
    return result, "\n".join(rebuilt) + suffix


def _arguments(argv: Sequence[str]):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--fields",
        nargs="+",
        help=f"Keys are the {TASK_DIR}/*.md file names. Default is every file.",
    )
    parser.add_argument("--add", help='Inline tasks, e.g. "self: Task one; personal: Task two"')
    parser.add_argument("--today", default=date.today().isoformat())
    parser.add_argument("--apply", action="store_true", help="Write changes. Default is dry-run.")
    return parser.parse_args(argv)


def _planned(files, fields, *change):
    today, additions = change
    planned = []
    for field_name in fields:
        path = files[field_name]
        try:
            processed = process_file(path, field_name, today, additions.get(field_name, []))
        except ValueError as error:
            raise SystemExit(f"{TASK_DIR}/{path.name}: {error}") from None
        planned.append((path, *processed))
    return planned


def _report(results, apply, today):
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"{mode}: vault todo maintenance for {today.isoformat()}")
    for result in results:
        print(
            f"- {result.field}: rolled={result.rolled}, "
            f"moved_done={result.moved_done}, added={len(result.added)}, changed={result.changed}"
        )
        for line in result.added:
            print(f"  + {line}")


def main(argv: Sequence[str]) -> int:
    args = _arguments(argv)

    root = find_root(Path(args.root).resolve())
    today = date.fromisoformat(args.today)
    additions = parse_add(args.add)
    files = task_files(root)
    fields = [key.lower() for key in args.fields or []] or sorted(additions) or list(files)
    unknown = sorted((set(fields) | set(additions)) - set(files))
    if unknown:
        raise SystemExit(f"Unknown field key: {', '.join(unknown)}. Available: {', '.join(files)}")
    unselected = sorted(set(additions) - set(fields))
    if unselected:
        raise SystemExit(f"Additions for keys not in --fields: {', '.join(unselected)}")

    planned = _planned(files, fields, today, additions)

    results: list[Result] = []
    for path, result, new_text in planned:
        if args.apply and result.changed:
            path.write_text(new_text, encoding="utf-8")
        results.append(result)

    _report(results, args.apply, today)
    return 0
