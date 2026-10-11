"""Verify a prepared session against its saved configuration snapshot."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

from slopmeister.errors import SlopmeisterError
from slopmeister.install import snapshot as session_snapshot
from slopmeister.install.preflight import (
    DIRECTORIES,
    ROOTS,
    directory_parent,
    refuse,
    repository_paths,
    safe_path,
    setting,
)
from slopmeister.install.workspace import worktree_relative
from slopmeister.session.verify import snapshot

VERSION = 3


@dataclass(frozen=True)
class CheckContext:
    repo: Path
    target: str
    permission: str
    grants: list[str]


@dataclass(frozen=True)
class CheckedState:
    context: CheckContext
    state_dir: Path
    state: dict
    roots: list[str]


def state_directory(repo: Path) -> tuple[Path, bool]:
    directory = not (repo / ".git").exists()
    if directory:
        directory_parent(repo)
        return repo / ".slopmeister-config", True
    _, gitdir = repository_paths(repo)
    return gitdir / "slopmeister-config", False


def _identity(state: dict, context: CheckContext, directory: bool) -> None:
    if state.get("version") == 2:
        refuse(
            "legacy prepared workspace still uses the removed Git guard and cannot be "
            "redispatched; the operator can restore ordinary Git in this worktree with "
            "`git config --worktree --unset core.hooksPath`"
        )
    if state.get("worktree") != str(context.repo):
        refuse(
            f"this workspace moved from {state.get('worktree')} to {context.repo} and its saved "
            "configuration cannot verify it; no automatic recovery exists, do not commit or push, "
            "stop and report this to the operator"
        )
    expected = (
        state["version"] == VERSION
        and state["worktree"] == str(context.repo)
        and state["plot"] == context.target
        and state["commit"] == context.permission
        and state["directory"] == directory
        and state["grants"] == context.grants
    )
    if not expected:
        refuse("saved configuration identity or permission disagrees with this launch")
    if state.get("shipping", "deny") not in ("allow", "deny"):
        refuse("saved shipping permission is invalid")
    if state.get("bloom", "local") not in ("local", "tailnet"):
        refuse("saved Bloom publication permission is invalid")


def _roots(state: dict) -> list[str]:
    roots = state["roots"]
    unsafe = (
        not isinstance(roots, list)
        or any(
            not isinstance(path, str)
            or path.startswith("/")
            or any(part in ("", ".", "..") for part in path.split("/"))
            for path in roots
        )
        or not set(ROOTS).issubset(roots)
    )
    if unsafe:
        refuse("saved configuration roots are incomplete or unsafe")
    return roots


def _files(checked: CheckedState) -> None:
    context, state_dir, state, roots = (
        checked.context,
        checked.state_dir,
        checked.state,
        checked.roots,
    )
    selected = [path for path in roots if path != state["allocation"]]
    current = snapshot(context.repo, selected)
    changed = sorted(
        path
        for path in {*current, *state["files"]}
        if current.get(path) != state["files"].get(path)
    )
    if changed:
        names = ", ".join(json.dumps(path) for path in changed)
        refuse("saved session configuration has changed or is incomplete: " + names)
    if any(not (context.repo / path).is_dir() for path in DIRECTORIES):
        refuse("saved configuration lacks a required native directory")
    helper = state_dir / "config-install.py"
    safe_path(helper)
    if hashlib.sha256(helper.read_bytes()).hexdigest() != state["helper_sha256"]:
        refuse("saved configuration helper has changed")
    if not state.get("snapshot_sha256"):
        refuse("saved configuration lacks its snapshot record")
    try:
        session_snapshot.verify(state_dir, state["snapshot_sha256"])
    except SlopmeisterError as error:
        refuse(str(error))


def _delivery_isolation(checked: CheckedState) -> None:
    context, state_dir, state = (
        checked.context,
        checked.state_dir,
        checked.state,
    )
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", state["baseline"]):
        refuse("saved repository baseline is invalid")
    expected = worktree_relative(context.repo, state_dir / "exclude")
    if setting(context.repo, "core.excludesFile") != expected:
        refuse("saved delivery exclusion is not wired to this worktree")
    safe_path(state_dir / "exclude")
    digest = hashlib.sha256((state_dir / "exclude").read_bytes()).hexdigest()
    if digest != state["exclude_sha256"]:
        refuse("saved ignore rules have changed")


def check(context: CheckContext) -> dict:
    state_dir, directory = state_directory(context.repo)
    safe_path(state_dir / "state.json")
    state = json.loads((state_dir / "state.json").read_text())
    _identity(state, context, directory)
    roots = _roots(state)
    checked = CheckedState(context, state_dir, state, roots)
    _files(checked)
    if not directory:
        _delivery_isolation(checked)
    print("Slopmeister configuration verified")
    return state
