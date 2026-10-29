"""A worker ending with an unfinished ticket hands its claim back through its handoff copy."""

import json

from tests.integration.claims.helpers import receipt, writes
from tests.support.claims_world import SLOPMEISTER


def _remove(env, workspace, *flags):
    import subprocess

    command = [str(SLOPMEISTER / "bin/slopmeister"), "workspace-remove", str(workspace), *flags]
    return subprocess.run(command, capture_output=True, text=True, env=env, timeout=60)


def _recorded_handback(world):
    """A claimed worker that wrote its handoff copy and recorded the hand-back, as harvest does."""
    root, repo, env, worker, launch, cli = world
    process, workspace = worker("slopmeister-7-work", "claude")
    started = launch("slopmeister-7-work", "claude", "--issue-id", "7", "--model", "alias")
    assert started.returncode == 0, started.stdout + started.stderr
    notes = workspace / "SLOPMEISTER-7-NOTES.md"
    notes.write_text("Handoff: the second criterion is open, resume from the branch.\n")
    copy = workspace / ".slopmeister-tmp" / "SLOPMEISTER-7-handoff.md"
    copy.parent.mkdir(exist_ok=True)
    copy.write_bytes(notes.read_bytes())
    prepared = cli("abandon-prepare", "--workspace", workspace, "--handoff", copy)
    assert prepared.returncode == 0, prepared.stdout + prepared.stderr
    notes.unlink()
    assert json.loads(receipt(workspace).read_text())["phase"] == "abandoning"
    return process, workspace, copy


def test_unfinished_ticket_releases_its_claim_before_the_worktree_goes(world):
    """Bug: removal refused the abandoning receipt, so the ticket stayed claimed for good."""
    root, repo, env, worker, launch, cli = world
    process, workspace, copy = _recorded_handback(world)
    refused = _remove(env, workspace)
    assert refused.returncode != 0 and "phase abandoning" in refused.stderr
    process.terminate()
    process.wait(timeout=30)
    completed = cli("abandon-complete", "--workspace", workspace, "--handoff", copy)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert json.loads(receipt(workspace).read_text())["phase"] == "released"
    remote = json.loads((root / "remote.json").read_text())
    assert remote["state"] == "open" and not remote["labels"]
    assert [x["method"] for x in writes(root)][-1] == "DELETE"
    removed = _remove(env, workspace)
    assert removed.returncode == 0, removed.stdout + removed.stderr
    assert not workspace.exists()
