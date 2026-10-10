"""Interrupted and legacy claims recover without replacing workers."""

import json

import pytest

from tests.integration.claims.helpers import receipt, writes

pytestmark = pytest.mark.xdist_group("claims")


def test_repeat_abandon_never_stops_replacement_worker(world):
    root, repo, env, worker, launch, cli = world
    old, workspace = worker("slopmeister-7-work", "claude")
    assert launch("slopmeister-7-work", "claude", "--issue-id", "7").returncode == 0
    handoff = workspace / "SLOPMEISTER-7-NOTES.md"
    handoff.write_text("Recovery evidence.\n")
    assert (
        launch("slopmeister-7-work", "claude", "--abandon", "--handoff", str(handoff)).returncode
        == 0
    )
    new, _ = worker("slopmeister-7-work", "claude")
    (root / (str(new.pid) + ".started")).touch()
    before = writes(root)
    repeated = launch("slopmeister-7-work", "claude", "--abandon", "--handoff", str(handoff))
    assert repeated.returncode == 0, repeated.stderr
    assert new.poll() is None and writes(root) == before
    report = json.loads(cli("backlog", "--repo", repo, "--plot", "slopmeister", "--json").stdout)
    # The replacement holds no claim, so it is reported and blocks nothing.
    assert report["recommend"] == [7] and str(workspace) in report["warnings"][0]


def test_failed_redispatch_reports_missing_delivery_then_recovers(world):
    root, repo, env, worker, launch, cli = world
    old, workspace = worker("slopmeister-7-work", "claude")
    assert launch("slopmeister-7-work", "claude", "--issue-id", "7").returncode == 0
    replacement, _ = worker("slopmeister-7-work", "claude")
    (root / "case.json").write_text('{"undelivered":true}')
    assert launch("slopmeister-7-work", "claude", "--redispatch").returncode != 0
    replacement.terminate()
    replacement.wait(timeout=5)
    report = json.loads(cli("backlog", "--repo", repo, "--plot", "slopmeister", "--json").stdout)
    assert report["issues"][0]["category"] == "unknown" and not report["recommend"]
    failed = cli("reconcile", "--workspace", workspace)
    assert failed.returncode != 0 and "no bound delivery" in failed.stderr
    (root / "case.json").write_text("{}")
    worker("slopmeister-7-work", "claude")
    result = launch("slopmeister-7-work", "claude", "--redispatch")
    assert result.returncode == 0, result.stderr
    assert len(writes(root)) == 1


def test_redispatch_recovers_an_unconfirmed_claim(world):
    root, repo, env, worker, launch, cli = world
    (root / "case.json").write_text('{"write_failure":true}')
    worker("slopmeister-7-work", "claude")
    assert launch("slopmeister-7-work", "claude", "--issue-id", "7").returncode != 0
    (root / "case.json").write_text("{}")
    worker("slopmeister-7-work", "claude")
    result = launch("slopmeister-7-work", "claude", "--redispatch")
    assert result.returncode == 0, result.stderr
    assert json.loads((root / "remote.json").read_text())["labels"]


@pytest.mark.parametrize("config", ["model_reasoning_effort=high", "model=alias"])
def test_codex_literal_config_remains_supported_for_issue_dispatch(world, config):
    root, repo, env, worker, launch, cli = world
    worker("slopmeister-7-work", "codex")
    result = launch("slopmeister-7-work", "codex", "--issue-id", "7", "--", "-c", config)
    assert result.returncode == 0, result.stderr
    assert len(writes(root)) == 1


@pytest.mark.parametrize("tool", ["claude", "codex"])
def test_legacy_workers_can_be_associated_without_relaunching(world, tool):
    root, repo, env, worker, launch, cli = world
    owners = _legacy_workers(root, worker, launch, tool)
    result = cli("reconcile", *_reconcile_args(root, owners[0], 7, tool, "a"))
    assert result.returncode == 0, result.stderr
    assert all(p.poll() is None for p, _, _ in owners)
    assert len(writes(root)) == 1 and receipt(owners[0][1]).exists()
    report = json.loads(cli("backlog", "--repo", repo, "--plot", "slopmeister", "--json").stdout)
    assert not report["recommend"] and report["issues"][0]["category"] == "claimed"
    assert any(str(owners[1][1]) in warning for warning in report["warnings"])
    conflict = cli("reconcile", *_reconcile_args(root, owners[1], 7, tool, "b"))
    assert conflict.returncode != 0 and not receipt(owners[1][1]).exists()
    assert len(writes(root)) == 1
    (root / "remote.json").write_text(
        json.dumps(dict(number=8, state="open", title="Second legacy issue", labels=[]))
    )
    recovered = cli("reconcile", *_reconcile_args(root, owners[1], 8, tool, "b"))
    assert recovered.returncode == 0, recovered.stderr
    assert all(p.poll() is None for p, _, _ in owners) and len(writes(root)) == 2
    report = json.loads(cli("backlog", "--repo", repo, "--plot", "slopmeister", "--json").stdout)
    assert report["issues"][0]["category"] == "claimed" and not report["recommend"]


def _legacy_workers(root, worker, launch, tool):
    owners = []
    for name in ("slopmeister-legacy-a", "slopmeister-legacy-b"):
        process, workspace = worker(name, tool)
        result = launch(name, tool)
        assert result.returncode == 0, result.stderr
        native = json.loads((root / "native.json").read_text())
        owners.append((process, workspace, native))
    return owners


def _reconcile_args(root, owner, issue, tool, suffix):
    process, workspace, native = owner
    return [
        "--workspace",
        workspace,
        "--issue-id",
        issue,
        "--kickoff",
        root / f"state/slopmeister-legacy-{suffix}.md",
        "--tool",
        tool,
        "--pid",
        process.pid,
        "--session",
        native["session"],
        "--evidence",
        native["path"],
    ]


@pytest.mark.parametrize("fault", ["kickoff", "session", "pid", "occupied", "permission"])
def test_legacy_recovery_refuses_unverified_evidence_before_association(world, fault):
    root, repo, env, worker, launch, cli = world
    process, workspace, native, kickoff = _fault_worker(world, fault)
    result = cli("reconcile", *_fault_args(workspace, process, native, kickoff, fault))
    assert result.returncode != 0, result.stdout + result.stderr
    assert not receipt(workspace).exists()
    assert not (root / "github.log").exists() or not writes(root)
    assert process.poll() is None


def _fault_worker(world, fault):
    root, repo, env, worker, launch, cli = world
    process, workspace = worker("slopmeister-legacy", "claude")
    first = launch("slopmeister-legacy", "claude")
    assert first.returncode == 0, first.stderr
    native = json.loads((root / "native.json").read_text())
    kickoff = root / "state/slopmeister-legacy.md"
    if fault == "kickoff":
        kickoff.write_text("Mode: spine\nChanged.\n")
    if fault == "permission":
        path = root / "plots/slopmeister/plot.toml"
        path.write_text(path.read_text().replace('tasks="github"', 'tasks="manual"'))
    if fault == "occupied":
        other, _ = worker("slopmeister-legacy", "claude")
        (root / (str(other.pid) + ".started")).touch()
    return process, workspace, native, kickoff


def _fault_args(workspace, process, native, kickoff, fault):
    return [
        "--workspace",
        workspace,
        "--issue-id",
        7,
        "--kickoff",
        kickoff,
        "--tool",
        "claude",
        "--pid",
        1 if fault == "pid" else process.pid,
        "--session",
        "foreign" if fault == "session" else native["session"],
        "--evidence",
        native["path"],
    ]
