"""Reverse a slot allocation whose launch failed before a worker could open."""

from __future__ import annotations

import shutil
import sys

from slopmeister.slots import allocation


def _delivered(claim: allocation.Claim) -> bool:
    """The worktree carries this run's allocation, so this run created it and its branch."""
    try:
        delivered = (claim.live.worktree / allocation.ALLOCATION).read_bytes()
        return delivered == (claim.data / allocation.ALLOCATION).read_bytes()
    except OSError:
        return False


def run(claim: allocation.Claim, start: str) -> None:
    project = f"{claim.live.target}-slot{claim.live.slot}"
    print(f"slot: up failed, releasing {project}", file=sys.stderr)
    if claim.compose:
        allocation.remove_project(project)
    worktree = claim.live.worktree
    root = worktree.parent.parent
    own = bool(start) and _delivered(claim)
    if worktree.is_dir():
        allocation.run(
            ["git", "-C", str(root), "worktree", "remove", "--force", str(worktree)],
            ok=False,
        )
        shutil.rmtree(worktree, ignore_errors=True)
        allocation.run(["git", "-C", str(root), "worktree", "prune"])
    if own:
        # Git deletes the branch only while it still points at the commit it was created from.
        ref = f"refs/heads/{claim.live.name}"
        allocation.run(
            ["git", "-C", str(root), "update-ref", "-d", ref, start], capture=True, ok=False
        )
    shutil.rmtree(claim.data, ignore_errors=True)
