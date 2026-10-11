"""Mutate a validated session workspace and install its fixed configuration."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from slopmeister.install import snapshot as session_snapshot
from slopmeister.install.fileops import lock_service_actions, remove, write_file
from slopmeister.install.models import InstallContext
from slopmeister.install.preflight import (
    DIRECTORIES,
    NATIVE_DIRS,
    ROOTS,
    GitOptions,
    configuration_roots,
    directory_parent,
    git,
    preflight,
    protected,
    refuse,
    repository_paths,
    safe_path,
)
from slopmeister.session.verify import snapshot


def worktree_relative(repo: Path, path: Path) -> str:
    """Git resolves the private exclusion file from the worktree root."""
    return os.path.relpath(path.resolve(), repo.resolve())


def prepare_repository(context: InstallContext) -> bool:
    common, gitdir = repository_paths(context.repo)
    baseline = git(context.repo, ("rev-parse", "HEAD")).decode().strip()
    entries = git(context.repo, ("ls-tree", "-rz", "HEAD")).split(b"\0")
    roots = configuration_roots(entries)
    allocation = context.request.allocation
    if allocation:
        if git(context.repo, ("ls-files", "--", ":(literal)" + allocation)):
            refuse("allocation basename is tracked in the repository")
        roots.append(allocation)
    _configuration_paths(context.repo, roots)
    if context.request.action == "--preflight":
        preflight(context.repo)
        return False
    _linked_worktree(context.repo, common, gitdir)
    context.common, context.gitdir, context.roots = common, gitdir, roots
    context.state_dir = gitdir / "slopmeister-config"
    _pristine(context)
    context.state.update(
        baseline=baseline,
        ship_target=_ship_target(context.repo),
    )
    return True


def _configuration_paths(repo: Path, roots: list[str]) -> None:
    for relative in roots:
        path = repo / relative
        safe_path(path, link=True)
        if (
            path.name in NATIVE_DIRS
            and path.exists()
            and not path.is_dir()
            and not path.is_symlink()
        ):
            refuse("configuration directory is a regular file: " + relative)


def _linked_worktree(repo: Path, common: Path, gitdir: Path) -> None:
    registered = b"worktree " + os.fsencode(repo) + b"\0"
    invalid = (
        gitdir == common
        or gitdir.parent != common / "worktrees"
        or not (repo / ".git").is_file()
        or (repo / ".git").is_symlink()
        or registered not in git(repo, ("worktree", "list", "--porcelain", "-z"))
        or (gitdir / "gitdir").read_text().strip() != str(repo / ".git")
    )
    if invalid:
        refuse("configuration requires a registered linked worktree; main is never a destination")


def _pristine(context: InstallContext) -> None:
    status = git(
        context.repo, ("status", "--porcelain", "--untracked-files=all", "--ignored=matching")
    )
    if context.state_dir.exists() or status:
        refuse("configuration destination must be pristine and not already prepared")
    context.indexed = git(context.repo, ("ls-files", "-v", "-z")).split(b"\0")
    if any(entry and not entry.startswith(b"H ") for entry in context.indexed):
        refuse("configuration destination has existing index flags")
    ignored = (
        git(
            context.repo,
            ("config", "--path", "--get", "core.excludesFile"),
            GitOptions(optional=True),
        )
        .decode()
        .strip()
    )
    default = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "git/ignore"
    excludes = Path(ignored) if ignored else default
    if not excludes.is_absolute():
        excludes = context.repo / excludes
    context.ignore_bytes = excludes.read_bytes() if excludes.is_file() else b""


def _ship_target(repo: Path) -> dict:
    options = GitOptions(optional=True)
    remote = git(repo, ("remote", "get-url", "--push", "--all", "origin"), options).decode().strip()
    branch = git(repo, ("branch", "--show-current")).decode().strip()
    return {"remote": remote, "branch": branch}


def prepare_directory(context: InstallContext) -> None:
    if context.repo.exists():
        refuse("session directory already exists")
    directory_parent(context.repo)
    context.roots = list(ROOTS)
    context.state_dir = context.repo / ".slopmeister-config"


def write_workspace(context: InstallContext) -> None:
    if context.directory:
        context.repo.mkdir(parents=True, mode=0o700)
    else:
        _enable_worktree_config(context)
        for relative in context.roots:
            remove(context.repo / relative)
    for relative, value in context.files.items():
        write_file(context.repo / relative, value)
    lock_service_actions(context.repo, (context.repo / ".codex/service-actions").is_dir())
    for name in DIRECTORIES:
        (context.repo / name).mkdir(parents=True, exist_ok=True)
    _state_helpers(context)
    if not context.directory:
        _delivery_isolation(context)
    state_file = context.state_dir / "state.json"
    state_file.write_text(json.dumps(context.state, indent=2) + "\n")
    state_file.chmod(0o600)


def _enable_worktree_config(context: InstallContext) -> None:
    args = (
        "config",
        "--file",
        str(context.common / "config"),
        "--type=bool",
        "--get",
        "extensions.worktreeConfig",
    )
    if git(context.repo, args, GitOptions(optional=True)).strip() != b"true":
        git(context.repo, ("config", "extensions.worktreeConfig", "true"))


def _state_helpers(context: InstallContext) -> None:
    """The private state directory: the session snapshot and the entry that runs from it."""
    context.state_dir.mkdir(mode=0o700)
    root = session_snapshot.write(context.root, context.state_dir)
    digests = session_snapshot.state_entries(context.state_dir, root)
    roots = [path for path in context.roots if path != context.request.allocation]
    context.state.update(
        roots=context.roots,
        files=snapshot(context.repo, roots),
        helper_sha256=digests["config-install.py"],
        snapshot=str(root),
        snapshot_sha256=session_snapshot.digest(root / session_snapshot.MANIFEST),
    )


def _delivery_isolation(context: InstallContext) -> None:
    _excludes(context)
    _route_excludes(context)


def _excludes(context: InstallContext) -> None:
    exclude = context.state_dir / "exclude"
    rules = "".join("/" + path + "\n" for path in context.roots).encode()
    exclude.write_bytes(context.ignore_bytes + b"\n" + rules + b"/*-NOTES.md\n")
    context.state["exclude_sha256"] = hashlib.sha256(exclude.read_bytes()).hexdigest()
    tracked = [
        entry[2:]
        for entry in context.indexed
        if entry and protected(os.fsdecode(entry[2:]), context.roots)
    ]
    if tracked:
        options = GitOptions(data=b"\0".join(tracked) + b"\0")
        git(context.repo, ("update-index", "--skip-worktree", "-z", "--stdin"), options)
    shared = context.common / "info/exclude"
    prior = shared.read_bytes() if shared.exists() else b""
    if b"/.worktrees/" not in prior.splitlines():
        shared.parent.mkdir(exist_ok=True)
        shared.write_bytes(prior + b"\n/.worktrees/\n")


def _route_excludes(context: InstallContext) -> None:
    value = worktree_relative(context.repo, context.state_dir / "exclude")
    git(context.repo, ("config", "--worktree", "core.excludesFile", value))
    if git(context.repo, ("status", "--porcelain", "--untracked-files=all")):
        refuse("configuration preparation did not produce a clean worktree")
