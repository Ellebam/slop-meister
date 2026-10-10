"""Autonomous updates may change only the exact bot PR head."""

from dataclasses import dataclass, field
import json
from pathlib import Path

import pytest

from slopmeister.session import ship, update_pr

OLD = "a" * 40
NEW = "b" * 40
REMOTE = "https://github.com/owner/subject.git"
URL = "https://github.com/owner/subject/pull/7"
BRANCH = "dependabot/npm_and_yarn/service-1"


@dataclass
class World:
    workspace: Path
    source: Path
    calls: list[tuple[Path, tuple[str, ...]]] = field(default_factory=list)
    remote_head: str = OLD
    author: str = "app/dependabot"
    head_repo: str = "owner/subject"
    url: str = URL

    def command(self, repo, *argv):
        repo = Path(repo)
        self.calls.append((repo, argv))
        if argv[:3] == ("git", "remote", "get-url"):
            return REMOTE
        values = {
            ("git", "rev-parse"): NEW,
            ("git", "diff"): "services/app.py",
            ("git", "ls-remote"): f"{self.remote_head}\trefs/heads/{BRANCH}",
        }
        if argv[:2] in values:
            return values[argv[:2]]
        if "push" in argv:
            self.remote_head = NEW
            return ""
        if argv[:2] in (("git", "fetch"), ("git", "merge-base"), ("git", "status")):
            return ""
        raise AssertionError(f"unexpected command: {argv}")

    def gh(self, repo, repository, *argv):
        assert repo == self.workspace and repository == "owner/subject"
        if argv[:2] == ("repo", "view"):
            return json.dumps(
                {"nameWithOwner": "owner/subject", "defaultBranchRef": {"name": "main"}}
            )
        assert argv[:3] == ("pr", "view", "7")
        return json.dumps(
            {
                "number": 7,
                "url": self.url,
                "state": "OPEN",
                "author": {"login": self.author, "is_bot": True},
                "baseRefName": "main",
                "headRefName": BRANCH,
                "headRefOid": self.remote_head,
                "headRepository": {"nameWithOwner": self.head_repo},
            }
        )


@pytest.fixture
def world(tmp_path, monkeypatch):
    workspace = tmp_path / "prepared"
    source = workspace / "editable-clone"
    workspace.mkdir()
    source.mkdir()
    result = World(workspace, source)
    state = {
        "worktree": str(workspace),
        "plot": "example-app",
        "commit": "allow",
        "shipping": "allow",
        "ship_target": {"remote": REMOTE, "branch": "prepared"},
    }
    monkeypatch.setattr(ship, "authorized_state", lambda repo: state)
    monkeypatch.setattr(ship, "command", result.command)
    monkeypatch.setattr(ship, "gh", result.gh)
    return result


def test_exact_bot_head_pushed_from_prepared_workspace_once(world):
    """Bug: a no-prompt update pushed from the editable clone or wrote an extra ref."""
    result = update_pr.push(
        world.workspace, world.source, update_pr.Target(7, OLD, "owner/subject")
    )
    assert result == {"pr": URL, "sha": NEW, "pushed": True}
    pushes = [(repo, args) for repo, args in world.calls if "push" in args]
    assert len(pushes) == 1
    repo, args = pushes[0]
    assert repo == world.workspace
    assert "--no-verify" in args and "--force" not in args
    assert args[-1] == f"{NEW}:refs/heads/{BRANCH}"
    world.calls.clear()
    assert (
        update_pr.push(world.workspace, world.source, update_pr.Target(7, NEW, "owner/subject"))[
            "pushed"
        ]
        is False
    )
    assert not any("push" in args for _, args in world.calls)


@pytest.mark.parametrize(
    "change",
    [
        {"author": "someone"},
        {"head_repo": "other/fork"},
        {"remote_head": "c" * 40},
        {"url": "https://evil.example/pull/7"},
    ],
)
def test_wrong_owner_head_or_gate_change_cannot_push(world, change):
    """Bug: an unrelated or self-certifying change reached a bot branch unattended."""
    for name, value in change.items():
        setattr(world, name, value)
    with pytest.raises(ValueError):
        update_pr.push(world.workspace, world.source, update_pr.Target(7, OLD, "owner/subject"))
    assert not any("push" in args for _, args in world.calls)


def test_explicit_repository_must_match_saved_origin(world):
    """Bug: a scheduled example-app run could silently target another prepared plot."""
    with pytest.raises(ValueError, match="repository"):
        update_pr.push(world.workspace, world.source, update_pr.Target(7, OLD, "owner/wrong"))
    assert not any("push" in args for _, args in world.calls)
