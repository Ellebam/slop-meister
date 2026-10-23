"""Remove one retired workspace after checking its location and surviving ownership."""

import argparse
from collections.abc import Sequence
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

from slopmeister.claims import evidence
from slopmeister.errors import SlopmeisterError
from slopmeister.paths import ROOT, main_checkout
from slopmeister.removal import IGNORED_ARGS, check_ignored, read_inventory, remove_tree
from slopmeister.session import git_environment
from slopmeister.slots import allocation, claimed, down, leftover
from slopmeister.threads import occupants


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        env=git_environment.child(),
        text=True,
        capture_output=True,
        timeout=30,
    )
    if result.returncode:
        raise SlopmeisterError(result.stderr.strip() or "Git inspection failed")
    return result.stdout


def _scope(value: str) -> tuple[Path, Path | None]:
    path = Path(os.path.abspath(Path(value).expanduser()))
    if path.name == ".orca-worktree-trash":
        raise SlopmeisterError("Orca trash containers must not be removed as a workspace")
    if path.is_symlink() or path.parent.is_symlink():
        raise SlopmeisterError("a symlink in the managed workspace path is refused")
    if not path.is_dir():
        raise SlopmeisterError(f"workspace directory not found: {path}")
    sessions = Path(os.environ.get("PLOT_SESSION_ROOT") or Path.home() / ".slopmeister/sessions")
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


def _slot(path: Path, repo: Path | None) -> None:
    if repo is None:
        return
    source = path / allocation.ALLOCATION
    if source.exists():
        item = allocation.read(source)
        if item.name != path.name:
            raise SlopmeisterError("allocation names a different workspace, refusing")
        plot, number = item.target, str(item.slot)
    else:
        receipt = claimed._receipt(path, repo)
        saved = (read_inventory(receipt.parent) or {}) if receipt else {}
        if saved.get("allocation") != allocation.ALLOCATION:
            return
        plot, number = saved.get("plot"), "<n>"
        if not isinstance(plot, str):
            raise SlopmeisterError("saved slot allocation has no plot, refusing")
        allocation.validate_name(plot, "plot")
    prefix = ["task", "--dir", str(ROOT), "slot:down", "--", str(repo)]
    command = shlex.join([*prefix, plot, path.name, "--slot", number])
    raise SlopmeisterError(f"this workspace belongs to a slot, run: {command}")


def _occupied(path: Path) -> None:
    try:
        found = [p for p in occupants.census(str(path)) if p.inside]
    except occupants.CensusError as error:
        raise SlopmeisterError(f"worker inspection failed, refusing: {error}") from error
    if found:
        names = ", ".join(f"{p.kind} pid {p.pid}" for p in found)
        raise SlopmeisterError(f"a worker still occupies {path}, refusing: {names}")


def _claim(path: Path, repo: Path | None, own: bool) -> None:
    if not (own and claimed.handback_recorded(path, repo)):
        claimed.refuse(path, "<plot>", repo)


def _check(path: Path, repo: Path | None, args: argparse.Namespace) -> bool:
    registered = _registered(path, repo)
    if args.self and not registered:
        raise SlopmeisterError("--self requires a registered worktree")
    _slot(path, repo)
    _claim(path, repo, args.self)
    if Path.cwd().resolve().is_relative_to(path):
        raise SlopmeisterError("run workspace removal from outside the selected workspace")
    if registered:
        _clean(path, repo, args.force)
    elif repo is not None:
        if claimed._receipt(path, repo) is not None:
            raise SlopmeisterError("Git still identifies this workspace, use its owning repository")
        leftover.confirm(args.force, _retry(path))
    if repo is None and not args.force:
        check_ignored(path, ["? " + p.name for p in path.iterdir()], path / ".slopmeister-config")
    _nested(path)
    if args.self:
        down._calling_worker(path, "workspace")
    else:
        _occupied(path)
    return registered


def _clean(path: Path, repo: Path, force: bool) -> None:
    if (path / ".git").is_symlink() or not (path / ".git").is_file():
        repair = shlex.join(["git", "-C", str(repo), "worktree", "repair"])
        raise SlopmeisterError(f"registered worktree has no valid Git link; repair with: {repair}")
    if Path(_git(path, "rev-parse", "--show-toplevel").strip()).resolve() != path:
        raise SlopmeisterError("Git link does not identify the selected worktree, refusing")
    common = _git(path, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    if Path(common).resolve() != repo / ".git":
        raise SlopmeisterError("Git link does not belong to the owning repository, refusing")
    metadata = Path(_git(path, "rev-parse", "--absolute-git-dir").strip())
    if (metadata / "locked").exists():
        raise SlopmeisterError("locked worktree, unlock it before workspace removal")
    if not _git(path, "branch", "--show-current").strip() and not force:
        raise SlopmeisterError("detached HEAD may lose commits, pass --force to confirm deletion")
    if _git(path, "status", "--porcelain", "--untracked-files=all") and not force:
        raise SlopmeisterError("uncommitted work, pass --force to confirm deletion")
    if not force:
        entries = _git(path, *IGNORED_ARGS).split("\0")
        ignored = [entry for entry in entries if entry.startswith(("? ", "S ", "s ", "h "))]
        check_ignored(path, ignored, metadata / "slopmeister-config")


def _nested(path: Path) -> None:
    """A child linked worktree owns a separate record that recursive deletion would strand."""
    for directory, names, files in os.walk(path):
        names[:] = [name for name in names if name != ".git"]
        link = Path(directory) / ".git"
        if link.parent == path or ".git" not in files or link.is_symlink():
            continue
        value = link.read_text().strip()
        if not value.startswith("gitdir: "):
            continue
        metadata = (link.parent / value.removeprefix("gitdir: ")).resolve()
        pointer = metadata / "gitdir"
        if pointer.is_file() and (metadata / pointer.read_text().strip()).resolve() == link:
            raise SlopmeisterError(f"nested linked worktree {link.parent}, remove it separately")


def _retry(path: Path) -> str:
    return shlex.join([str(ROOT / "bin/slopmeister"), "workspace-remove", str(path), "--force"])


def _remove(path: Path, repo: Path | None) -> int:
    if repo is not None:
        leftover.remove(path, _retry(path), repo)
    else:
        remove_tree(path)
    print(f"workspace removed: {path}; branches kept")
    return 0


def _self(path: Path, repo: Path, args: argparse.Namespace) -> int:
    state = read_inventory(evidence.receipt_path(path).parent) or {}
    plot = state.get("plot")
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
        print(f"workspace cleanup pending; this worker stops now; result in {name}; branches kept")
        return 0
    request = down.Request(str(repo), plot, path.name, args.force, "")
    down._stop_worker(request, repo, path)
    claimed.complete_handback(path, repo)
    args.self = False
    _check(path, repo, args)
    return _remove(path, repo)


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="slopmeister workspace-remove")
    parser.add_argument("path")
    parser.add_argument(
        "--force", action="store_true", help="confirm loss of unchecked or unsaved work"
    )
    parser.add_argument(
        "--self", action="store_true", help="stop the sole calling worker before removal"
    )
    args = parser.parse_args(argv)
    if git_environment.redirect():
        raise SlopmeisterError("Git context overrides are refused for workspace removal")
    try:
        path, repo = _scope(args.path)
        _check(path, repo, args)
        return _self(path, repo, args) if args.self else _remove(path, repo)
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        raise SlopmeisterError(f"workspace removal failed: {error}") from error
