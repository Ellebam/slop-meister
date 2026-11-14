"""The fixed entry retries only its task run and never repeats a failed attempt."""

import json
import subprocess
import sys

import pytest

from tests.integration.session.test_ci_rerun_world import world

REMOTE = "https://github.com/example/project.git"
SHA = "a" * 40


@pytest.fixture
def github(tmp_path):
    return world(tmp_path, "github")


def invoke(world):
    workspace, env, state = world
    entry = workspace / ".agents/skills/ci-rerun/scripts/ci_rerun.py"
    assert entry.is_file(), "session delivery lacks the bounded CI rerun entry"
    result = subprocess.run(
        [sys.executable, str(entry), "--run", "7"],
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    log = state.parent / "calls.jsonl"
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    writes = [call for call in calls if "POST" in call or "PATCH" in call]
    return result, writes


def change(world, **updates):
    state = world[2]
    state.write_text(json.dumps(json.loads(state.read_text()) | updates))


def test_github_retries_failed_jobs_and_reports_final_evidence(github):
    result, writes = invoke(github)
    assert result.returncode == 0, result.stderr
    assert len(writes) == 1
    frames = [json.loads(line) for line in result.stdout.splitlines()]
    assert frames[-1]["result"] == "success"
    assert frames[-1]["jobs"][0]["name"] == "flaky"
    assert frames[-1]["jobs"][0]["result"] == "success"
    assert "https://github.com/example/project/actions/runs/7" in result.stdout


def test_github_foreign_branch_is_refused_without_a_write(github):
    change(github, branch="other-task")
    result, writes = invoke(github)
    assert result.returncode == 1 and "task branch" in result.stderr
    assert writes == []


def test_github_second_failure_is_real_and_not_retried(github):
    change(github, attempt=2, fails_again=True)
    result, writes = invoke(github)
    assert result.returncode == 1 and "already retried" in result.stderr
    assert writes == []
