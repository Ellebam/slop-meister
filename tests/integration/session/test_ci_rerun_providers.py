"""Provider-independent authority and recovery at the actual delivered entry."""

import json

import pytest

from tests.integration.session.test_ci_rerun import change, invoke
from tests.integration.session.test_ci_rerun_world import world
from tests.support.repos import git


@pytest.fixture(params=["github", "gitlab", "azure"])
def provider(request, tmp_path):
    return request.param, world(tmp_path, request.param)


def test_provider_retry_reports_only_restarted_jobs(provider):
    name, fixture = provider
    result, _ = invoke(fixture)
    assert result.returncode == 0, result.stderr
    frames = [json.loads(line) for line in result.stdout.splitlines()]
    assert frames[-1]["result"] == ("succeeded" if name == "azure" else "success")
    assert [job["name"] for job in frames[-1]["jobs"]] == ["flaky"]
    assert "status_command" in frames[0]
    assert fixture[2].read_text().find('"attempt": 2') >= 0


@pytest.mark.parametrize("case", ["foreign", "repeated", "other_repository", "uncertain"])
def test_provider_authority_and_uncertain_write_stop(provider, case):
    name, fixture = provider
    updates = {
        "foreign": dict(branch="other-task"),
        "repeated": dict(attempt=2, fails_again=True),
        "other_repository": dict(repository_id=999),
        "uncertain": dict(uncertain=True),
    }
    change(fixture, **updates[case])
    result, _ = invoke(fixture)
    reason = {
        "foreign": "task branch",
        "repeated": "already retried",
        "other_repository": "another repository",
        "uncertain": "no write was retried",
    }[case]
    assert result.returncode == 1 and reason in result.stderr, result.stdout + result.stderr
    assert "sensitive-provider-diagnostic" not in result.stderr
    calls = [
        json.loads(line) for line in (fixture[2].parent / "calls.jsonl").read_text().splitlines()
    ]
    writes = [call for call in calls if "POST" in call or "PATCH" in call]
    assert len(writes) == (1 if case == "uncertain" else 0)


@pytest.mark.parametrize("merged", [True, False])
def test_default_branch_requires_exact_own_merge_push(provider, merged):
    name, fixture = provider
    change(fixture, branch="main", head_sha="b" * 40, merged=merged)
    result, writes = invoke(fixture)
    assert result.returncode == (0 if merged else 1), result.stdout + result.stderr
    if not merged:
        assert "exact merge push" in result.stderr
        assert writes == []


def test_scheduled_default_commit_cannot_borrow_merge_authority(provider):
    _, fixture = provider
    change(fixture, branch="main", head_sha="b" * 40, merged=True, event="schedule")
    result, writes = invoke(fixture)
    assert result.returncode == 1 and "exact merge push" in result.stderr
    assert writes == []


def test_changed_origin_is_refused_before_provider_access(provider):
    _, fixture = provider
    git(fixture[0], "remote", "set-url", "origin", "https://github.com/other/project.git")
    result, writes = invoke(fixture)
    assert result.returncode == 1 and "origin differs" in result.stderr
    assert writes == [] and not (fixture[2].parent / "calls.jsonl").exists()


def test_modified_snapshot_is_refused_before_provider_access(provider):
    _, fixture = provider
    directory = git(fixture[0], "rev-parse", "--absolute-git-dir").strip()
    from pathlib import Path

    runtime = Path(directory) / "slopmeister-config/snapshot/slopmeister/session/ship.py"
    runtime.write_text(runtime.read_text() + "\n# changed\n")
    result, _ = invoke(fixture)
    assert result.returncode == 1 and "runtime snapshot changed" in result.stderr
    assert not (fixture[2].parent / "calls.jsonl").exists()


@pytest.mark.parametrize("case", ["own", "fork", "unrelated_pipeline"])
def test_gitlab_merge_request_binds_source_repository_and_pipeline(tmp_path, case):
    fixture = world(tmp_path, "gitlab")
    change(
        fixture,
        event="merge_request_event",
        mr=True,
        mr_source_project=999 if case == "fork" else 1,
        mr_pipeline_member=case != "unrelated_pipeline",
    )
    result, writes = invoke(fixture)
    assert result.returncode == (0 if case == "own" else 1), result.stdout + result.stderr
    if case != "own":
        assert "merge-request run" in result.stderr and writes == []
