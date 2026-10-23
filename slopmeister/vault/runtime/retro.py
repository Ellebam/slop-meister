"""Write one new retro note and commit only that note through the ordinary lease."""

import argparse
from datetime import date
import os
import re
import socket
import subprocess
import sys
from uuid import uuid4

from . import repository

DIRECTORY = "_system/retros"
COMMIT_WAIT = 60
SLUG_LENGTH = 64


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
    """Keep the machine field without copying its domain into the entry."""
    return socket.gethostname().partition(".")[0]


def _entry(args: argparse.Namespace, lines: list[str]) -> str:
    today = date.today().isoformat()
    return (
        f"---\ntype: reference\ncreated: '{today}'\n---\n\n"
        f"### {args.repo}, {args.task}, {args.title}, {today}\n\n"
        "| Repository | Tool | Model | Machine |\n"
        "|---|---|---|---|\n"
        f"| {args.repo} | {args.tool} | {args.model} | {_machine()} |\n\n"
        f"- {lines[0]}\n- {lines[1]}\n- {lines[2]}\n"
    )


def _problem(args: argparse.Namespace, lines: list[str]) -> str | None:
    if len(lines) != 3:
        return f"stdin must carry exactly three lines, got {len(lines)}"
    checks = [
        ("--repo", args.repo, True),
        ("--tool", args.tool, True),
        ("--model", args.model, True),
        ("--task", args.task, False),
        ("--title", args.title, False),
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


def _write(task: str, entry: str) -> str:
    # The root may be the machine's Drive symlink, but internal directories cannot redirect it.
    root = repository.vault_path().resolve(strict=True)
    directory = root / DIRECTORY
    if directory.parent.is_symlink() or directory.is_symlink():
        raise OSError("retro directories must not be symlinks")
    if not directory.parent.is_dir():
        raise OSError("the vault must contain a real _system directory")
    directory.mkdir(mode=0o700, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", task.casefold()).strip("-")[:SLUG_LENGTH]
    relative = f"{DIRECTORY}/{date.today():%F}-{slug}-{uuid4().hex}.md"
    descriptor = os.open(root / relative, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(entry)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as error:
        raise OSError(f"{relative}: {error}") from error
    return relative


def _committed(path: str, expected: bytes) -> bool:
    env = repository.commit_environment()
    try:
        result = subprocess.run(
            ["git", f"--git-dir={env['VAULT_GIT_DIR']}", "show", f"HEAD:{path}"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return False
    return result.returncode == 0 and result.stdout == expected


def run(args: argparse.Namespace) -> int:
    lines = sys.stdin.read().splitlines()
    if problem := _problem(args, lines):
        print(f"refused: {problem}", file=sys.stderr)
        return 2
    entry = _entry(args, lines)
    try:
        note = _write(args.task, entry)
    except OSError as error:
        print(f"retro file unavailable: {error}", file=sys.stderr)
        return 1
    status = repository.commit_cli(["Record retro entry", "--", note], wait_seconds=COMMIT_WAIT)
    if status and _committed(note, entry.encode()):
        status = 0
    if status:
        print(f"retro file not committed: {note}. Use an ordinary named commit.", file=sys.stderr)
    else:
        print(f"retro entry committed: {note}")
    return status
