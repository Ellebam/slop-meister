"""Keep a worktree whose issue claim is active, its removal deletes the record that releases it."""

from pathlib import Path
import stat
import subprocess

from slopmeister.claims import cli, evidence
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
            f"(phase {saved.get('phase')}), refusing. Harvest the task or release the claim: "
            f"task plot-session -- {root} {target} {worktree.name} --abandon "
            "--handoff <absolute-task-notes> --tool <tool>"
        )


def handback_recorded(worktree: Path, root: Path | None = None) -> bool:
    """A worker ending with an unfinished ticket recorded its hand-back. Only the self path
    admits it, and completes it after the worker stopped, so the recorded handoff must still be
    the file it digested. Anything unreadable is left to the ordinary refusal."""
    try:
        path = _receipt(worktree, root)
        saved = evidence.read(path) if path and path.exists() else None
    except ValueError, OSError, subprocess.TimeoutExpired:
        return False
    return saved is not None and saved.get("phase") == "abandoning" and _handoff_intact(saved)


def _handoff_intact(saved: dict) -> bool:
    handoff = saved.get("handoff")
    if not isinstance(handoff, dict) or not isinstance(handoff.get("path"), str):
        return False
    try:
        path = evidence.safe_path(handoff["path"]).resolve()
        inside = path.is_relative_to(Path(saved["workspace"]).resolve())
        # Only a regular file is digested. A pipe or device in its place would block the read.
        regular = stat.S_ISREG(path.lstat().st_mode)
        return inside and regular and evidence.digest(path) == handoff.get("sha256")
    except ValueError, OSError, KeyError:
        return False


def complete_handback(worktree: Path, root: Path | None = None) -> None:
    """After the sole worker stopped, finish the hand-back it recorded, so the ordinary claim
    check below admits the removal. Other phases are left to that check."""
    path = _receipt(worktree, root)
    saved = evidence.read(path) if path and path.exists() else None
    if saved is None or saved.get("phase") != "abandoning":
        return
    if not _handoff_intact(saved):
        raise SlopmeisterError(f"recorded hand-back of {worktree} changed, claim preserved")
    arguments = ["abandon-complete", "--workspace", str(worktree), "--handoff"]
    if cli.main([*arguments, saved["handoff"]["path"]]) != 0:
        raise SlopmeisterError(f"claim hand-back of {worktree} failed, claim preserved")
