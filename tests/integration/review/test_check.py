"""The diff check reviews and tests the snapshot commit or candidate in its own clean checkout."""

import json
from pathlib import Path
import shutil
import stat
import uuid

import pytest

from slopmeister.review import check, cli
from slopmeister.review.process import CommandResult
from slopmeister.review.schema import CrossToolReviewError
from slopmeister.session import launch_identity
from slopmeister.spine import candidate
from tests.support.repos import git, scratch_repo

GUIDE = "### Scenario basic: Read the subject\nRun `cat README.md`, expect its text.\n"
LENS = {"finding": None, "checks": ["secrets"], "evidence": "Nothing crosses a boundary."}


def answer(status="pass", quote="saved output"):
    rows = [{"id": "basic", "status": status, "reason": "", "evidence": [
        {"path": "evidence/basic.out", "quote": quote}]}]  # fmt: skip
    return json.dumps(
        {"findings": [], "security_lens": LENS, "scenarios": rows, "guide_findings": []}
    )


class Checker:
    """A stand-in reviewer process that saves evidence and may touch its copy."""

    def __init__(self, act=None, output=None):
        self.act, self.output, self.seen = act, output or answer(), []

    def __call__(self, argv, **options):
        cwd = Path(options["cwd"])
        root = cwd.parent
        self.seen.append((cwd, sorted(p.name for p in cwd.iterdir()), options.get("stdin_text")))
        (root / "evidence/basic.out").write_text("saved output\n")
        if self.act:
            self.act(cwd)
        return CommandResult(0, self.output)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    repo = scratch_repo(tmp_path / "check-task")
    monkeypatch.chdir(repo)
    session = str(uuid.uuid4())
    monkeypatch.setenv("CODEX_THREAD_ID", session)
    launch_identity.write(repo, (repo.name, "codex", session))
    (tmp_path / "guide.md").write_text(GUIDE)
    return repo


def run(workspace, checker, monkeypatch, *extra):
    monkeypatch.setattr(check, "owned_reviewer_runner", checker)
    guide = str(workspace.parent / "guide.md")
    return cli.main(
        ["review", "--direction", "codex-to-claude", "--mode", "diff", "--cwd", str(workspace),
         "--prompt", "Review.", "--guide", guide, *extra]
    )  # fmt: skip


def runs(tmp_path):
    return sorted((tmp_path / "state/slopmeister/checks").glob("run-*"))


def test_commit_check_tests_a_clean_copy_and_keeps_only_evidence(
    workspace, tmp_path, monkeypatch, capsys
):
    commit = git(workspace, "rev-parse", "HEAD").strip()
    checker = Checker()
    assert run(workspace, checker, monkeypatch) == 0
    cwd, names, prompt = checker.seen[0]
    assert cwd != workspace and cwd.name == "checkout" and ".slopmeister-config" not in names
    assert "Scenario IDs: basic." in prompt and str(cwd.parent / "guide.md") in prompt
    gate = capsys.readouterr().out
    assert "**Status:** CLEAN_ADVISORY" in gate and "- basic: pass" in gate
    assert f"**Tested:** commit {commit}" in gate
    [root] = runs(tmp_path)
    assert not (root / "checkout").exists() and (root / "evidence/basic.out").is_file()
    assert stat.S_IMODE(root.stat().st_mode) == 0o700


def test_failed_or_unproven_scenario_makes_the_gate_not_clean(workspace, monkeypatch, capsys):
    assert run(workspace, Checker(output=answer(quote="invented")), monkeypatch) == 1
    gate = capsys.readouterr().out
    assert "**Status:** TEST_INCOMPLETE" in gate and "evidence not verified" in gate


def test_uncommitted_change_is_refused_before_any_run(workspace, tmp_path, monkeypatch, capsys):
    (workspace / "README.md").write_text("edited\n")
    checker = Checker()
    assert run(workspace, checker, monkeypatch) == 1
    assert "worktree has uncommitted changes" in capsys.readouterr().out
    assert not checker.seen and not runs(tmp_path)


def test_diff_without_guide_names_the_flag_but_still_replays(workspace, monkeypatch, capsys):
    """A session on an older procedure learns the new input and still replays its saved result."""
    args = ["review", "--direction", "codex-to-claude", "--mode", "diff", "--cwd", str(workspace),
            "--prompt", "Review."]  # fmt: skip
    checker = Checker()
    monkeypatch.setattr(check, "owned_reviewer_runner", checker)
    assert cli.main(args) == 1
    assert "--mode diff needs --guide" in capsys.readouterr().out and not checker.seen
    assert run(workspace, checker, monkeypatch) == 0
    gate = capsys.readouterr().out
    assert cli.main(args) == 0 and len(checker.seen) == 1
    assert capsys.readouterr().out == gate
    plan = [*args[:4], "plan", *args[5:], "--guide", "/absent"]
    assert cli.main(plan) == 1
    assert "apply to --mode diff only" in capsys.readouterr().out


def test_checker_may_add_files_but_never_change_tested_ones(workspace, monkeypatch, capsys):
    added = Checker(act=lambda cwd: (cwd / "fixture.tmp").write_text("scenario output"))
    assert run(workspace, added, monkeypatch) == 0
    capsys.readouterr()
    shutil.rmtree(Path(git(workspace, "rev-parse", "--git-common-dir").strip()).resolve()
                  / "slopmeister-config/reviews")  # fmt: skip
    edited = Checker(act=lambda cwd: (cwd / "README.md").write_text("changed by the checker\n"))
    assert run(workspace, edited, monkeypatch) == 1
    assert "the checker changed the tested files" in capsys.readouterr().out


def test_candidate_check_tests_the_frozen_tree(workspace, tmp_path, monkeypatch, capsys):
    (workspace / "new.txt").write_text("candidate only\n")
    frozen = candidate.freeze(workspace, workspace.name)
    checker = Checker()
    assert run(workspace, checker, monkeypatch, "--candidate") == 0
    cwd, names, prompt = checker.seen[0]
    assert "new.txt" in names and frozen.base in prompt
    assert f"**Tested:** candidate tree {frozen.tree}" in capsys.readouterr().out
    assert not (runs(tmp_path)[0] / "checkout").exists()


def test_unverified_reviewer_stop_keeps_checkout_and_reports_it(
    workspace, tmp_path, monkeypatch, capsys
):
    def hang(argv, **options):
        raise CrossToolReviewError("reviewer timed out", category="TIMEOUT", process_stopped=False)

    assert run(workspace, hang, monkeypatch) == 1
    [root] = runs(tmp_path)
    assert (root / "checkout/README.md").is_file()
    assert "reviewer stop unverified" in capsys.readouterr().err


def test_readonly_cache_is_removed_and_outside_files_survive(workspace, tmp_path, monkeypatch):
    outside = tmp_path / "outside.txt"
    outside.write_text("unrelated bytes")
    outside.chmod(0o444)

    def cache(cwd):
        module = cwd / "tmp/go-mod/module"
        module.mkdir(parents=True)
        (module / "module.go").write_text("readonly module")
        (module / "outside-link").symlink_to(outside)
        (module / "module.go").chmod(0o444)
        for path in (module, module.parent):
            path.chmod(0o555)

    assert run(workspace, Checker(act=cache), monkeypatch) == 0
    assert not (runs(tmp_path)[0] / "checkout").exists()
    assert outside.read_text() == "unrelated bytes"
    assert stat.S_IMODE(outside.stat().st_mode) == 0o444


def test_checkout_symlink_is_never_followed_by_cleanup(workspace, tmp_path, monkeypatch, capsys):
    def replace(cwd):
        (cwd.parent / "evidence/kept.txt").write_text("retained proof")
        shutil.move(cwd, cwd.parent / "moved")
        cwd.symlink_to(cwd.parent / "evidence", target_is_directory=True)

    monkeypatch.setattr(check.Check, "verify", lambda self: None)
    assert run(workspace, Checker(act=replace), monkeypatch) == 0
    [root] = runs(tmp_path)
    assert (root / "evidence/kept.txt").read_text() == "retained proof"
    assert "checkout is a symlink, not removed" in capsys.readouterr().out


def test_checker_writing_into_the_worker_checkout_is_refused(workspace, monkeypatch, capsys):
    """The checker works in its own copy, the guard still watches the worker's live tree."""
    intruder = Checker(act=lambda cwd: (workspace / "intruder.txt").write_text("x\n"))
    assert run(workspace, intruder, monkeypatch) == 1
    assert "reviewer changed the worktree" in capsys.readouterr().out


def test_clone_keeps_the_worker_view_of_its_upstream(workspace, monkeypatch):
    """A prompt that diffs against origin/main must compare the same commits as the worker."""
    git(workspace, "checkout", "-qb", "upstream")
    (workspace / "upstream.txt").write_text("upstream\n")
    git(workspace, "add", "upstream.txt")
    git(workspace, "commit", "-qm", "Upstream")
    upstream = git(workspace, "rev-parse", "HEAD").strip()
    git(workspace, "checkout", "-q", "main")
    git(workspace, "branch", "-qD", "upstream")
    git(workspace, "update-ref", "refs/remotes/origin/main", upstream)
    seen = []
    checker = Checker(act=lambda cwd: seen.append(git(cwd, "rev-parse", "origin/main").strip()))
    assert run(workspace, checker, monkeypatch) == 0
    assert seen == [upstream]
