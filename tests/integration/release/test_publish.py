"""Release publication preserves version identity and retries without moving tags."""

import pytest

from tests.integration.release.conftest import ReleaseRepository

BASE = "repos/example/project"
TAG = "v0.1.0"


def tag(sha: str) -> dict:
    return {"ref": f"refs/tags/{TAG}", "object": {"type": "commit", "sha": sha}}


def published(sha: str) -> dict:
    return {
        "tag_name": TAG,
        "target_commitish": sha,
        "draft": False,
        "prerelease": False,
        "published_at": "2026-01-01T00:00:00Z",
    }


@pytest.mark.parametrize("event", ["push", "workflow_dispatch"])
def test_first_release_uses_the_tested_commit(release_repo: ReleaseRepository, event: str) -> None:
    result = release_repo.run(GITHUB_EVENT_NAME=event)
    assert result.returncode == 0, result.stderr
    sha = release_repo.env["GITHUB_SHA"]
    writes = release_repo.writes()
    assert [(call["method"], call["path"]) for call in writes] == [
        ("POST", f"{BASE}/git/refs"),
        ("POST", f"{BASE}/releases"),
    ]
    assert writes[0]["body"] == {"ref": f"refs/tags/{TAG}", "sha": sha}
    assert writes[1]["body"] == {
        "tag_name": TAG,
        "target_commitish": sha,
        "name": TAG,
        "draft": False,
        "prerelease": False,
        "generate_release_notes": True,
    }
    assert f"Published {TAG} at {sha}" in result.stdout


@pytest.mark.parametrize("version", ["01.2.3", "1.2", "1.2.3-rc1", "1.2.3+meta", "../tag", 123])
def test_invalid_version_refuses_before_remote_access(
    release_repo: ReleaseRepository, version
) -> None:
    (release_repo.path / "pyproject.toml").write_text(f"[project]\nversion = {version!r}\n")
    result = release_repo.run()
    assert result.returncode != 0 and "version must be X.Y.Z" in result.stderr
    assert release_repo.state()["calls"] == []


@pytest.mark.parametrize(
    "context",
    [
        {"GITHUB_EVENT_NAME": "pull_request"},
        {"GITHUB_EVENT_NAME": "pull_request_target"},
        {"GITHUB_REF": "refs/heads/topic"},
        {"GITHUB_REF": "refs/tags/v0.1.0"},
        {"GITHUB_SHA": "a" * 40},
    ],
)
def test_untrusted_context_refuses_before_remote_access(release_repo: ReleaseRepository, context):
    result = release_repo.run(**context)
    assert result.returncode != 0 and "tested main commit" in result.stderr
    assert release_repo.state()["calls"] == []


def test_published_version_skips_later_commits(release_repo: ReleaseRepository) -> None:
    old = "a" * 40
    release_repo.state(tag=tag(old), release=published("main"))
    result = release_repo.run()
    assert result.returncode == 0, result.stderr
    assert "already published" in result.stdout
    assert release_repo.writes() == []
    assert release_repo.state()["tag"] == tag(old)


def test_partial_tag_retries_the_same_commit(release_repo: ReleaseRepository) -> None:
    release_repo.state(tag=tag(release_repo.env["GITHUB_SHA"]))
    result = release_repo.run()
    assert result.returncode == 0, result.stderr
    assert [call["path"] for call in release_repo.writes()] == [f"{BASE}/releases"]


def test_conflicting_tag_is_never_moved(release_repo: ReleaseRepository) -> None:
    original = tag("a" * 40)
    release_repo.state(tag=original)
    result = release_repo.run()
    assert result.returncode != 0 and "conflicting tag" in result.stderr
    assert release_repo.writes() == []
    assert release_repo.state()["tag"] == original


@pytest.mark.parametrize("kind", ["draft", "prerelease", "missing_tag", "annotated_tag"])
def test_unrelated_release_state_refuses(release_repo: ReleaseRepository, kind: str) -> None:
    sha = release_repo.env["GITHUB_SHA"]
    existing_tag, existing_release = tag(sha), published(sha)
    if kind in ("draft", "prerelease"):
        existing_release[kind] = True
    elif kind == "missing_tag":
        existing_tag = None
    else:
        existing_tag["object"]["type"] = "tag"
    release_repo.state(tag=existing_tag, release=existing_release)
    result = release_repo.run()
    assert result.returncode != 0 and "conflicting" in result.stderr
    assert release_repo.writes() == []


@pytest.mark.parametrize(
    "failure",
    [
        f"GET {BASE}/releases/tags/{TAG}",
        f"GET {BASE}/git/ref/tags/{TAG}",
        f"POST {BASE}/git/refs",
        f"POST {BASE}/releases",
    ],
)
def test_api_failure_never_reports_success(release_repo: ReleaseRepository, failure: str) -> None:
    release_repo.state(fail=failure)
    result = release_repo.run()
    assert result.returncode != 0 and "GitHub request failed" in result.stderr
    assert "Published" not in result.stdout
    assert release_repo.env["GH_TOKEN"] not in result.stdout + result.stderr
    assert release_repo.state()["release"] is None


def test_failed_publication_can_resume_without_recreating_tag(
    release_repo: ReleaseRepository,
) -> None:
    release_repo.state(fail=f"POST {BASE}/releases")
    failed = release_repo.run()
    assert failed.returncode != 0 and "GitHub request failed" in failed.stderr
    assert release_repo.state()["tag"] == tag(release_repo.env["GITHUB_SHA"])
    release_repo.state(fail=None, calls=[])
    retry = release_repo.run()
    assert retry.returncode == 0, retry.stderr
    assert [call["path"] for call in release_repo.writes()] == [f"{BASE}/releases"]
