"""A directory name alone cannot make legacy workspace content disposable."""

import json

import pytest


@pytest.mark.parametrize("recorded", [False, True])
def test_scratch_requires_saved_ownership_before_removal(workspace, invoke, recorded):
    repo, worktree, _ = workspace
    with (repo / ".git/info/exclude").open("a") as stream:
        stream.write(".slopmeister-tmp/\n")
    scratch = worktree / ".slopmeister-tmp"
    scratch.mkdir(mode=0o700)
    note = scratch / "keep.md"
    note.write_text("unrecorded work\n")
    state = repo / ".git/worktrees/scratch/slopmeister-config/state.json"
    saved = json.loads(state.read_text())
    if recorded:
        saved["scratch"] = scratch.name
        state.write_text(json.dumps(saved))
    result = invoke(worktree)
    if recorded:
        assert result.returncode == 0 and not worktree.exists(), result.stderr
    else:
        assert result.returncode != 0 and "ignored work" in result.stderr, (
            result.stdout + result.stderr
        )
        assert note.read_text() == "unrecorded work\n"


def test_nonregular_inventory_refuses_without_blocking(workspace, invoke):
    import os

    repo, worktree, _ = workspace
    state = repo / ".git/worktrees/scratch/slopmeister-config/state.json"
    state.unlink()
    os.mkfifo(state)
    result = invoke(worktree)
    assert result.returncode != 0 and "not a regular file" in result.stderr
    assert worktree.is_dir()


def test_nonregular_claim_refuses_without_blocking(workspace, invoke):
    import os

    repo, worktree, _ = workspace
    receipt = repo / ".git/worktrees/scratch/slopmeister-config/issue.json"
    os.mkfifo(receipt)
    result = invoke(worktree)
    assert result.returncode != 0 and "claim evidence must be a regular file" in result.stderr
    assert worktree.is_dir() and receipt.exists()
