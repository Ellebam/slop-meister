"""A failed slot:up can be retried, and slot:down keeps a claimed worktree."""

import json

from tests.integration.launch.helpers import executable
from tests.integration.slots.test_public_commands import _compose_world, _task, _world


def test_failed_compose_releases_the_name_for_a_retry(tmp_path):
    """Bug: a failed slot:up kept its branch, so the same command and name were refused."""
    _, repository, env, _ = _compose_world(tmp_path)
    working = (tmp_path / "bin/docker").read_text()
    broken = working.replace("  compose)\n", "  compose) exit 1 ;;\n  compose)\n", 1)
    arguments = ("slot:up", "--", str(repository), "slopmeister", "slopmeister-one")
    executable(tmp_path / "bin/docker", broken)
    failed = _task(env, *arguments, input_text="Mode: freeform\ncompose fixture\n")
    assert failed.returncode != 0 and "releasing slopmeister-slot1" in failed.stderr
    assert not (repository / ".worktrees/slopmeister-one").exists()
    executable(tmp_path / "bin/docker", working)
    retried = _task(env, *arguments, input_text="Mode: freeform\ncompose fixture\n")
    assert retried.returncode == 0, retried.stdout + retried.stderr
    assert (repository / ".worktrees/slopmeister-one/.slot.env").is_file()


def test_public_down_keeps_a_worktree_whose_claim_is_active(tmp_path):
    """Bug: slot:down removed a claimed worktree and orphaned agent:claimed on its issue."""
    _, repository, env = _world(tmp_path)
    arguments = ("--", str(repository), "slopmeister", "slopmeister-one")
    up = _task(env, "slot:up", *arguments, input_text="Mode: freeform\nslot fixture\n")
    assert up.returncode == 0, up.stdout + up.stderr
    worktree = repository / ".worktrees/slopmeister-one"
    receipt = repository / ".git/worktrees/slopmeister-one/slopmeister-config/issue.json"
    for phase in ("claimed", "closing"):
        receipt.write_text(json.dumps({"issue": 7, "phase": phase}))
        down = _task(env, "slot:down", *arguments)
        assert down.returncode != 0 and "--abandon" in down.stderr, down.stdout + down.stderr
        assert worktree.is_dir()
    receipt.write_text(json.dumps({"issue": 7, "phase": "closed"}))
    down = _task(env, "slot:down", *arguments)
    assert down.returncode == 0, down.stdout + down.stderr
    assert not worktree.exists()
