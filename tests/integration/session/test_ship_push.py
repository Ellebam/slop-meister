"""The push-only helper pushes a session's own HEAD to its recorded branch on any forge."""

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess

import pytest

from tests.integration.install.installer_helpers import environment, install, project, worktree
from tests.support.repos import git


@dataclass(frozen=True)
class Pushed:
    workspace: Path
    origin: Path
    env: dict[str, str]


def remote_head(origin: Path, ref: str) -> str:
    return git(origin, "for-each-ref", "--format=%(objectname)", ref).strip()


@pytest.fixture
def session(tmp_path):
    return pushed(tmp_path)


def pushed(tmp_path: Path) -> Pushed:
    """A suffixed worktree shop-t-2 whose recorded push branch is shop-t, one commit ahead."""
    env = environment(tmp_path)
    origin = tmp_path / "origin.git"
    origin.mkdir()
    git(origin, "init", "-q", "--bare", "-b", "main")
    repo = project(tmp_path / "project")
    git(repo, "remote", "add", "origin", str(origin))
    git(repo, "push", "-q", "origin", "main", "main:shop-t")
    workspace = worktree(repo, "shop-t-2")
    install(env, "--prepare", "example-app", str(workspace), "--push-branch", "shop-t")
    (workspace / "app.txt").write_text("changed\n")
    git(workspace, "commit", "-qam", "Change app")
    return Pushed(workspace, origin, env)


def ship(current: Pushed, *args: str) -> subprocess.CompletedProcess[str]:
    entry = current.workspace / ".claude/skills/ship/scripts/ship.py"
    return subprocess.run(
        ["python3", str(entry), "--push-only", "--cwd", str(current.workspace), *args],
        cwd=current.workspace,
        env=current.env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_tracer_pushes_head_to_the_recorded_branch(session):
    result = ship(session)
    assert result.returncode == 0, result.stderr
    head = git(session.workspace, "rev-parse", "HEAD").strip()
    assert json.loads(result.stdout) == dict(sha=head, branch="shop-t", pushed=True)
    assert remote_head(session.origin, "refs/heads/shop-t") == head
    assert remote_head(session.origin, "refs/heads/shop-t-2") == ""


def test_rerun_writes_nothing(session):
    assert ship(session).returncode == 0
    result = ship(session)
    assert result.returncode == 0 and json.loads(result.stdout)["pushed"] is False


def test_rewritten_history_is_never_forced(session):
    """Bug: the push-only path overwrites someone else's commits on the merge request branch."""
    other = git(session.workspace, "commit-tree", "-m", "Elsewhere", "HEAD~1^{tree}").strip()
    git(session.workspace, "push", "-q", "origin", other + ":refs/heads/shop-t", "--force")
    result = ship(session)
    assert result.returncode == 1 and "git push --no-follow-tags failed" in result.stderr
    assert remote_head(session.origin, "refs/heads/shop-t") == other


@pytest.mark.parametrize("change", ["default", "origin", "clone", "switched"])
def test_refused_targets_push_nothing(session, tmp_path, change):
    """Bug: an approval-free push lands on the default branch, another remote, a foreign clone or
    another branch's HEAD."""
    before = git(session.origin, "for-each-ref").strip()
    current = session
    if change == "default":
        git(session.origin, "symbolic-ref", "HEAD", "refs/heads/shop-t")
        expected = "default branch"
    elif change == "origin":
        moved = tmp_path / "moved.git"
        git(session.origin, "clone", "-q", "--bare", str(session.origin), str(moved))
        git(session.workspace, "remote", "set-url", "origin", str(moved))
        expected = "saved single repository"
    elif change == "switched":
        git(session.workspace, "switch", "-q", "-c", "other")
        expected = "task branch changed"
    else:
        clone = tmp_path / "clone"
        git(tmp_path, "clone", "-q", "-b", "shop-t", str(session.origin), str(clone))
        current = Pushed(clone, session.origin, session.env)
        expected = "outside its session"
    entry = session.workspace / ".claude/skills/ship/scripts/ship.py"
    result = subprocess.run(
        ["python3", str(entry), "--push-only", "--cwd", str(current.workspace)],
        env=session.env, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert result.returncode == 1 and expected in result.stderr, result.stderr
    assert git(session.origin, "for-each-ref").strip() == before


def test_origin_with_two_urls_at_launch_pushes_nothing(tmp_path):
    """Bug: a second origin URL receives the push although its default branch is the target."""
    second = tmp_path / "second.git"
    second.mkdir()
    git(second, "init", "-q", "--bare", "-b", "shop-t")
    env = environment(tmp_path)
    origin = tmp_path / "origin.git"
    origin.mkdir()
    git(origin, "init", "-q", "--bare", "-b", "main")
    repo = project(tmp_path / "project")
    git(repo, "remote", "add", "origin", str(origin))
    git(repo, "push", "-q", "origin", "main", "main:shop-t")
    git(second, "fetch", "-q", str(origin), "shop-t:shop-t")
    git(repo, "remote", "set-url", "--add", "origin", str(second))
    workspace = worktree(repo, "shop-t-2")
    install(env, "--prepare", "example-app", str(workspace), "--push-branch", "shop-t")
    (workspace / "app.txt").write_text("changed\n")
    git(workspace, "commit", "-qam", "Change app")
    before = git(second, "for-each-ref").strip()
    result = ship(Pushed(workspace, origin, env))
    assert result.returncode == 1 and "saved single repository" in result.stderr, result.stderr
    assert git(second, "for-each-ref").strip() == before


def test_missing_remote_branch_is_never_created(session):
    """Bug: a worker without a recorded merge request branch creates a stray branch without
    approval."""
    git(session.origin, "update-ref", "-d", "refs/heads/shop-t")
    before = git(session.origin, "for-each-ref").strip()
    result = ship(session)
    assert result.returncode == 1 and "origin has no branch shop-t" in result.stderr, result.stderr
    assert git(session.origin, "for-each-ref").strip() == before


def test_dev_tag_at_head_is_pushed_once(session):
    git(session.workspace, "tag", "-a", "-m", "dev", "0.2.1-dev1")
    first, second = ship(session, "--tag", "0.2.1-dev1"), ship(session, "--tag", "0.2.1-dev1")
    assert first.returncode == 0 and second.returncode == 0, first.stderr + second.stderr
    assert json.loads(first.stdout)["tag_pushed"] is True
    assert json.loads(second.stdout)["tag_pushed"] is False
    local = git(session.workspace, "rev-parse", "refs/tags/0.2.1-dev1").strip()
    assert remote_head(session.origin, "refs/tags/0.2.1-dev1") == local


@pytest.mark.parametrize("case", ["release", "elsewhere", "moved"])
def test_refused_tags_push_nothing(session, case):
    """Bug: the approval-free path publishes a release or moves a published tag."""
    name = "1.0.0" if case == "release" else "0.2.1-dev1"
    git(session.workspace, "tag", name, "HEAD~1" if case == "elsewhere" else "HEAD")
    if case == "moved":
        git(session.workspace, "push", "-q", "origin", "HEAD~1:refs/tags/" + name)
    before = git(session.origin, "for-each-ref").strip()
    result = ship(session, "--tag", name)
    reason = dict(release="pre-release", elsewhere="not point at HEAD", moved="never moved")
    assert result.returncode == 1 and reason[case] in result.stderr, result.stderr
    assert git(session.origin, "for-each-ref").strip() == before


def test_push_only_takes_no_pr_options(session):
    """Bug: the approval-free entry opens a PR as well."""
    result = ship(session, "--title", "Task")
    assert result.returncode == 2 and "takes no PR options" in result.stderr


@pytest.mark.parametrize("name", ["-x", "a..b", "shop t"])
def test_invalid_push_branch_is_refused_at_preparation(tmp_path, name):
    env = environment(tmp_path)
    workspace = worktree(project(tmp_path / "project"), "shop-t-2")
    result = install(
        env, "--prepare", "example-app", str(workspace), "--push-branch=" + name, ok=False
    )
    assert "push branch is not a valid branch name" in result.stderr
