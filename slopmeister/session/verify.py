#!/usr/bin/env python3
"""Verify fixed session configuration before automated shipping."""

from collections.abc import Sequence
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

from slopmeister.session import git_environment


def entry() -> Path:
    """The delivered entry in the state directory, the path the ship helper invokes."""
    return Path(sys.argv[0]).resolve()


VERSION = 3
ROOTS = (
    "AGENTS.md",
    "CLAUDE.md",
    "AGENTS.override.md",
    "CLAUDE.local.md",
    ".claude",
    ".codex",
    ".agents",
    ".mcp.json",
)
DIRECTORIES = (".claude/skills", ".claude/agents", ".claude/commands", ".agents/skills")
# Claude Code writes these at runtime, and none is loaded as instructions or skills.
LOCAL_SETTINGS = Path(".claude/settings.local.json")
SCHEDULER_LOCK = Path(".claude/scheduled_tasks.lock")
CLAUDE_WRITES = Path(".claude/.cc-writes")


def refuse(message: str) -> None:
    raise ValueError(message)


def safe_path(path: Path) -> None:
    for ancestor in reversed((path, *path.parents)):
        if ancestor.is_symlink():
            refuse("symlinked configuration path: " + str(ancestor))


def _claude_writes(relative_path: Path, path: Path) -> bool:
    """Its contents change during the session, so only the directory's shape is verified."""
    if relative_path == CLAUDE_WRITES and not path.is_dir():
        refuse("Claude Code runtime path is not a directory: " + str(path))
    return relative_path.is_relative_to(CLAUDE_WRITES)


def snapshot(repo: Path, roots: list[str]) -> dict:
    result = {}
    for relative in roots:
        root = repo / relative
        paths = [root, *root.rglob("*")] if root.is_dir() and not root.is_symlink() else [root]
        for path in paths:
            relative_path = path.relative_to(repo)
            if relative_path in (LOCAL_SETTINGS, SCHEDULER_LOCK):
                continue
            safe_path(path)
            if _claude_writes(relative_path, path) or not path.exists():
                continue
            if not path.is_dir() and not path.is_file():
                refuse("configuration is not a regular file or directory: " + str(path))
            digest = None if path.is_dir() else hashlib.sha256(path.read_bytes()).hexdigest()
            result[relative_path.as_posix()] = [digest, stat.S_IMODE(path.stat().st_mode)]
    return result


def _check_identity(state: dict, repo: Path) -> None:
    if state.get("version") == 2:
        refuse(
            "legacy prepared workspace still uses the removed Git guard; the operator can restore "
            "ordinary Git with `git config --worktree --unset core.hooksPath`"
        )
    required = (
        state["version"] == VERSION
        and state["worktree"] == str(repo)
        and state["commit"] in ("allow", "deny")
        and isinstance(state["grants"], list)
    )
    if not required:
        refuse("saved configuration identity or permission disagrees with this launch")
    if state.get("shipping", "deny") not in ("allow", "deny"):
        refuse("saved shipping permission is invalid")
    roots = state.get("roots")
    unsafe = not isinstance(roots, list) or not set(ROOTS).issubset(roots)
    unsafe = unsafe or any(
        not isinstance(path, str)
        or path.startswith("/")
        or any(part in ("", ".", "..") for part in path.split("/"))
        for path in roots
    )
    if unsafe:
        refuse("saved configuration roots are incomplete or unsafe")


def _check_delivery_isolation(repo: Path, state: dict) -> None:
    state_dir = entry().parent
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", state["baseline"]):
        refuse("saved repository baseline is invalid")
    if name := git_environment.redirect():
        refuse("delivery verification refuses Git context override " + name)
    result = subprocess.run(
        ["git", "-C", str(repo), "config", "--get", "core.excludesFile"],
        capture_output=True,
        text=True,
        env=git_environment.child(),
    )
    expected = os.path.relpath((state_dir / "exclude").resolve(), repo.resolve())
    if result.returncode or result.stdout.strip() != expected:
        refuse("saved delivery exclusion is not wired to this worktree")
    if hashlib.sha256((state_dir / "exclude").read_bytes()).hexdigest() != state["exclude_sha256"]:
        refuse("saved ignore rules have changed")


def verify_shipping(state: dict) -> None:
    repo = Path(state["worktree"])
    _check_identity(state, repo)
    roots = [path for path in state["roots"] if path != state["allocation"]]
    current, saved = snapshot(repo, roots), state["files"]
    changed = sorted(
        path
        for path in {*current, *saved}
        if path not in current or path not in saved or current[path] != saved[path]
    )
    if changed:
        names = ", ".join(json.dumps(path) for path in changed)
        refuse("saved session configuration has changed or is incomplete: " + names)
    if any(not (repo / path).is_dir() for path in DIRECTORIES):
        refuse("saved configuration lacks a required native directory")
    if hashlib.sha256(entry().read_bytes()).hexdigest() != state["helper_sha256"]:
        refuse("saved configuration helper has changed")
    if not state["directory"]:
        _check_delivery_isolation(repo, state)
    print("Slopmeister configuration verified")


def main(argv: Sequence[str]) -> int:
    try:
        if argv == ["--verify-shipping"]:
            verify_shipping(json.loads((entry().parent / "state.json").read_text()))
            return 0
        refuse("invalid delivered configuration helper operation")
    except (ValueError, OSError, KeyError, TypeError) as error:
        message = (
            "config-install: "
            + str(error)
            + "; preserve this workspace and report the refusal to the operator"
        )
        print(message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
