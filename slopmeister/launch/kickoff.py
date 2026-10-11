"""Resolve the kickoff text before any mutation, write it, and prune pairs of gone sessions."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shlex
import subprocess
import sys

from slopmeister.launch.model import Launch, die
from slopmeister.vault.runtime import repository

ENCODING = ("utf-8", "surrogateescape")


def _text(data: bytes) -> str:
    """Command substitution strips trailing newlines, the text the launch line delivers."""
    return data.decode(*ENCODING).rstrip("\n")


def _fetched(argv: list[str], cwd: Path | None, failure: str) -> str:
    result = subprocess.run(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)
    if result.returncode:
        raise die(failure)
    return _text(result.stdout)


def _source(launch: Launch) -> str:
    if launch.abandon:
        return "abandon"
    if launch.issue:
        scope = ["--repo", launch.claim_target] if launch.claim_target else []
        argv = ["gh", "issue", "view", launch.issue, *scope, "--json", "body", "-q", ".body"]
        failure = f"gh issue view {launch.issue} failed in {launch.repo}"
        return _fetched(argv, launch.repo, failure + ", the kickoff was not fetched")
    if launch.note:
        try:
            _, output = repository.note_bytes(launch.note)
        except OSError as error:
            raise die(
                f"vault note read failed for {launch.note}, the kickoff was not fetched"
            ) from error
        return _text(output)
    if sys.stdin.isatty():
        raise die("no kickoff, pipe it on stdin or pass --issue <n> or --note <path>")
    return _text(sys.stdin.buffer.read())


def resolve(launch: Launch) -> None:
    text = _source(launch)
    if not text:
        raise die("the kickoff is empty, a session with no brief sits idle")
    # Codex has no name flag and seeds the thread name from the opening text.
    launch.kickoff = f"{launch.name}\n\n{text}" if launch.tool == "codex" else text


def encoded(launch: Launch) -> bytes:
    return launch.kickoff.encode(*ENCODING)


def write(launch: Launch) -> None:
    descriptor = os.open(launch.kickoff_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(encoded(launch) + b"\n")


def receipt(launch: Launch) -> str:
    data = encoded(launch)
    return f"delivered ({len(data)} bytes, sha256 {hashlib.sha256(data).hexdigest()})"


def _workspace(command: Path) -> str | None:
    for line in command.read_text(*ENCODING).splitlines():
        if line.startswith("cd ") and " && exec " in line:
            return shlex.split(line.split(" && exec ", 1)[0])[1]
    return None


def prune(launch: Launch) -> None:
    """A command file is written after its workspace exists, so a missing workspace is gone."""
    pruned = 0
    try:
        for command in launch.state_dir.glob("*.command"):
            workspace = _workspace(command)
            if command.stem == launch.name or workspace is None or os.path.exists(workspace):
                continue
            command.with_suffix(".md").unlink(missing_ok=True)
            command.with_suffix(".orca").unlink(missing_ok=True)
            command.unlink()
            pruned += 1
    except (OSError, ValueError) as error:
        print(f"plot-session: kickoff cleanup skipped in {launch.state_dir}: {error}")
        return
    if pruned:
        print(
            f"plot-session: pruned {pruned} stale kickoff and command file pairs "
            f"from {launch.state_dir}"
        )
