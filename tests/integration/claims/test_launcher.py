"""Claim-aware launcher behavior against native and GitHub doubles."""

import json
from pathlib import Path
import subprocess
import time

import pytest

from tests.integration.claims.helpers import writes
from tests.support.claims_world import SLOPMEISTER

pytestmark = pytest.mark.xdist_group("claims")


@pytest.mark.parametrize("tool", ["claude", "codex"])
def test_stdin_dispatch_claims_only_after_native_delivery_and_alias_observation(world, tool):
    root, repo, env, worker, launch, cli = world
    process, workspace = worker("slopmeister-7-work", tool)
    result = launch("slopmeister-7-work", tool, "--issue-id", "7", "--model", "alias")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "issue claimed: owner/project#7" in result.stdout
    assert process.poll() is None
    assert len(writes(root)) == 1 and writes(root)[0]["native"]
    record = Path(json.loads((root / "native.json").read_text())["path"]).read_text()
    rows = [json.loads(line)["type"] for line in record.splitlines()]
    assert tool == "claude" or rows.index("turn_context") < rows.index("response_item")
    report = cli("backlog", "--repo", repo, "--plot", "slopmeister", "--json")
    assert report.returncode == 0, report.stderr
    assert json.loads(report.stdout)["issues"][0]["category"] == "claimed"
    assert not json.loads(report.stdout)["recommend"]


@pytest.mark.parametrize("tool", ["claude", "codex"])
@pytest.mark.parametrize("failure", ["write_failure", "model_absent", "undelivered"])
def test_unconfirmed_dispatch_keeps_worker_and_never_recommends_issue(world, tool, failure):
    root, repo, env, worker, launch, cli = world
    (root / "case.json").write_text(json.dumps({failure: True}))
    process, workspace = worker("slopmeister-7-work", tool)
    result = launch("slopmeister-7-work", tool, "--issue-id", "7", "--model", "alias")
    assert result.returncode != 0
    assert process.poll() is None
    if failure == "write_failure":
        assert "worker delivered, claim unconfirmed" in result.stderr
    else:
        assert not writes(root)
    report = cli("backlog", "--repo", repo, "--plot", "slopmeister", "--json")
    assert report.returncode == 0, report.stderr
    assert json.loads(report.stdout)["issues"][0]["category"] == "unknown"
    assert not json.loads(report.stdout)["recommend"]


def test_custom_stdin_without_identifier_never_writes_issue(world):
    root, repo, env, worker, launch, cli = world
    worker("slopmeister-7-work", "claude")
    result = launch("slopmeister-7-work", "claude")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (root / "github.log").exists()


@pytest.mark.parametrize("tool", ["claude", "codex"])
def test_redispatch_and_gate_pauses_keep_one_claim_transition(world, tool):
    root, repo, env, worker, launch, cli = world
    old, workspace = worker("slopmeister-7-work", tool)
    first = launch("slopmeister-7-work", tool, "--issue-id", "7", "--model", "alias")
    assert first.returncode == 0, first.stdout + first.stderr
    for gate in ("frame", "plan", "review", "testing"):
        (workspace / "SLOPMEISTER-7-NOTES.md").write_text("Paused for " + gate + "\n")
        report = cli("backlog", "--repo", repo, "--plot", "slopmeister", "--json")
        assert json.loads(report.stdout)["issues"][0]["category"] == "claimed", report.stderr
    new, _ = worker("slopmeister-7-work", tool)
    resumed = launch("slopmeister-7-work", tool, "--redispatch", "--model", "alias")
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert old.poll() is not None and new.poll() is None
    assert len(writes(root)) == 1


def test_abandon_preserves_handoff_and_retries_failed_release(world):
    root, repo, env, worker, launch, cli = world
    old, workspace = worker("slopmeister-7-work", "claude")
    first = launch("slopmeister-7-work", "claude", "--issue-id", "7", "--model", "alias")
    assert first.returncode == 0, first.stdout + first.stderr
    handoff = workspace / "SLOPMEISTER-7-NOTES.md"
    handoff.write_text("Saved work and recovery commands.\n")
    (root / "case.json").write_text('{"write_failure":true}')
    failed = launch("slopmeister-7-work", "claude", "--abandon", "--handoff", str(handoff))
    assert failed.returncode != 0 and old.poll() is not None, failed.stdout + failed.stderr
    assert json.loads((root / "remote.json").read_text())["labels"]
    (root / "case.json").write_text("{}")
    retried = launch("slopmeister-7-work", "claude", "--abandon", "--handoff", str(handoff))
    assert retried.returncode == 0, retried.stdout + retried.stderr
    assert handoff.read_text() == "Saved work and recovery commands.\n"
    remote = json.loads((root / "remote.json").read_text())
    assert remote["state"] == "open" and not remote["labels"]
    report = json.loads(cli("backlog", "--repo", repo, "--plot", "slopmeister", "--json").stdout)
    assert report["recommend"] == [7]


def test_concurrent_fresh_dispatch_has_one_worker_and_one_refusal(world):
    root, repo, env, worker, launch, cli = world
    winner, _ = worker("slopmeister-7-first", "claude")
    worker("slopmeister-7-second", "claude")
    (root / "case.json").write_text('{"hold":true}')
    first = _held_launch(root, repo, env)
    try:
        _wait_until_held(root, first)
        second = launch("slopmeister-7-second", "claude", "--issue-id", "7", "--model", "alias")
        assert second.returncode != 0 and "busy" in second.stderr
        assert not (repo / ".worktrees/slopmeister-7-second").exists()
    finally:
        (root / "continue").touch()
        out, err = first.communicate(timeout=30)
    assert first.returncode == 0, out + err
    second = launch("slopmeister-7-second", "claude", "--issue-id", "7", "--model", "alias")
    assert second.returncode != 0
    assert winner.poll() is None and len(writes(root)) == 1


def _held_launch(root, repo, env):
    args = [
        str(SLOPMEISTER / "bin/slopmeister"),
        "plot-session",
        str(repo),
        "slopmeister",
        "slopmeister-7-first",
        "--issue-id",
        "7",
        "--model",
        "alias",
    ]
    process = subprocess.Popen(
        args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    process.stdin.write("Mode: spine\nFixture work.\n")
    process.stdin.close()
    process.stdin = None
    return process


def _wait_until_held(root, process):
    deadline = time.monotonic() + 30
    while not (root / "held").exists() and process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.02)
    assert (root / "held").exists(), process.communicate(timeout=2)


@pytest.mark.parametrize(
    "setting",
    [
        'shipping="deny"',
        'shipping="allow"\nunused=true',
        "manual",
        "vault",
        "omitted",
        "commit-deny",
    ],
)
def test_existing_permission_or_source_denial_performs_no_tracker_writes(world, setting):
    root, repo, env, worker, launch, cli = world
    path = root / "plots/slopmeister/plot.toml"
    text = path.read_text()
    if setting in ("manual", "vault"):
        text = text.replace('tasks="github"', f'tasks="{setting}"')
    elif setting == "omitted":
        text = text.replace('shipping="allow"\n', "")
    elif setting == "commit-deny":
        text = text.replace('commit="allow"', 'commit="deny"').replace(
            'shipping="allow"', 'shipping="deny"'
        )
    else:
        text = text.replace('shipping="allow"', setting)
    path.write_text(text)
    worker("slopmeister-7-work", "claude")
    result = launch("slopmeister-7-work", "claude", "--issue-id", "7")
    assert (result.returncode == 0) == (setting in ('shipping="deny"', "omitted", "commit-deny")), (
        result.stdout + result.stderr
    )
    assert not (root / "github.log").exists()


def test_native_dependencies_block_recommendations_but_allow_explicit_dispatch(world):
    root, repo, env, worker, launch, cli = world
    (root / "case.json").write_text(json.dumps(dict(dependencies=[dict(number=3, state="open")])))
    report = cli("backlog", "--repo", repo, "--plot", "slopmeister", "--json")
    assert json.loads(report.stdout)["issues"][0]["category"] == "blocked"
    worker("slopmeister-7-work", "claude")
    result = launch("slopmeister-7-work", "claude", "--issue-id", "7")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "blocked" in result.stderr


def test_foreign_project_finalize_uses_absolute_helper_and_clears_claim(world):
    root, repo, env, worker, launch, cli = world
    _, workspace = worker("slopmeister-7-work", "claude")
    result = launch("slopmeister-7-work", "claude", "--issue-id", "7")
    assert result.returncode == 0, result.stdout + result.stderr
    closed = subprocess.run(
        [str(SLOPMEISTER / "bin/slopmeister"), "claims", "close", "--workspace", str(workspace)],
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
    )
    assert closed.returncode == 0, closed.stderr
    remote = json.loads((root / "remote.json").read_text())
    assert remote["state"] == "closed" and not remote["labels"]


def test_finalize_close_ignores_harness_git_variables_and_refuses_a_redirect(world):
    """Bug: claims close refused until harness-injected Git variables were unset by hand."""
    root, repo, env, worker, launch, cli = world
    _, workspace = worker("slopmeister-7-work", "claude")
    result = launch("slopmeister-7-work", "claude", "--issue-id", "7")
    assert result.returncode == 0, result.stdout + result.stderr
    harness = dict(
        GIT_CONFIG_COUNT="1",
        GIT_CONFIG_KEY_0="credential.helper",
        GIT_CONFIG_VALUE_0="x",
        GIT_ASKPASS="/bin/true",
    )
    command = [str(SLOPMEISTER / "bin/slopmeister"), "claims", "close", "--workspace"]
    command.append(str(workspace))
    redirected = subprocess.run(
        command, env={**env, **harness, "GIT_DIR": "/tmp/x"}, capture_output=True, text=True
    )
    assert redirected.returncode == 1 and "not allowed for issue management" in redirected.stderr
    assert json.loads((root / "remote.json").read_text())["state"] == "open"
    closed = subprocess.run(command, env={**env, **harness}, capture_output=True, text=True)
    assert closed.returncode == 0, closed.stderr
    remote = json.loads((root / "remote.json").read_text())
    assert remote["state"] == "closed" and not remote["labels"]
