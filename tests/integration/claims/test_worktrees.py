"""Worktree and process findings warn and never decide another issue's ownership."""

import json
import shutil
import subprocess

import pytest

from tests.integration.claims.helpers import writes

pytestmark = pytest.mark.xdist_group("claims")


def _backlog(cli, repo):
    return json.loads(cli("backlog", "--repo", repo, "--plot", "slopmeister", "--json").stdout)


def _serve_next_issue(root):
    (root / "remote.json").write_text(
        json.dumps(dict(number=8, state="open", title="Next work", labels=[]))
    )


def _occupy(root, worker, name):
    process, _ = worker(name, "claude")
    (root / (str(process.pid) + ".started")).touch()


def test_hand_resumed_finisher_does_not_block_another_issue(world):
    root, repo, env, worker, launch, cli = world
    old, workspace = worker("slopmeister-7-work", "claude")
    assert launch("slopmeister-7-work", "claude", "--issue-id", "7").returncode == 0
    assert cli("close", "--workspace", workspace).returncode == 0
    old.terminate()
    old.wait(timeout=5)
    _occupy(root, worker, "slopmeister-7-work")
    _serve_next_issue(root)
    report = _backlog(cli, repo)
    assert report["recommend"] == [8] and str(workspace) in report["warnings"][0]
    worker("slopmeister-8-next", "claude")
    result = launch("slopmeister-8-next", "claude", "--issue-id", "8")
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("original_ends", [True, False])
def test_claimed_issue_stays_claimed_when_its_process_changes(world, original_ends):
    root, repo, env, worker, launch, cli = world
    old, _ = worker("slopmeister-7-work", "claude")
    assert launch("slopmeister-7-work", "claude", "--issue-id", "7").returncode == 0
    if original_ends:
        old.terminate()
        old.wait(timeout=5)
    _occupy(root, worker, "slopmeister-7-work")
    report = _backlog(cli, repo)
    assert report["issues"][0]["category"] == "claimed" and not report["issues"][0]["reasons"]
    assert not report["warnings"]
    worker("slopmeister-7-second", "claude")
    second = launch("slopmeister-7-second", "claude", "--issue-id", "7")
    assert second.returncode != 0 and len(writes(root)) == 1


def _lose(workspace, recreated):
    shutil.rmtree(workspace)
    if recreated:
        workspace.mkdir()
    if recreated == "repository":
        subprocess.run(["git", "-C", str(workspace), "init", "-q"], check=True)


@pytest.mark.parametrize("recreated", [False, True])
def test_deleted_worktree_directory_warns_and_blocks_no_dispatch(world, recreated):
    root, repo, env, worker, launch, cli = world
    workspace = repo / ".worktrees/gone"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-qb", "gone", str(workspace)],
        check=True,
        capture_output=True,
    )
    _lose(workspace, recreated)
    report = _backlog(cli, repo)
    assert report["recommend"] == [7]
    finding = "unassociated worktree" if recreated else "worktree directory is missing"
    assert report["warnings"][0].startswith(f"{finding} at {workspace}")
    worker("slopmeister-7-work", "claude")
    result = launch("slopmeister-7-work", "claude", "--issue-id", "7")
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("recreated", [False, True, "repository"])
def test_unconfirmed_claim_survives_a_deleted_worktree_directory(world, recreated):
    root, repo, env, worker, launch, cli = world
    (root / "case.json").write_text('{"write_failure":true}')
    _, workspace = worker("slopmeister-7-work", "claude")
    assert launch("slopmeister-7-work", "claude", "--issue-id", "7").returncode != 0
    (root / "case.json").write_text("{}")
    _lose(workspace, recreated)
    report = _backlog(cli, repo)
    assert report["issues"][0]["reasons"] == ["local worker and GitHub claim disagree"]
    assert not report["recommend"]
    assert recreated or str(workspace) in report["warnings"][0]
    worker("slopmeister-7-second", "claude")
    assert launch("slopmeister-7-second", "claude", "--issue-id", "7").returncode != 0
    # The deleted owner's receipt names issue 7 only, another issue stays dispatchable.
    _serve_next_issue(root)
    assert _backlog(cli, repo)["recommend"] == [8]
