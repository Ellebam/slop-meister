"""Recovery refuses worker and repository identity drift."""

import json
import subprocess

import pytest

from tests.integration.claims.helpers import receipt, writes

pytestmark = pytest.mark.xdist_group("claims")


@pytest.mark.parametrize("fault", ["issue", "tasks", "origin", "handoff", "pid", "thread"])
def test_recovery_refuses_identity_drift_without_closing_worker(world, fault):
    root, repo, env, worker, launch, cli = world
    old, workspace = worker("slopmeister-7-work", "claude")
    first = launch("slopmeister-7-work", "claude", "--issue-id", "7")
    assert first.returncode == 0, first.stderr
    handoff = workspace / "SLOPMEISTER-7-NOTES.md"
    handoff.write_text("Recovery commands.\n")
    args = _drift(world, fault, old, workspace, handoff)
    result = launch("slopmeister-7-work", "claude", *args)
    assert result.returncode != 0, result.stdout + result.stderr
    assert old.poll() is None and len(writes(root)) == 1


def _drift(world, fault, old, workspace, handoff):
    root, repo, env, worker, launch, cli = world
    args = (
        ["--redispatch", "--issue-id", "8"]
        if fault == "issue"
        else ["--abandon", "--handoff", str(handoff)]
    )
    match fault:
        case "tasks":
            _change_tasks(root)
            return ["--redispatch"]
        case "origin":
            _change_origin(repo)
        case "handoff":
            handoff.unlink()
        case "pid" | "thread":
            _change_worker_identity(root, worker, old, workspace, fault)
    return args


def _change_tasks(root):
    path = root / "plots/slopmeister/plot.toml"
    path.write_text(path.read_text().replace('tasks="github"', 'tasks="manual"'))


def _change_origin(repo):
    command = ["git", "-C", str(repo), "remote", "set-url", "--push", "origin"]
    subprocess.run([*command, "git@github.com:owner/other.git"], check=True)


def _change_worker_identity(root, worker, old, workspace, fault):
    path = receipt(workspace)
    saved = json.loads(path.read_text())
    if fault == "pid":
        saved["delivery"]["pid_start"] = "wrong"
    else:
        worker("slopmeister-7-work", "claude")
        for record in root.glob("worker-*.json"):
            item = json.loads(record.read_text())
            if item["pid"] != old.pid:
                (root / (str(item["pid"]) + ".started")).touch()
    path.write_text(json.dumps(saved))


def test_failed_claim_reconciles_but_refuses_replacement_identity(world):
    root, repo, env, worker, launch, cli = world
    (root / "case.json").write_text('{"write_failure":true}')
    old, workspace = worker("slopmeister-7-work", "claude")
    assert launch("slopmeister-7-work", "claude", "--issue-id", "7").returncode != 0
    (root / "case.json").write_text("{}")
    path = receipt(workspace)
    saved = json.loads(path.read_text())
    saved["delivery"]["pid_start"] = "wrong"
    path.write_text(json.dumps(saved))
    result = cli("reconcile", "--workspace", workspace)
    assert result.returncode != 0, result.stdout + result.stderr
    assert not json.loads((root / "remote.json").read_text())["labels"]
    saved["delivery"]["pid_start"] = "fixture-start claude"
    path.write_text(json.dumps(saved))
    result = cli("reconcile", "--workspace", workspace)
    assert result.returncode == 0, result.stderr
    assert old.poll() is None and json.loads((root / "remote.json").read_text())["labels"]
