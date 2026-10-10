"""Slot, launcher and claim state lives under the main checkout, whichever copy runs."""

from pathlib import Path

from slopmeister import paths
from slopmeister.claims import github, lifecycle
from slopmeister.launch.model import Launch
from slopmeister.slots import allocation
from tests.support import repos


def _linked(tmp_path, monkeypatch) -> Path:
    main = repos.scratch_repo(tmp_path / "main").resolve()
    repos.git(main, "worktree", "add", "-q", "-b", "side", ".worktrees/side")
    monkeypatch.setattr(paths, "ROOT", main / ".worktrees/side")
    monkeypatch.delenv("SLOT_STATE_DIR", raising=False)
    monkeypatch.delenv("PLOT_SESSION_STATE_DIR", raising=False)
    paths.main_checkout.cache_clear()
    return main


def test_launch_from_a_linked_worktree_keeps_state_under_the_main_checkout(tmp_path, monkeypatch):
    """Bug: slot state, kickoff and the saved Slopmeister path died with the launching worktree."""
    main = _linked(tmp_path, monkeypatch)
    try:
        assert allocation.state_path() == main / "tmp/slots"
        launch = Launch("scratch", "scratch-one", "")
        assert launch.kickoff_file == main / "tmp/plot-session/scratch-one.md"
        kickoff = tmp_path / "kickoff.md"
        kickoff.write_text("Mode: freeform\n")
        context = github.Repository(main, main / ".git", "owner/project", "remote", "scratch")
        operation = lifecycle.Initialization(main, 7, kickoff)
        assert lifecycle._new_receipt(context, operation, {})["slopmeister"] == str(main)
    finally:
        paths.main_checkout.cache_clear()


def test_a_repository_redirect_cannot_move_the_state(tmp_path, monkeypatch):
    """Bug: GIT_DIR pointed state discovery at another repository, written before any refusal."""
    main = _linked(tmp_path, monkeypatch)
    other = repos.scratch_repo(tmp_path / "other")
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    try:
        assert paths.main_checkout() == main
    finally:
        paths.main_checkout.cache_clear()


def test_state_overrides_still_win(tmp_path, monkeypatch):
    """Bug: the main-checkout default ignored the directories a test or operator names."""
    _linked(tmp_path, monkeypatch)
    monkeypatch.setenv("SLOT_STATE_DIR", str(tmp_path / "slots"))
    monkeypatch.setenv("PLOT_SESSION_STATE_DIR", str(tmp_path / "sessions"))
    try:
        assert allocation.state_path() == tmp_path / "slots"
        assert Launch("scratch", "scratch-one", "").state_dir == tmp_path / "sessions"
    finally:
        paths.main_checkout.cache_clear()


def test_a_copy_outside_git_keeps_its_own_directory(tmp_path, monkeypatch):
    """Bug: a copy without Git metadata lost its state directory."""
    monkeypatch.setattr(paths, "ROOT", tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    paths.main_checkout.cache_clear()
    try:
        assert paths.main_checkout() == tmp_path
    finally:
        paths.main_checkout.cache_clear()
