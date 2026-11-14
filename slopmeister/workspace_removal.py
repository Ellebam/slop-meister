"""Remove one retired workspace after checking its location and surviving ownership."""

import argparse
from collections.abc import Sequence
from dataclasses import replace
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

from slopmeister.claims import evidence
from slopmeister.errors import SlopmeisterError
from slopmeister.paths import ROOT, main_checkout, session_root
from slopmeister.removal import check_ignored, ignored_work, nested, read_inventory, remove_tree
from slopmeister.removal import clean as _clean
from slopmeister.removal import git as _git
from slopmeister.repositories import check_companions, remove_companions
from slopmeister.session import git_environment
from slopmeister.slots import allocation, claimed, down, leftover, tester
from slopmeister.threads import occupants


def _scope(value: str) -> tuple[Path, Path | None]:
    path = Path(os.path.abspath(Path(value).expanduser()))
    if path.name == ".orca-worktree-trash":
        raise SlopmeisterError("Orca trash containers must not be removed as a workspace")
    if path.is_symlink() or path.parent.is_symlink():
        raise SlopmeisterError("a symlink in the managed workspace path is refused")
    if not path.is_dir():
        raise SlopmeisterError(f"workspace directory not found: {path}")
    sessions = session_root()
    if path.parent.resolve() == sessions.expanduser().resolve():
        if (path / ".git").exists() or (path / ".git").is_symlink():
            raise SlopmeisterError("Git workspaces require their owning repository's .worktrees")
        return path.resolve(), None
    if path.parent.name != ".worktrees":
        raise SlopmeisterError(
            "only workspace children of .worktrees or the session root are supported"
        )
    repo = path.parent.parent.resolve()
    common = Path(_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").strip())
    if common != repo / ".git" or path.parent.resolve() != repo / ".worktrees":
        raise SlopmeisterError("workspace is not below its owning main repository")
    return path.resolve(), repo


def _registered(path: Path, repo: Path | None) -> bool:
    if repo is None:
        return False
    rows = _git(repo, "worktree", "list", "--porcelain", "-z").split("\0")
    known = [
        Path(row.removeprefix("worktree ")).resolve() for row in rows if row.startswith("worktree ")
    ]
    if any(member != path and member.is_relative_to(path) for member in known):
        raise SlopmeisterError(
            "another registered worktree is inside this workspace, remove it first"
        )
    return path in known


def _slot(
    path: Path, repo: Path | None, *, own: bool = False, force: bool = False
) -> down.Request | None:
    if repo is None:
        return
    source = path / allocation.ALLOCATION
    if source.exists():
        item = allocation.read(source)
        if item.name != path.name:
            raise SlopmeisterError("allocation names a different workspace, refusing")
        plot, number = item.target, str(item.slot)
        if own:
            return down.Request(str(repo), plot, path.name, force, number, True)
    else:
        receipt = claimed._receipt(path, repo)
        saved = (read_inventory(receipt.parent) or {}) if receipt else {}
        if saved.get("allocation") != allocation.ALLOCATION:
            return
        plot, number = saved.get("plot"), "<n>"
        if not isinstance(plot, str):
            raise SlopmeisterError("saved slot allocation has no plot, refusing")
        allocation.validate_name(plot, "plot")
    command = _slot_command(str(repo), plot, path.name, number)
    raise SlopmeisterError(f"this workspace belongs to a slot, run: {command}")


def _slot_command(repo: str, plot: str, name: str, number: str) -> str:
    prefix = ["task", "--dir", str(ROOT), "slot:down", "--", repo]
    return shlex.join([*prefix, plot, name, "--slot", number])


def _occupied(path: Path) -> None:
    try:
        found = [p for p in occupants.census(str(path)) if p.inside]
    except occupants.CensusError as error:
        raise SlopmeisterError(f"worker inspection failed, refusing: {error}") from error
    if found:
        names = ", ".join(f"{p.kind} pid {p.pid}" for p in found)
        raise SlopmeisterError(f"a worker still occupies {path}, refusing: {names}")


def _contents(
    path: Path, repo: Path | None, registered: bool, force: bool, slotted: bool = False
) -> None:
    """Refuse unsaved ignored work and nested worktrees other than the checked companions.

    A slot release allows the slot's own allocation file, so it checks ignored work itself."""
    children = check_companions(path, force) if registered else []
    owned = frozenset(Path(row["worktree"]) for row in children)
    if registered and not force and not slotted:
        ignored_work(path, owned)
    if repo is None and not force:
        check_ignored(path, ["? " + p.name for p in path.iterdir()], path / ".slopmeister-config")
    nested(path, owned)


def _check(
    path: Path, repo: Path | None, args: argparse.Namespace
) -> tuple[occupants.Process | None, down.Request | None]:
    registered = _registered(path, repo)
    if args.self and repo is not None and not registered:
        raise SlopmeisterError("--self requires a registered worktree or a session directory")
    if args.stop_only:
        return down._calling_worker(path, "workspace"), None
    slot = _slot(path, repo, own=args.self, force=args.force)
    claimed.refuse(path, "<plot>", repo)
    if Path.cwd().resolve().is_relative_to(path):
        raise SlopmeisterError("run workspace removal from outside the selected workspace")
    if registered:
        _clean(path, repo, args.force)
    elif repo is not None:
        if claimed._receipt(path, repo) is not None:
            raise SlopmeisterError("Git still identifies this workspace, use its owning repository")
        leftover.confirm(args.force, _retry(path))
    _contents(path, repo, registered, args.force, slot is not None)
    if args.self:
        return down._calling_worker(path, "workspace"), slot
    else:
        _occupied(path)
    return None, None


def _retry(path: Path) -> str:
    return shlex.join([str(ROOT / "bin/slopmeister"), "workspace-remove", str(path), "--force"])


def _remove(path: Path, repo: Path | None) -> int:
    if repo is not None:
        if _registered(path, repo):
            remove_companions(path)
        leftover.remove(path, _retry(path), repo)
    else:
        remove_tree(path)
    print(f"workspace removed: {path}; branches kept")
    return 0


def _self(
    path: Path,
    repo: Path | None,
    args: argparse.Namespace,
    caller: occupants.Process,
    slot: down.Request | None,
) -> int:
    # A directory session keeps its launcher state in itself, it has no Git metadata.
    saved = evidence.receipt_path(path).parent if repo else path / ".slopmeister-config"
    plot = (read_inventory(saved) or {}).get("plot")
    if not isinstance(plot, str):
        raise SlopmeisterError("self-cleanup requires the saved launcher plot")
    allocation.validate_name(plot, "plot")
    directory = Path(
        os.environ.get("PLOT_SESSION_STATE_DIR") or main_checkout() / "tmp/plot-session"
    )
    directory.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f"{path.name}.remove.", suffix=".log", dir=directory)
    os.close(descriptor)
    if not down._detach(Path(name)):
        action = "session stop" if args.stop_only else "workspace cleanup"
        print(f"{action} pending; this worker stops now; result in {name}; branches kept")
        return 0
    request = slot or down.Request(str(repo or ""), plot, path.name, args.force, "")
    down._stop_worker(request, repo, path, caller)
    if args.stop_only:
        print(f"session stopped; workspace kept: {path}")
        return 0
    if slot:
        return down._release(replace(slot, own=False))
    args.self = False
    _check(path, repo, args)
    return _remove(path, repo)


def _detached(
    path: Path,
    repo: Path,
    args: argparse.Namespace,
    caller: occupants.Process,
    slot: down.Request | None,
) -> int:
    """A failure after the fork reaches only the private log, when the worker is already told
    to stop. That log must name what stayed behind and the command that removes it."""
    command = os.getpid()
    try:
        return _self(path, repo, args, caller, slot)
    except (SlopmeisterError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        if os.getpid() == command or args.stop_only:
            raise
        cleanup = (
            _slot_command(slot.repo, slot.target, slot.name, slot.wanted)
            if slot
            else shlex.join(["task", "--dir", str(ROOT), "workspace:remove", "--", str(path)])
        )
        raise SlopmeisterError(
            f"{error}; workspace kept: {path}; when its worker has stopped, run: {cleanup}"
        ) from error


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="slopmeister workspace-remove")
    parser.add_argument("path")
    parser.add_argument(
        "--force", action="store_true", help="confirm loss of unchecked or unsaved work"
    )
    parser.add_argument(
        "--self", action="store_true", help="stop the sole calling worker before removal"
    )
    parser.add_argument(
        "--stop-only", action="store_true", help="with --self, keep the workspace, slot and claim"
    )
    args = parser.parse_args(argv)
    if args.stop_only and (not args.self or args.force):
        parser.error("--stop-only requires --self and refuses --force")
    if git_environment.redirect():
        raise SlopmeisterError("Git context overrides are refused for workspace removal")
    try:
        path, repo = _scope(args.path)
        caller, slot = _check(path, repo, args)
        if slot:
            if tester.find(slot.target, slot.name, slot.wanted):
                raise SlopmeisterError("slot has a check lease; finish or recover it before --self")
            down._context(slot)
        return _detached(path, repo, args, caller, slot) if args.self else _remove(path, repo)
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        raise SlopmeisterError(f"workspace removal failed: {error}") from error
