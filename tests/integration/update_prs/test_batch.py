"""One structured issue hands tested bot PRs to the existing dispatcher."""

from dataclasses import dataclass, field
import json
from pathlib import Path

import pytest

from slopmeister.session import ship, update_pr
from slopmeister.workstation import kickoff
from tests.support.repos import git as _git

REPO = "owner/subject"
URL = f"https://github.com/{REPO}/issues/12"


def _pr(number):
    return {
        "number": number,
        "url": f"https://github.com/{REPO}/pull/{number}",
        "state": "OPEN",
        "author": {"login": "app/dependabot", "is_bot": True},
        "baseRefName": "main",
        "headRepository": {"nameWithOwner": REPO},
    }


def _scratch_repos(tmp_path):
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "-b", "main")
    (seed / "component.txt").write_text("pass\n")
    _git(seed, "add", "component.txt")
    _git(seed, "commit", "-m", "Seed scratch component")
    bare = tmp_path / "origin.git"
    _git(tmp_path, "clone", "--bare", str(seed), str(bare))
    prepared = tmp_path / "prepared"
    _git(tmp_path, "clone", str(bare), str(prepared))
    source = tmp_path / "editable-clone"
    _git(tmp_path, "clone", str(bare), str(source))
    return bare, prepared, source, _git(prepared, "rev-parse", "main").strip()


def _plant_updates(source):
    _git(source, "checkout", "-b", "dependabot/passing")
    (source / "component.txt").write_text("pass updated\n")
    _git(source, "commit", "-am", "Plant passing update")
    passing = _git(source, "rev-parse", "HEAD").strip()
    assert (source / "component.txt").read_text().startswith("pass")
    _git(source, "push", "origin", "HEAD:refs/heads/dependabot/passing")
    _git(source, "checkout", "main")
    _git(source, "checkout", "-b", "dependabot/broken")
    (source / "component.txt").write_text("broken\n")
    _git(source, "commit", "-am", "Plant broken update")
    old = _git(source, "rev-parse", "HEAD").strip()
    assert not (source / "component.txt").read_text().startswith("pass")
    _git(source, "push", "origin", "HEAD:refs/heads/dependabot/broken")
    (source / "component.txt").write_text("fixed\n")
    _git(source, "commit", "-am", "Fix broken update")
    fixed = _git(source, "rev-parse", "HEAD").strip()
    assert (source / "component.txt").read_text() == "fixed\n"
    return passing, old, fixed


@dataclass
class ScratchGH:
    prepared: Path
    bare: Path
    issues: list[dict] = field(default_factory=list)

    def gh(self, repo, repository, *args):
        assert Path(repo) == self.prepared and repository == REPO
        if args[:2] == ("pr", "view"):
            number = int(args[2])
            branch = "dependabot/passing" if number == 7 else "dependabot/broken"
            head = _git(self.bare, "rev-parse", "refs/heads/" + branch).strip()
            return json.dumps({**_pr(number), "headRefName": branch, "headRefOid": head})
        if args[:2] == ("issue", "list"):
            return json.dumps(self.issues)
        if args[:2] == ("issue", "create"):
            body = next(
                value.removeprefix("--body=") for value in args if value.startswith("--body=")
            )
            self.issues.append(
                {"number": 12, "url": URL, "body": body, "author": {"login": "operator"}}
            )
            return URL
        if args[:2] == ("issue", "view"):
            return json.dumps(self.issues[0])
        raise AssertionError(f"unexpected GitHub write: {args}")


def _authenticated_user(monkeypatch):
    monkeypatch.setattr(
        update_pr,
        "_run",
        lambda repo, *args: "operator" if args[:2] == ("gh", "api") else ship.command(repo, *args),
    )


def test_invalid_pr_number_is_rejected_before_github_read(tmp_path, monkeypatch):
    """Bug: report data could become a gh flag before validation."""
    calls = []
    monkeypatch.setattr(update_pr, "_gh", lambda *args: calls.append(args) or "{}")
    with pytest.raises(ValueError, match="pull request"):
        update_pr._pr(tmp_path, (REPO, "main"), update_pr.Target("--web", "a" * 40, REPO))
    assert calls == []


def test_foreign_marked_issue_is_not_adopted(tmp_path, monkeypatch):
    """Bug: a foreign issue marker could replace the structured handoff."""
    issues = [
        {
            "number": 99,
            "url": f"https://github.com/{REPO}/issues/99",
            "body": update_pr.ISSUE_MARKER,
            "author": {"login": "stranger"},
        }
    ]
    _authenticated_user(monkeypatch)
    monkeypatch.setattr(update_pr, "_gh", lambda repo, name, *args: json.dumps(issues))
    assert update_pr._existing_issue(tmp_path, REPO) is None
    issues.append(
        {"number": 12, "url": URL, "body": update_pr.ISSUE_MARKER, "author": {"login": "operator"}}
    )
    assert update_pr._existing_issue(tmp_path, REPO) == URL


def test_bare_origin_keeps_main_unchanged_after_a_breaking_pr_fix(tmp_path, monkeypatch):
    """Bug: two tested updates were summarized without an exact bot head or changed main."""
    bare, prepared, source, main = _scratch_repos(tmp_path)
    passing, old, fixed = _plant_updates(source)
    _git(source, "config", "remote.origin.pushurl", str(tmp_path / "wrong.git"))
    marker = tmp_path / "hook-ran"
    hook = source / ".git/hooks/pre-push"
    hook.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
    hook.chmod(0o755)
    monkeypatch.setattr(update_pr, "_context", lambda _: (REPO, "main"))
    github = ScratchGH(prepared, bare)
    monkeypatch.setattr(ship, "gh", github.gh)
    update_pr.push(prepared, source, update_pr.Target(8, old, REPO))
    assert _git(bare, "rev-parse", "refs/heads/dependabot/broken").strip() == fixed
    assert _git(bare, "rev-parse", "refs/heads/main").strip() == main
    assert not marker.exists() and not (tmp_path / "wrong.git").exists()
    rows = [
        {"number": 7, "head": passing, "ci": "pass", "smoke": "pass"},
        {"number": 8, "head": fixed, "ci": "fail", "smoke": "pass", "fix": fixed},
    ]
    _authenticated_user(monkeypatch)
    assert update_pr.publish(prepared, REPO, rows) == {"issue": URL, "created": True}
    body = github.issues[0]["body"]
    assert f"[#{7}](https://github.com/{REPO}/pull/7) | `{passing}` | pass | pass | ready" in body
    broken_line = f"[#{8}](https://github.com/{REPO}/pull/8) | `{fixed}`"
    assert broken_line in body and f"needs fix: CI failed; fix pushed {fixed}" in body
    assert kickoff.hits(body)[0] == []
    assert update_pr.publish(prepared, REPO, rows) == {"issue": URL, "created": False}
    assert len(github.issues) == 1
