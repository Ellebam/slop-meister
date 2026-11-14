"""The repositories recorded by one session, including legacy single-repository state."""

import json
import os
from pathlib import Path
import subprocess
import tempfile

from slopmeister.session import git_environment, launch_identity

DIRECTORY = ".slopmeister-repos"


def git(workspace: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(workspace), *args],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        env={**git_environment.child(), "GIT_TERMINAL_PROMPT": "0"},
        timeout=30,
        check=True,
    )
    return result.stdout.strip()


def state_path(workspace: Path) -> Path:
    return Path(git(workspace, "rev-parse", "--absolute-git-dir")) / "slopmeister-config/state.json"


def read(workspace: Path) -> dict:
    value = launch_identity.private_json(state_path(workspace), "repository state")
    if value.get("worktree") != str(workspace):
        raise ValueError("saved repository location differs")
    return value


def record(workspace: Path, state: dict) -> dict:
    common = git(workspace, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return dict(
        worktree=str(workspace),
        repository=str(Path(common).parent),
        common=common,
        branch=git(workspace, "branch", "--show-current"),
        plot=state["plot"],
        commit=state["commit"],
        shipping=state["shipping"],
        status="ready",
    )


def members(workspace: Path) -> list[dict]:
    state = read(workspace)
    rows = state.get("repositories") or [record(workspace, state)]
    if not isinstance(rows, list) or not rows or rows[0]["worktree"] != str(workspace):
        raise ValueError("invalid session repository list")
    seen = set()
    for index, row in enumerate(rows):
        path = Path(row["worktree"])
        try:
            expected = workspace if index == 0 else workspace / DIRECTORY / path.name
            if path != expected or path.is_symlink() or path.parent.is_symlink():
                raise ValueError("repository member is outside its recorded location")
            if row.get("status") != "ready":
                raise ValueError(f"repository preparation is incomplete: {path}")
            member = read(path)
            if index and member.get("session") != str(workspace):
                raise ValueError("repository member belongs to a different session")
            current = record(path, member)
            if current != row or row["common"] in seen or row["branch"] != rows[0]["branch"]:
                raise ValueError("repository member identity or permission changed")
            registration = f"worktree {path}\n"
            if registration not in git(path, "worktree", "list", "--porcelain") + "\n":
                raise ValueError("repository member is no longer registered")
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
            raise ValueError(f"repository member {path}: {error}") from error
        seen.add(row["common"])
    return rows


def workspaces(workspace: Path) -> list[Path]:
    if not state_path(workspace).exists():
        return [workspace]
    return [Path(row["worktree"]) for row in members(workspace)]


def save(path: Path, state: dict) -> None:
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".repositories-")
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(state, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
