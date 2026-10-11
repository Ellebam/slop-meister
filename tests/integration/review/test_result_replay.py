"""Final review results follow protected launcher tasks, not ticket-shaped CLI text."""

import json
from pathlib import Path
import uuid

from slopmeister.review import cli
from slopmeister.review.schema import CrossToolReviewError, ReviewResult, SecurityLens
from slopmeister.session import launch_identity
from slopmeister.vault import subject
from tests.support.repos import git, scratch_repo

CLEAN = ReviewResult((), SecurityLens(None, ("secrets",), "Nothing found."))


def _identity(monkeypatch, workspace: Path, tool: str = "codex") -> Path:
    monkeypatch.chdir(workspace)
    session = str(uuid.uuid4())
    monkeypatch.setenv("CODEX_THREAD_ID", session)
    path = launch_identity.path(workspace)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "state": "confirmed",
                "workspace": str(workspace.resolve()),
                "task": workspace.name,
                "tool": tool,
                "session_id": session,
            }
        )
    )
    path.chmod(0o600)
    return path


def _args(workspace: Path, *extra: str) -> list[str]:
    return [
        "review",
        "--direction",
        "codex-to-claude",
        "--mode",
        "plan",
        "--cwd",
        str(workspace),
        "--prompt",
        "Review.",
        *extra,
    ]


def test_changed_bytes_replay_one_final_result(monkeypatch, tmp_path):
    workspace = scratch_repo(tmp_path / "phase-one")
    _identity(monkeypatch, workspace)
    calls = []
    monkeypatch.setattr(cli, "run_review", lambda *a, **k: calls.append(a) or CLEAN)
    assert cli.main(_args(workspace)) == 0
    (workspace / "README.md").write_text("changed\n")
    assert cli.main(_args(workspace)) == 0
    assert len(calls) == 1


def test_distinct_launcher_tasks_on_one_ticket_get_distinct_results(monkeypatch, tmp_path):
    repo = scratch_repo(tmp_path / "repo")
    first, second = tmp_path / "phase-one", tmp_path / "phase-two"
    git(repo, "worktree", "add", "-q", "-b", "phase-one", str(first))
    git(repo, "worktree", "add", "-q", "-b", "phase-two", str(second))
    calls = []
    monkeypatch.setattr(cli, "run_review", lambda *a, **k: calls.append(a) or CLEAN)
    for workspace in (first, second):
        _identity(monkeypatch, workspace)
        assert cli.main(_args(workspace)) == 0
    assert len(calls) == 2
    common = Path(git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").strip())
    assert {path.name for path in (common / "slopmeister-config/reviews").iterdir()} == {
        "phase-one-plan.json",
        "phase-two-plan.json",
    }


def test_same_protected_task_from_two_worktrees_replays(monkeypatch, tmp_path):
    repo = scratch_repo(tmp_path / "repo")
    first, second = tmp_path / "one/task", tmp_path / "two/task"
    first.parent.mkdir()
    second.parent.mkdir()
    git(repo, "worktree", "add", "-q", "-b", "task", str(first))
    git(repo, "worktree", "add", "-q", "--detach", str(second), "HEAD")
    calls = []
    monkeypatch.setattr(cli, "run_review", lambda *a, **k: calls.append(a) or CLEAN)
    for workspace in (first, second):
        _identity(monkeypatch, workspace)
        assert cli.main(_args(workspace)) == 0
    assert len(calls) == 1


def test_operator_replace_removes_only_exact_result(monkeypatch, tmp_path):
    workspace = scratch_repo(tmp_path / "replace-task")
    _identity(monkeypatch, workspace)
    calls = []
    monkeypatch.setattr(cli, "run_review", lambda *a, **k: calls.append(a) or CLEAN)
    assert cli.main(_args(workspace)) == 0
    path = cli.result_path(cli.build_parser().parse_args(_args(workspace)), workspace.name)
    sibling = path.with_name("other-diff.json")
    sibling.write_text('{"gate":"other","exit_code":0}\n')
    sibling.chmod(0o600)
    assert cli.main(["replace", "--mode", "plan", "--cwd", str(workspace)]) == 0
    assert not path.exists() and sibling.exists()
    assert cli.main(_args(workspace)) == 0
    assert len(calls) == 2


def test_group_readable_result_is_not_replayed(monkeypatch, tmp_path):
    workspace = scratch_repo(tmp_path / "unsafe-result")
    _identity(monkeypatch, workspace)
    calls = []
    monkeypatch.setattr(cli, "run_review", lambda *a, **k: calls.append(a) or CLEAN)
    args = _args(workspace)
    assert cli.main(args) == 0
    path = cli.result_path(cli.build_parser().parse_args(args), workspace.name)
    path.chmod(0o644)
    assert cli.main(args) == 1
    assert len(calls) == 1


def test_failed_execution_leaves_no_final_result(monkeypatch, tmp_path):
    workspace = scratch_repo(tmp_path / "failed-task")
    _identity(monkeypatch, workspace)
    monkeypatch.setattr(
        cli,
        "run_review",
        lambda *a, **k: (_ for _ in ()).throw(
            CrossToolReviewError("failed", category="EXECUTION_FAILURE")
        ),
    )
    args = cli.build_parser().parse_args(_args(workspace))
    assert cli.main(_args(workspace)) == 1
    assert not cli.result_path(args, workspace.name).exists()


def test_changed_directory_subject_replays_one_final_result(monkeypatch, tmp_path):
    workspace = tmp_path / "directory-task"
    workspace.mkdir()
    _identity(monkeypatch, workspace)
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    note = candidate / "note.md"
    note.write_text("first\n")
    first = subject.freeze(candidate, [{"path": "note.md"}], tmp_path / "first/subject.json")
    calls = []
    monkeypatch.setattr(cli, "run_review", lambda *a, **k: calls.append(a) or CLEAN)
    args = [
        "review",
        "--direction",
        "codex-to-claude",
        "--mode",
        "plan",
        "--subject-manifest",
        str(first.manifest),
        "--prompt",
        "Review.",
    ]
    assert cli.main(args) == 0
    note.write_text("second\n")
    second = subject.freeze(candidate, [{"path": "note.md"}], tmp_path / "second/subject.json")
    args[args.index(str(first.manifest))] = str(second.manifest)
    assert cli.main(args) == 0
    assert len(calls) == 1


def test_repository_worker_cannot_switch_to_directory_subject(monkeypatch, tmp_path, capsys):
    workspace = scratch_repo(tmp_path / "repository-task")
    _identity(monkeypatch, workspace)
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "note.md").write_text("content\n")
    frozen = subject.freeze(candidate, [{"path": "note.md"}], tmp_path / "subject.json")
    calls = []
    monkeypatch.setattr(cli, "run_review", lambda *a, **k: calls.append(a) or CLEAN)
    result = cli.main(
        [
            "review",
            "--direction",
            "codex-to-claude",
            "--mode",
            "plan",
            "--subject-manifest",
            str(frozen.manifest),
            "--prompt",
            "Review.",
        ]
    )
    assert result == 1
    assert "directory subject requires a directory launcher workspace" in capsys.readouterr().out
    assert not calls


def test_exemption_is_the_same_final_result(monkeypatch, tmp_path):
    workspace = scratch_repo(tmp_path / "editorial-task")
    _identity(monkeypatch, workspace)
    calls = []
    monkeypatch.setattr(cli, "run_review", lambda *a, **k: calls.append(a) or CLEAN)
    exempt = _args(workspace, "--exempt-reason", "Editorial only")
    assert cli.main(exempt) == 0
    assert cli.main(_args(workspace)) == 0
    assert not calls
