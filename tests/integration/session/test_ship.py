"""Shipping pushes one task branch and opens or updates its one PR, and nothing else."""

import json
import os
import sys
from types import SimpleNamespace

import pytest

from slopmeister.session import ship
from tests.support import repos
from tests.support.ship_origin import BODY, OTHER, PR, REAL_COMMAND, REMOTE, URL, Origin


@pytest.fixture
def world(tmp_path, monkeypatch):
    for key in [key for key in os.environ if key.startswith("GIT_")]:
        monkeypatch.delenv(key)
    repo = tmp_path / "repo"
    repo.mkdir()
    repos.git(repo, "init", "-qb", "task")

    def git(*args):
        return repos.git(repo, *args).strip()

    git("commit", "-q", "--allow-empty", "-m", "Create app")
    git("remote", "add", "origin", REMOTE)
    state = dict(
        worktree=str(repo), directory=False, commit="allow", shipping="allow",
        baseline=git("rev-parse", "HEAD"), roots=[".claude", ".agents", "CLAUDE.md"],
        ship_target=dict(remote=REMOTE, branch="task"),
    )  # fmt: skip
    origin = Origin()
    monkeypatch.setattr(ship, "command", origin.command)
    sleep = SimpleNamespace(sleep=lambda seconds: origin.calls.append(("sleep", seconds)))
    monkeypatch.setattr(ship, "time", sleep)
    return dict(repo=repo, git=git, state=state, origin=origin, body=BODY, tmp=tmp_path)


def run(world, capsys):
    config = world["repo"] / ".git/slopmeister-config"
    config.mkdir(exist_ok=True)
    (config / "state.json").write_text(json.dumps(world["state"]))
    body = world["tmp"] / "body.md"
    body.write_text(world["body"])
    argv = ["--cwd", str(world["repo"]), "--title", "Task", "--body-file", str(body)]
    code = ship.main(argv)
    out, err = capsys.readouterr()
    return code, json.loads(out) if code == 0 else out, err


def test_first_run_pushes_creates_and_reports(world, capsys, monkeypatch):
    """Bug: push.followTags adds tags to an agent push, or session Git settings block shipping."""
    monkeypatch.setenv("GIT_EDITOR", "true")
    monkeypatch.setenv("GIT_PAGER", "cat")
    code, result, _ = run(world, capsys)
    assert code == 0
    sha, action = world["git"]("rev-parse", "HEAD"), "created"
    assert result == dict(pr=URL, sha=sha, pushed=True, pr_action=action, mergeable="MERGEABLE")
    assert [call[:6] for call in world["origin"].writes()] == [
        ("git", "push", "--no-follow-tags", "--no-recurse-submodules", "--set-upstream", "origin"),
        ("gh", "pr", "create", "--head", "task", "--base"),
    ]
    assert world["origin"].writes()[0][6:] == ("refs/heads/task:refs/heads/task",)


def test_harness_git_variables_do_not_stop_shipping(world, capsys, monkeypatch):
    """Bug: shipping refused until the harness credential variables were unset by hand."""
    harness = ("GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0", "GIT_ASKPASS")
    for name in (*harness, "GIT_TERMINAL_PROMPT"):
        monkeypatch.setenv(name, "0")
    assert run(world, capsys)[0] == 0


def test_rerun_with_confirmed_results_writes_nothing(world, capsys):
    """Bug: a rerun after a confirmed push and PR repeats a remote write."""
    assert run(world, capsys)[0] == 0
    world["origin"].calls.clear()
    code, result, _ = run(world, capsys)
    assert code == 0 and result["pushed"] is False and result["pr_action"] == "unchanged"
    assert world["origin"].writes() == []


def test_changed_body_edits_the_existing_pr_once(world, capsys):
    """Bug: an updated review line never reaches the existing PR."""
    world["origin"].prs.append(dict(PR, body="Independent review: PENDING - old\n"))
    world["origin"].sha = world["git"]("rev-parse", "HEAD")
    code, result, _ = run(world, capsys)
    assert code == 0 and result["pr_action"] == "updated" and result["pushed"] is False
    assert [call[1:3] for call in world["origin"].writes()] == [("pr", "edit")]
    assert world["origin"].prs[0]["body"] == BODY


@pytest.mark.parametrize(
    "change,reason",
    [
        (dict(push_lands=False), "pushed SHA is unconfirmed"),
        (dict(fail=("git", "push")), "git push --no-follow-tags failed (1): boom"),
    ],
)
def test_failed_or_unconfirmed_push_stops_before_any_pr_write(world, capsys, change, reason):
    """Bug: a PR is opened for a commit not on the remote, or a failed push reads as success."""
    vars(world["origin"]).update(change)
    code, out, err = run(world, capsys)
    assert code == 1 and out == "" and reason in err
    assert [call[:2] for call in world["origin"].writes()] == [("git", "push")]


def test_unconfirmed_pr_write_fails(world, capsys, monkeypatch):
    """Bug: a stale PR body is reported as shipped."""
    world["origin"].prs.append(dict(PR, body="Independent review: PENDING - old\n"))
    monkeypatch.setattr(world["origin"], "gh", lambda args, gh=world["origin"].gh: (
        URL if args[:2] == ("pr", "edit") else gh(args)))  # fmt: skip
    code, out, err = run(world, capsys)
    assert code == 1 and out == "" and "PR write is unconfirmed" in err


@pytest.mark.parametrize(
    "states,reported,reads",
    [
        (["UNKNOWN", "MERGEABLE"], "MERGEABLE", 2),
        (["CONFLICTING"], "CONFLICTING", 1),
        (["UNKNOWN"], "UNKNOWN", 5),
        (None, "UNAVAILABLE", 1),
    ],
)
def test_mergeability_is_reported_never_enforced(world, capsys, states, reported, reads):
    """Bug #178: a mergeability answer or a failed status read blocks a completed shipment."""
    world["origin"].mergeable = states or ["MERGEABLE"]
    world["origin"].fail = None if states else ("gh", "pr", "view")
    code, result, _ = run(world, capsys)
    assert code == 0 and result["mergeable"] == reported
    calls = world["origin"].calls
    assert len([call for call in calls if call[1:3] == ("pr", "view")]) == reads
    assert [call for call in calls if call[0] == "sleep"] == [("sleep", 2)] * (reads - 1)


def test_command_timeout_names_the_command_without_its_arguments(tmp_path, monkeypatch):
    """Bug: a timed-out PR write prints its whole body in the error."""
    monkeypatch.setattr(ship, "COMMAND_TIMEOUT_SECONDS", 0.2)
    with pytest.raises(ValueError) as error:
        REAL_COMMAND(tmp_path, sys.executable, "-c", "import time; time.sleep(5)", "--body=TEXT")
    assert "timed out after 0.2s" in str(error.value) and "TEXT" not in str(error.value)


def test_command_error_names_the_command_and_its_stderr(tmp_path):
    """Bug: a failing Git or gh call surfaces without the command or its reason."""
    script = "import sys; sys.stderr.write('remote rejected'); sys.exit(3)"
    with pytest.raises(ValueError, match=r"-c import sys.* failed \(3\): remote rejected"):
        REAL_COMMAND(tmp_path, sys.executable, "-c", script)


def leak_delivered(world):
    (world["repo"] / ".claude").mkdir()
    (world["repo"] / ".claude/session.md").write_text("delivered\n")
    world["git"]("add", "-f", ".claude/session.md")
    world["git"]("commit", "-qm", "Leak delivered configuration")


def refuse(world, monkeypatch, case):
    state, git, origin, other = world["state"], world["git"], world["origin"], world["tmp"] / "o"
    changes = {
        "commit-missing": (lambda: state.pop("commit"), "missing or invalid"),
        "shipping-missing": (lambda: state.pop("shipping"), "missing or invalid"),
        "directory": (lambda: state.update(directory=True), "missing or invalid"),
        "worktree": (lambda: state.update(worktree=str(other)), "repository identity differs"),
        "branch": (lambda: git("switch", "-qc", "other"), "current task branch changed"),
        "remote": (lambda: git("remote", "set-url", "origin", OTHER), "not the saved single"),
        "fetch-url": (  # push still reaches the saved remote, fetch and ls-remote read another
            lambda: (
                git("remote", "set-url", "origin", OTHER)
                or git("config", "remote.origin.pushurl", REMOTE)
            ),
            "not the saved single",
        ),
        "default": (lambda: setattr(origin, "default", "task"), "is the default branch"),
        "dirty": (lambda: (world["repo"] / "x.py").write_text("x\n"), "commit the explicit"),
        "no-review-line": (lambda: world.update(body="Task\n"), "exactly one independent"),
        "two-review-lines": (lambda: world.update(body=BODY * 2), "exactly one independent"),
        "git-dir": (lambda: monkeypatch.setenv("GIT_DIR", str(other)), "overrides: GIT_DIR"),
        "git-ssh": (lambda: monkeypatch.setenv("GIT_SSH_COMMAND", "ssh"), "GIT_SSH_COMMAND"),
        "detached": (lambda: git("switch", "-q", "--detach"), "HEAD is detached"),
        "verification": (lambda: setattr(origin, "fail", (sys.executable,)), "failed (1): boom"),
        "delivered": (lambda: leak_delivered(world), "delivered session configuration"),
    }
    changes[case][0]()  # apply the case, then return the reason it must be refused with
    return changes[case][1]


CASES = """commit-missing shipping-missing directory worktree branch
remote fetch-url default dirty no-review-line two-review-lines git-dir git-ssh detached
verification delivered"""


@pytest.mark.parametrize("case", CASES.split())
def test_refusals_stop_before_any_remote_write(world, capsys, monkeypatch, case):
    """Bug: shipping reaches the wrong destination or ships without declared authority."""
    reason = refuse(world, monkeypatch, case)
    code, out, err = run(world, capsys)
    assert code == 1 and out == "" and err.startswith("SPINE BLOCKED: shipping:")
    assert reason in err
    assert world["origin"].writes() == []


@pytest.mark.parametrize(("commit", "shipping"), [("deny", "deny"), ("allow", "deny")])
def test_explicit_denied_ship_writes_the_exact_pr_through_the_fixed_guards(
    world, capsys, commit, shipping
):
    """Bug: under deny the fixed helper refuses the operator-requested ship, or drops its body."""
    world["state"].update(commit=commit, shipping=shipping)
    code, result, _ = run(world, capsys)
    assert code == 0 and result["pr_action"] == "created"
    assert world["origin"].prs[0]["title"] == "Task" and world["origin"].prs[0]["body"] == BODY


@pytest.mark.parametrize(
    "prs",
    [
        [dict(PR, headRepository={"nameWithOwner": "other/subject"})],
        [dict(PR, state="CLOSED")],
        [PR, dict(PR, number=2)],
    ],
    ids=["foreign", "closed", "duplicate"],
)
def test_foreign_closed_or_duplicate_pr_is_never_written(world, capsys, prs):
    """Bug: shipping edits someone else's PR or a closed one."""
    world["origin"].prs = prs
    world["origin"].sha = world["git"]("rev-parse", "HEAD")
    code, out, _ = run(world, capsys)
    assert code == 1 and out == ""
    assert world["origin"].writes() == []


def test_follow_up_after_merge_creates_updates_and_retries(world, capsys):
    """A merged PR must not block a new PR or make retries repeat writes."""
    origin, git = world["origin"], world["git"]
    origin.prs.append(dict(PR, state="MERGED", headRefOid=git("rev-parse", "HEAD")))
    git("commit", "-q", "--allow-empty", "-m", "Follow up")
    world["body"] += "\nFollows #1\n"
    code, result, err = run(world, capsys)
    assert code == 0 and result["pr_action"] == "created", err
    assert len(origin.prs) == 2 and origin.prs[1]["body"] == world["body"]
    origin.calls.clear()
    code, result, _ = run(world, capsys)
    assert code == 0 and not result["pushed"] and result["pr_action"] == "unchanged"
    assert origin.writes() == []
    world["body"] = world["body"].replace("Task proof", "Updated proof")
    code, result, _ = run(world, capsys)
    assert code == 0 and result["pr_action"] == "updated"
    assert origin.prs[1]["body"] == world["body"]


def test_merged_without_follow_up_does_not_recreate_deleted_branch(world, capsys):
    """A no-change retry after merge must not recreate a deleted branch."""
    world["origin"].prs.append(
        dict(PR, state="MERGED", headRefOid=world["git"]("rev-parse", "HEAD"))
    )
    world["body"] += "\nFollows #1\n"
    code, _, err = run(world, capsys)
    assert code == 1 and "no follow-up commits" in err
    assert world["origin"].writes() == []


@pytest.mark.parametrize(
    "case,reason",
    [
        ("closed", "existing PR does not match"),
        ("foreign", "existing PR does not match"),
        ("duplicate", "multiple PRs"),
        ("body", "predecessor line"),
        ("extra-line", "predecessor line"),
        ("unrelated", "does not descend"),
    ],
)
def test_follow_up_refuses_invalid_history_before_push(world, capsys, case, reason):
    """A refused follow-up must not push or change a PR, even if the branch was deleted."""
    origin, git = world["origin"], world["git"]
    merged = dict(PR, state="MERGED", headRefOid=git("rev-parse", "HEAD"))
    origin.prs.append(merged)
    git("commit", "-q", "--allow-empty", "-m", "Follow up")
    world["body"] += "\nFollows #1\n"
    if case == "closed":
        origin.prs.append(dict(PR, number=2, state="CLOSED"))
    if case == "foreign":
        merged["headRepository"] = {"nameWithOwner": "other/subject"}
    if case == "duplicate":
        origin.prs.extend([dict(PR, number=2), dict(PR, number=3)])
    if case == "body":
        world["body"] = BODY
    if case == "extra-line":
        world["body"] += "Follows #2\n"
    if case == "unrelated":
        merged["headRefOid"] = "0" * 40
    code, _, err = run(world, capsys)
    assert code == 1 and reason in err
    assert origin.writes() == []


def test_follow_up_names_latest_of_multiple_merged_prs(world, capsys):
    """The next request follows the latest merge, not an older request on the branch."""
    origin, git = world["origin"], world["git"]
    first = git("rev-parse", "HEAD")
    git("commit", "-q", "--allow-empty", "-m", "Second change")
    second = git("rev-parse", "HEAD")
    origin.prs.extend(
        [
            dict(PR, state="MERGED", headRefOid=first, mergedAt="2026-01-01T00:00:00Z"),
            dict(PR, number=2, state="MERGED", headRefOid=second, mergedAt="2026-01-02T00:00:00Z"),
        ]
    )
    git("commit", "-q", "--allow-empty", "-m", "Third change")
    world["body"] += "\nFollows #1\n"
    code, _, err = run(world, capsys)
    assert code == 1 and "Follows #2" in err and origin.writes() == []
    world["body"] = world["body"].replace("Follows #1", "Follows #2")
    code, result, _ = run(world, capsys)
    assert code == 0 and result["pr_action"] == "created"
    assert origin.prs[-1]["number"] == 3 and origin.prs[-1]["body"] == world["body"]
