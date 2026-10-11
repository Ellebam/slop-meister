"""Public slot teardown removes read-only content and releases a directory Git let go of."""

from pathlib import Path
import re
import shlex
import stat

from tests.integration.slots.test_public_commands import _task, _world
from tests.support.repos import git

NAME = "slopmeister-one"
IDENTITY = f"SLOT=1\nSLOT_TARGET=slopmeister\nSLOT_NAME={NAME}\n"


def _readonly_tree(directory: Path, outside: Path) -> None:
    """What a Go module cache leaves: files and directories without owner write permission."""
    cache = directory / "tmp/go-mod/pkg"
    cache.mkdir(parents=True)
    (cache / "module.go").write_text("package pkg\n")
    (cache / "outside-link").symlink_to(outside)
    (cache / "module.go").chmod(0o444)
    for path in (cache, cache.parent):
        path.chmod(0o555)


def _outside(tmp_path: Path) -> Path:
    outside = tmp_path / "outside.txt"
    outside.write_text("unrelated bytes")
    outside.chmod(0o444)
    return outside


def _state(env: dict[str, str]) -> Path:
    state = Path(env["SLOT_STATE_DIR"]) / "slopmeister-slot1"
    state.mkdir(parents=True)
    (state / ".slot.env").write_text(IDENTITY)
    return state


def _down(env, repository, *flags):
    return _task(env, "slot:down", "--", str(repository), "slopmeister", NAME, *flags)


def test_public_down_removes_a_worktree_that_holds_a_readonly_tree(tmp_path):
    """Bug: a Go module cache left the directory on disk, or removal unlocked an outside file."""
    _, repository, env = _world(tmp_path)
    arguments = ("slot:up", "--", str(repository), "slopmeister", NAME, "--tool", "claude")
    up = _task(env, *arguments, input_text="Mode: freeform\nslot scratch\n")
    assert up.returncode == 0, up.stdout + up.stderr
    worktree, outside = repository / ".worktrees" / NAME, _outside(tmp_path)
    with (repository / ".git/info/exclude").open("a") as exclude:
        exclude.write("tmp/\n")
    _readonly_tree(worktree, outside)
    down = _down(env, repository)
    assert down.returncode == 0, down.stdout + down.stderr
    assert "slopmeister-slot1 released, data worktree" in down.stdout
    assert not worktree.exists() and not (tmp_path / "slots/slopmeister-slot1").exists()
    assert NAME not in git(repository, "worktree", "list")
    assert outside.read_text() == "unrelated bytes"
    assert stat.S_IMODE(outside.stat().st_mode) == 0o444


def test_public_down_removes_a_worktree_whose_own_directory_is_readonly(tmp_path):
    """Bug: Git left a stale link in a read-only worktree, and no rerun could finish."""
    _, repository, env = _world(tmp_path)
    arguments = ("slot:up", "--", str(repository), "slopmeister", NAME, "--tool", "claude")
    up = _task(env, *arguments, input_text="Mode: freeform\nslot scratch\n")
    assert up.returncode == 0, up.stdout + up.stderr
    worktree = repository / ".worktrees" / NAME
    worktree.chmod(0o555)
    down = _down(env, repository)
    assert down.returncode == 0, down.stdout + down.stderr
    assert not worktree.exists() and not (tmp_path / "slots/slopmeister-slot1").exists()


def test_public_down_releases_a_leftover_only_after_force(tmp_path):
    """Bug: a half-removed worktree kept its slot claimed, or was deleted unconfirmed."""
    _, repository, env = _world(tmp_path)
    leftover, state = repository / ".worktrees" / NAME, _state(env)
    _readonly_tree(leftover, _outside(tmp_path))
    refused = _down(env, repository, "--slot", "1")
    assert refused.returncode != 0 and leftover.is_dir() and state.is_dir()
    printed = re.search(r"run: (task slot:down -- .* --slot 1 --force)$", refused.stderr, re.M)
    assert printed, refused.stderr
    released = _task(env, *shlex.split(printed.group(1))[1:])
    assert released.returncode == 0, released.stdout + released.stderr
    assert not leftover.exists() and not state.exists()


def test_public_down_never_follows_a_link_at_the_worktree_path(tmp_path):
    """Bug: leftover removal deleted or unlocked a directory outside the worktree."""
    _, repository, env = _world(tmp_path)
    target, state = tmp_path / "elsewhere", _state(env)
    target.mkdir()
    (target / "kept.txt").write_text("kept bytes")
    target.chmod(0o555)
    (repository / ".worktrees").mkdir()
    (repository / ".worktrees" / NAME).symlink_to(target, target_is_directory=True)
    try:
        result = _down(env, repository, "--slot", "1", "--force")
        assert result.returncode != 0 and "is a symlink and is never followed" in result.stderr
        assert (target / "kept.txt").read_text() == "kept bytes"
        assert stat.S_IMODE(target.stat().st_mode) == 0o555
        assert state.is_dir()
    finally:
        target.chmod(0o700)
