"""Keep issue ownership from becoming an available-backlog guess."""

import pytest

from slopmeister.claims import evidence, github, inventory
from tests.support import trees
from tests.unit.claims.conftest import issue


@pytest.mark.parametrize(
    "labels,owners,errors,dependencies,expected",
    [
        pytest.param(
            [],
            [],
            [],
            [],
            ("available", False),
            id="labels0-owners0-errors0-dependencies0-available-False",
        ),
        pytest.param(
            ["agent:claimed"],
            [],
            [],
            [],
            ("claimed", True),
            id="labels1-owners1-errors1-dependencies1-claimed-True",
        ),
        pytest.param(
            ["blocked"],
            [],
            [],
            [],
            ("blocked", False),
            id="labels2-owners2-errors2-dependencies2-blocked-False",
        ),
        pytest.param(
            ["blocked", "agent:claimed"],
            [],
            [],
            [],
            ("blocked", True),
            id="labels3-owners3-errors3-dependencies3-blocked-True",
        ),
        pytest.param(
            [],
            [{"phase": "pending"}],
            [],
            [],
            ("unknown", True),
            id="labels4-owners4-errors4-dependencies4-unknown-True",
        ),
        pytest.param(
            [],
            [{"phase": "claimed", "delivery": {"session": "owner"}}],
            [],
            [],
            ("unknown", True),
            id="labels5-owners5-errors5-dependencies5-unknown-True",
        ),
        pytest.param(
            ["agent:claimed"],
            [{"phase": "claimed", "delivery": {"session": "owner"}}],
            [],
            [],
            ("claimed", True),
            id="labels6-owners6-errors6-dependencies6-claimed-True",
        ),
        pytest.param(
            ["agent:claimed"],
            [{"phase": "claimed"}, {"phase": "claimed"}],
            [],
            [],
            ("unknown", True),
            id="labels7-owners7-errors7-dependencies7-unknown-True",
        ),
        pytest.param(
            [],
            [],
            ["dependency lookup failed"],
            [],
            ("unknown", False),
            id="labels8-owners8-errors8-dependencies8-unknown-False",
        ),
        pytest.param(
            [],
            [],
            [],
            [issue(state="open", number=3)],
            ("blocked", False),
            id="labels9-owners9-errors9-dependencies9-blocked-False",
        ),
        pytest.param(
            [],
            [],
            [],
            [issue(state="closed", number=3)],
            ("available", False),
            id="labels10-owners10-errors10-dependencies10-available-False",
        ),
    ],
)
def test_backlog_never_recommends_occupied_blocked_or_unknown(
    labels, owners, errors, dependencies, expected
):
    category, owned = expected
    row = inventory.classify(
        item=issue(labels), values=inventory.Classification(owners, dependencies, errors)
    )
    assert row["category"] == category
    assert row["owned"] == owned
    assert row["recommend"] is (category == "available")


@pytest.mark.parametrize("value", ["", "0", "-1", "7x", "../7", "1\n2", True])
def test_invalid_explicit_identifier_never_reaches_github(value):
    with pytest.raises(ValueError):
        github.issue_number(value)


def test_closed_issue_is_done_even_with_historical_claim():
    row = inventory.classify(issue(["agent:claimed"], state="closed"), inventory.Classification())
    assert row["category"] == "closed" and not row["recommend"]


@pytest.mark.parametrize(
    "value", ["git@github.com:owner/project.git", "https://github.com/owner/project.git"]
)
def test_repo_identity_has_one_canonical_spelling(value):
    assert github.repository_name(value) == "owner/project"


@pytest.mark.parametrize(
    "value",
    [
        "https://elsewhere.invalid/owner/project",
        "git@github.com:owner/repo.git\nother",
        "https://github.com/owner/repo/../other",
        "https://token@github.com/owner/repo",
    ],
)
def test_ambiguous_remote_cannot_select_an_issue(value):
    with pytest.raises(ValueError):
        github.repository_name(value)


def test_dependency_pagination_does_not_hide_later_blocker(monkeypatch):
    calls = []

    def request(ctx, call):
        calls.append(call.endpoint)
        return (
            [issue(state="closed")] * 100
            if call.endpoint.endswith("&page=1")
            else [issue(state="open")]
        )

    monkeypatch.setattr(github, "request", request)
    dependencies = github.pages(None, "issues/7/dependencies/blocked_by")
    assert len(calls) == 2
    assert (
        inventory.classify(issue(), inventory.Classification(dependencies=dependencies))["category"]
        == "blocked"
    )


def test_incomplete_list_refuses_instead_of_reporting_empty(monkeypatch):
    monkeypatch.setattr(github, "request", lambda ctx, call: {})
    with pytest.raises(ValueError, match="incomplete"):
        github.pages(None, "issues?state=open")


def test_wrong_issue_response_never_mutates(monkeypatch):
    monkeypatch.setattr(github, "request", lambda *args: issue(number=8))
    with pytest.raises(ValueError, match="exact issue"):
        github.remote_issue(None, 7)


def test_string_issue_in_receipt_cannot_hide_an_owner(monkeypatch, tmp_path):
    path = trees.write(tmp_path, "slopmeister-config/issue.json", "{}")
    evidence.save(
        path,
        {
            "repository": "owner/project",
            "workspace": str(tmp_path),
            "issue": "7",
            "phase": "pending",
        },
    )
    context = github.Repository(tmp_path, tmp_path, "owner/project", "remote", "slopmeister")
    monkeypatch.setattr(github, "workspaces", lambda ctx: [tmp_path])
    with pytest.raises(ValueError, match="issue"):
        evidence.receipts(context)


def test_listed_worktree_without_git_metadata_cannot_hide_an_owner(monkeypatch, tmp_path):
    # Git prints a path with a line break unquoted, so its listed path matches no metadata.
    context = github.Repository(tmp_path, tmp_path, "owner/project", "remote", "slopmeister")
    monkeypatch.setattr(github, "workspaces", lambda ctx: [tmp_path, tmp_path / "cut"])
    with pytest.raises(ValueError, match="no Git metadata"):
        evidence.receipts(context)


@pytest.mark.parametrize("failing,error", [("census", ValueError), ("_has_notes", OSError)])
def test_uninspectable_worktree_warns_and_blocks_nothing(monkeypatch, tmp_path, failing, error):
    def fail(*args):
        raise error("unreadable")

    root = tmp_path / "root"
    context = github.Repository(root, tmp_path, "owner/project", "remote", "slopmeister")
    monkeypatch.setattr(github, "workspaces", lambda ctx: [tmp_path])
    monkeypatch.setattr(evidence, "receipts", lambda ctx: [])
    monkeypatch.setattr(inventory, "census", lambda workspace: [])
    monkeypatch.setattr(inventory, failing, fail)
    monkeypatch.setattr(
        github, "pages", lambda ctx, endpoint: [] if "dependencies" in endpoint else [issue()]
    )
    report = inventory.backlog(context)
    assert report["recommend"] == [7]
    assert report["warnings"] == [
        f"cannot inspect worktree at {tmp_path}: unreadable, does not block dispatch"
    ]
