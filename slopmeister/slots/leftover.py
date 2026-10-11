"""Release a slot whose worktree Git no longer knows, and remove what Git could not delete."""

from pathlib import Path
import shlex

from slopmeister.errors import SlopmeisterError
from slopmeister.removal import remove_tree
from slopmeister.slots import allocation


def found(worktree: Path) -> bool:
    """A directory Git let go of, neither its Git link nor its allocation is left."""
    names = (".git", allocation.ALLOCATION)
    return worktree.is_dir() and not any((worktree / name).exists() for name in names)


def numbered(worktree: Path, target: str, wanted: str) -> int:
    """The slot an explicit number releases once no live worktree can identify it."""
    if not wanted.isdigit() or not 1 <= int(wanted) <= 99 or len(wanted) > 2:
        raise SlopmeisterError(f"--slot must be a slot number, got '{wanted}'")
    number, root = int(wanted), worktree.parent.parent
    key = target, number
    holder = next((item for item in allocation.live(root) if (item.target, item.slot) == key), None)
    if holder:
        raise SlopmeisterError(f"slot {number} is live as '{holder.name}', refusing")
    identity = allocation.state_path() / f"{target}-slot{number}" / allocation.ALLOCATION
    if identity.is_file():
        item = allocation.read(identity)
        if (item.target, item.slot, item.name) != (target, number, worktree.name):
            raise SlopmeisterError(
                f"the residual allocation names {item.target}-slot{item.slot} for '{item.name}', "
                f"not {target}-slot{number} for '{worktree.name}', refusing"
            )
    return number


def command(worktree: Path, target: str, number: int) -> str:
    root = str(worktree.parent.parent)
    return shlex.join(["task", "slot:down", "--", root, target, worktree.name]) + (
        f" --slot {number} --force"
    )


def confirm(force: bool, rerun: str) -> None:
    """Git cannot report unsaved work in a leftover, so its deletion is always confirmed."""
    if not force:
        raise SlopmeisterError(
            f"the leftover directory cannot be checked for unsaved work, to delete it run: {rerun}"
        )


def _held(worktree: Path, root: Path) -> bool:
    """The owning inventory remains authoritative when the workspace loses its Git link."""
    probe = ["git", "-C", str(root), "worktree", "list", "--porcelain", "-z"]
    result = allocation.run(probe, capture=True)
    for record in result.stdout.split("\0\0"):
        rows = record.split("\0")
        location = next((row[9:] for row in rows if row.startswith("worktree ")), None)
        if location is not None and Path(location).resolve() == worktree.resolve():
            locked = any(row.startswith("locked") for row in rows)
            prunable = any(row.startswith("prunable") for row in rows)
            return locked or not prunable
    return False


def remove(worktree: Path, rerun: str, root: Path | None = None) -> None:
    kept = "Its slot stays claimed. " if root is None else ""
    root = root or worktree.parent.parent
    argv = ["git", "-C", str(root), "worktree", "remove", "--force"]
    result = allocation.run([*argv, str(worktree)], capture=True, ok=False)
    # Git may refuse, a locked worktree for one. Only what it unregistered is deleted.
    if result.returncode and _held(worktree, root):
        raise SlopmeisterError(result.stderr.strip() or "git failed")
    try:
        remove_tree(worktree)
    except FileNotFoundError:
        return
    except OSError as error:
        raise SlopmeisterError(
            f"{worktree} is not fully removed, {error}. {kept}Fix the cause, then run: {rerun}"
        ) from error
