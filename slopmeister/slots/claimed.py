"""Keep a worktree whose issue claim is active, its removal deletes the record that releases it."""

from pathlib import Path
import subprocess

from slopmeister.claims import evidence
from slopmeister.errors import SlopmeisterError


def _receipt(worktree: Path, root: Path | None = None) -> Path | None:
    """The association lives in the repository's metadata, also once the worktree lost its link."""
    root = root or worktree.parent.parent
    for pointer in (root / ".git").glob("worktrees/*/gitdir"):
        value = evidence.safe_path(pointer).read_text().strip()
        if (pointer.parent / value).parent.resolve() == worktree.resolve():
            return pointer.parent / evidence.RECEIPT
    link = worktree / ".git"
    if link.exists():
        try:
            return evidence.receipt_path(worktree)
        except ValueError:
            value = link.read_text().strip()
            destination = (worktree / value.removeprefix("gitdir: ")).resolve()
            if not value.startswith("gitdir: ") or destination.exists():
                raise
            if destination.parent != (root / ".git/worktrees").resolve():
                raise
    return None


def refuse(worktree: Path, target: str, root: Path | None = None) -> None:
    try:
        path = _receipt(worktree, root)
        saved = evidence.read(path) if path and (path.exists() or path.is_symlink()) else None
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        raise SlopmeisterError(
            f"cannot read the issue association of {worktree}, refusing: {error}"
        ) from error
    # Any phase but the two finished ones keeps the worktree, an unknown one may hide an owner.
    if saved is not None and saved.get("phase") not in ("released", "closed"):
        root = worktree.parent.parent
        raise SlopmeisterError(
            f"worktree {worktree} still holds the claim on issue {saved.get('issue')} "
            f"(phase {saved.get('phase')}), refusing. Finalize the task, or release the claim: "
            f"task plot-session -- {root} {target} {worktree.name} --abandon "
            "--handoff <absolute-task-notes> --tool <tool>"
        )
