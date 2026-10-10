"""Append verified retro entries and retain failures in a stable replay queue."""

import argparse
from datetime import UTC, date, datetime
import os
from pathlib import Path, PurePosixPath
import re
import socket
import sys
import tempfile
import time

from . import repository

STALE_DAYS = 7
DEFAULT_NOTE = "_system/retro-log.md"


def spill_dir() -> Path:
    if value := os.environ.get("RETRO_SPILL_DIR"):
        return Path(value)
    state = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    return state / "slopmeister/retro-spill"


def input_problem(label: str, value: str, *, table: bool = False) -> str | None:
    control = re.search(r"[\x00-\x1f\x7f]", value) is not None
    problems = (
        (not value, f"{label} is empty"),
        (control, f"{label} must be one line without control characters"),
        (
            r"\n" in value or r"\t" in value,
            f"{label} carries a literal backslash-n or backslash-t sequence",
        ),
        (table and "|" in value, f"{label} cannot carry a pipe"),
    )
    return next((message for found, message in problems if found), None)


def _machine() -> str:
    """The short host name, so the one shared log shows which machine wrote an entry."""
    return socket.gethostname().partition(".")[0]


def _entry(args: argparse.Namespace, lines: list[str]) -> str:
    return (
        f"### {args.repo}, {args.task}, {args.title}, {date.today():%F}\n\n"
        "| Repository | Tool | Model | Machine |\n"
        "|---|---|---|---|\n"
        f"| {args.repo} | {args.tool} | {args.model} | {_machine()} |\n\n"
        f"- {lines[0]}\n- {lines[1]}\n- {lines[2]}\n"
    )


def _slug(value: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]", "-", value.casefold())).strip("-")


def _matching_spill(directory: Path, entry: str) -> Path | None:
    for owed in sorted(directory.glob("*.md")):
        try:
            if owed.read_text() == entry:
                return owed
        except OSError:
            continue
    return None


def _spill(entry: str, args: argparse.Namespace) -> int:
    directory = spill_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        if owed := _matching_spill(directory, entry):
            print(f"retro entry still owed at {owed}", file=sys.stderr)
            return 1
        prefix = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        stem = f"{prefix}-{_slug(args.repo)}-{_slug(args.task)}."
        with tempfile.NamedTemporaryFile(
            mode="w", dir=directory, prefix=stem, delete=False
        ) as stream:
            stream.write(entry)
            stream.flush()
            os.fsync(stream.fileno())
            source = Path(stream.name)
        target = source.with_suffix(source.suffix + ".md")
        source.replace(target)
        print(
            f"retro entry NOT consolidated, spilled to {target}; inspect Markdown and Git "
            f"state for {args.note}; the next close-out with vault access replays it",
            file=sys.stderr,
        )
    except OSError:
        print(
            f"retro entry NOT consolidated and NOT spilled, {directory} is not writable; "
            f"the entry follows\n{entry}",
            file=sys.stderr,
        )
    return 1


def _owed() -> list[Path]:
    directory = spill_dir()
    return sorted(directory.glob("*.md")) if directory.is_dir() else []


def _replay_entries(paths: list[Path]) -> list[tuple[Path, str]]:
    entries = []
    for path in paths:
        try:
            age = int((time.time() - path.stat().st_mtime) / 86400)
            entry = path.read_text()
        except OSError:
            continue
        if age > STALE_DAYS:
            print(f"stale spill {path}, {age} days old", file=sys.stderr)
        entries.append((path, entry))
    return entries


def _addition(current: bytes, entries: list[str]) -> bytes:
    addition, complete = bytearray(), current
    for entry in entries:
        encoded = entry.encode()
        if encoded in complete:
            continue
        if complete and not complete.endswith(b"\n"):
            addition.extend(b"\n")
            complete += b"\n"
        if complete and not complete.endswith(b"\n\n"):
            addition.extend(b"\n")
            complete += b"\n"
        addition.extend(encoded)
        complete += encoded
    return bytes(addition)


def _append(path: Path, addition: bytes) -> None:
    if not addition:
        return
    flags = os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "ab", closefd=True) as stream:
        stream.write(addition)
        stream.flush()
        os.fsync(stream.fileno())


def _remove_replayed(entries: list[tuple[Path, str]]) -> None:
    for path, _ in entries:
        try:
            path.unlink()
        except OSError:
            print(
                f"replayed spill could not be removed, {path}, it is already in the note",
                file=sys.stderr,
            )


def _consolidated(note: str, entries: list[str]) -> bool:
    expected = [entry.encode() for entry in entries]
    if repository.committed(note, expected):
        return True
    repository.commit_cli(["Append", "retro", "entry", "--", note])
    return repository.committed(note, expected)


def _problem(args: argparse.Namespace, lines: list[str]) -> str | None:
    if len(lines) != 3:
        return f"stdin must carry exactly three lines, got {len(lines)}"
    if repository.path_problem(args.note):
        return "--note must be vault-relative without parent or control segments"
    checks = [
        ("--repo", args.repo, True),
        ("--tool", args.tool, True),
        ("--model", args.model, True),
        ("--task", args.task, False),
        ("--title", args.title, False),
        ("--note", args.note, False),
        *((f"line {index}", value, False) for index, value in enumerate(lines, 1)),
    ]
    return next(
        (
            problem
            for label, value, table in checks
            if (problem := input_problem(label, value, table=table))
        ),
        None,
    )


def _refusal(args: argparse.Namespace, lines: list[str]) -> str | None:
    problem = _problem(args, lines)
    note = str(PurePosixPath(args.note)).casefold()
    custom_target = note != DEFAULT_NOTE
    if problem is None and custom_target and not os.environ.get("RETRO_SPILL_DIR"):
        problem = "a custom --note requires an isolated RETRO_SPILL_DIR"
    forbidden = os.environ.get("RETRO_FORBID_NOTE")
    if problem is None and forbidden and str(PurePosixPath(forbidden)).casefold() == note:
        problem = f"--note {args.note} is forbidden by RETRO_FORBID_NOTE"
    return problem


def _retain_failed(args: argparse.Namespace, entry: str, appended: bool) -> int:
    if appended and repository.committed(args.note, [entry.encode()]):
        print("retro replay NOT consolidated, existing spills retained", file=sys.stderr)
        return 1
    return _spill(entry, args)


def _argv(args: argparse.Namespace) -> list[str]:
    values = [
        *(
            item
            for name in ("repo", "task", "title", "tool", "model")
            for item in (f"--{name}", getattr(args, name))
        ),
        "--note",
        args.note,
    ]
    return ["retro", *values]


def run(args: argparse.Namespace) -> int:
    lines = sys.stdin.read().splitlines()
    if problem := _refusal(args, lines):
        print(f"refused: {problem}", file=sys.stderr)
        return 2
    entry = _entry(args, lines)
    if os.environ.get("SLOPMEISTER_VAULT_LOCKED") != "1":
        status = repository.locked(_argv(args), [args.note], input_text="\n".join(lines) + "\n")
        return 0 if status == 0 else _spill(entry, args)
    replayed = _replay_entries(_owed())
    entries = [*(value for _, value in replayed), entry]
    try:
        subject, current = repository.note_bytes(args.note)
        _append(subject, _addition(current, entries))
        _, final = repository.note_bytes(args.note)
        appended = all(value.encode() in final for value in entries)
    except OSError as error:
        print(f"retro note unavailable: {error}", file=sys.stderr)
        appended = False
    if appended and _consolidated(args.note, entries):
        for path, _ in replayed:
            print(f"replayed spilled retro entry from {path}")
        _remove_replayed(replayed)
        print(f"retro entry appended to {args.note}")
        print(entry.splitlines()[0])
        return 0
    return _retain_failed(args, entry, appended)
