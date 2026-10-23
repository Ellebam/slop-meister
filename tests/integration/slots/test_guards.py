"""Invalid slot launch inputs stop before an allocation or terminal can be created."""

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
