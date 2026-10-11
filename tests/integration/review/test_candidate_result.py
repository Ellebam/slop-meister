"""Repository candidate review retains the protected task-and-mode result namespace."""

import json
from pathlib import Path
import tempfile
import uuid

from slopmeister.review import cli
from slopmeister.review.process import CommandResult
from slopmeister.review.schema import ReviewResult, SecurityLens
from slopmeister.session import launch_identity
from slopmeister.spine import candidate
from tests.support.repos import git, scratch_repo
from tests.support.review_helpers import CLEAN_REVIEW_JSON

CLEAN = ReviewResult((), SecurityLens(None, ("secrets",), "Nothing found."))


def ready(monkeypatch, tmp_path):
    workspace = scratch_repo(tmp_path / "candidate-task")
    monkeypatch.chdir(workspace)
    session = str(uuid.uuid4())
    monkeypatch.setenv("CODEX_THREAD_ID", session)
    launch_identity.write(workspace, (workspace.name, "codex", session))
    (workspace / "README.md").write_text("candidate\n")
    return workspace, candidate.freeze(workspace, workspace.name)


def arguments(workspace):
    return [
        "review", "--direction", "codex-to-claude", "--mode", "diff",
        "--cwd", str(workspace), "--candidate", "--prompt", "Review.",
    ]  # fmt: skip


def test_candidate_review_uses_repository_namespace_and_replays_only_same_tree(
    monkeypatch, tmp_path, capsys
):
    workspace, first = ready(monkeypatch, tmp_path)
    calls = []

    def review(*args, **kwargs):
        target = args[1]
        calls.append(target)
        assert Path(target.cwd) != workspace
        assert (Path(target.cwd) / "README.md").read_text() == "candidate\n"
        return CLEAN

    monkeypatch.setattr(cli, "run_review", review)
    args = arguments(workspace)
    assert cli.main(args) == 0
    result = cli.result_path(cli.build_parser().parse_args(args), workspace.name)
    common = (workspace / git(workspace, "rev-parse", "--git-common-dir").strip()).resolve()
    assert result.is_relative_to(common)
    assert json.loads(result.read_text())["candidate"] == first.tree
    (workspace / "README.md").write_text("second candidate\n")
    assert candidate.freeze(workspace, workspace.name).tree != first.tree
    assert cli.main(args) == 1 and len(calls) == 1
    assert "candidate differs from final review result" in capsys.readouterr().out


def test_candidate_review_prompt_shows_the_reviewer_every_changed_and_new_file(
    monkeypatch, tmp_path
):
    """Without the guide a branch diff finds nothing and plain `git diff` drops new files."""
    workspace, _ = ready(monkeypatch, tmp_path)
    (workspace / "added.py").write_text("new\n")
    frozen = candidate.freeze(workspace, workspace.name)
    seen = {}

    def review(*args, **kwargs):
        target = args[1]
        seen["prompt"] = target.prompt
        seen["status"] = git(Path(target.cwd), "status", "--porcelain", "--untracked-files=all")
        seen["diff"] = git(Path(target.cwd), "diff", "HEAD")
        return CLEAN

    monkeypatch.setattr(cli, "run_review", review)
    assert cli.main(arguments(workspace)) == 0
    assert seen["prompt"].startswith("Review.")
    assert frozen.base in seen["prompt"]
    assert "`git status --untracked-files=all`" in seen["prompt"]
    assert "`git diff HEAD`" in seen["prompt"]
    assert "?? added.py" in seen["status"] and "+candidate" in seen["diff"]


def test_dirty_sentence_is_for_a_dirty_worktree_and_never_for_a_candidate(
    monkeypatch, tmp_path, capsys
):
    """Escaping bug: a materialized candidate always differs from its base and read as dirty."""
    workspace, _ = ready(monkeypatch, tmp_path)
    # The materialized copy must sit under this test's directory to be read for real.
    (tmp_path / "materialized").mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "materialized"))
    monkeypatch.setattr(
        cli, "owned_reviewer_runner", lambda argv, **options: CommandResult(0, CLEAN_REVIEW_JSON)
    )
    sentence = "Pre-existing dirty worktree was unchanged."
    assert cli.main(arguments(workspace)) == 0
    gate = capsys.readouterr().out
    assert "**Status:** CLEAN_ADVISORY" in gate and sentence not in gate
    plain = [argument for argument in arguments(workspace) if argument != "--candidate"]
    plain[plain.index("diff")] = "plan"
    assert cli.main(plain) == 0
    assert sentence in capsys.readouterr().out
