"""Slot guards reject unsafe inputs and foreign allocations before mutation."""

from pathlib import Path

import pytest

from tests.integration.slots.test_public_commands import _task, _world


@pytest.mark.parametrize("kind", ["native-identity", "nested-root"])
def test_invalid_launch_never_reaches_allocation(tmp_path, kind):
    _, repository, env = _world(tmp_path)
    state = Path(env["SLOT_STATE_DIR"])
    state.write_text("allocation sentinel")
    repo, tail = repository, ["--tool", "claude", "--", "--session-id=other"]
    if kind == "nested-root":
        repo = repository / "nested"
        repo.mkdir()
        tail = []
    result = _task(
        env,
        "slot:up",
        "--",
        str(repo),
        "slopmeister",
        "slopmeister-one",
        *tail,
        input_text="Mode: freeform\nguard fixture\n",
    )
    expected = (
        "override Slopmeister-owned"
        if kind == "native-identity"
        else "not a non-bare git repository"
    )
    assert result.returncode != 0 and expected in result.stderr
    assert state.read_text() == "allocation sentinel"
    assert not (repository / ".worktrees").exists()


def test_public_down_by_number_refuses_another_live_slot(tmp_path):
    """Bug: a mistyped missing name tore resources out from under another live slot."""
    _, repository, env = _world(tmp_path)
    worktree = repository / ".worktrees/slopmeister-other"
    data = Path(env["SLOT_STATE_DIR"]) / "slopmeister-slot2"
    allocation = "SLOT=2\nSLOT_TARGET=slopmeister\nSLOT_NAME=slopmeister-other\n"
    worktree.mkdir(parents=True)
    data.mkdir(parents=True)
    (worktree / ".slot.env").write_text(allocation)
    result = _task(
        env,
        "slot:down",
        "--",
        str(repository),
        "slopmeister",
        "slopmeister-typo",
        "--slot",
        "2",
    )
    assert result.returncode != 0 and "slot 2" in result.stderr and "live" in result.stderr
    assert worktree.is_dir() and data.is_dir()
