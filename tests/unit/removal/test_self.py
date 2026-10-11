"""Self-cleanup validates first, stops its worker, and rechecks before deleting."""

import json

import pytest

from slopmeister import workspace_removal as removal
from slopmeister.errors import SlopmeisterError


@pytest.fixture
def context(tmp_path, monkeypatch):
    repo, state = tmp_path / "main", tmp_path / "metadata"
    path = repo / ".worktrees/scratch"
    path.mkdir(parents=True)
    (path / ".git").touch()
    state.mkdir()
    (state / "state.json").write_text(json.dumps({"plot": "slopmeister"}))
    monkeypatch.setenv("PLOT_SESSION_STATE_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(removal, "_scope", lambda value: (path, repo))
    monkeypatch.setattr(removal, "_registered", lambda path, repo: True)
    monkeypatch.setattr(removal.evidence, "receipt_path", lambda path: state / "issue.json")
    monkeypatch.setattr(
        removal,
        "_git",
        lambda root, *args: (
            str(repo / ".git")
            if "--git-common-dir" in args
            else ""
            if "status" in args
            else str(path)
        ),
    )
    steps = []
    monkeypatch.setattr(removal, "_slot", lambda path, repo: steps.append("slot"))
    monkeypatch.setattr(removal.claimed, "refuse", lambda *args: steps.append("claim"))
    monkeypatch.setattr(removal.down, "_calling_worker", lambda *args: steps.append("caller"))
    monkeypatch.setattr(removal, "_occupied", lambda path: steps.append("occupants"))
    monkeypatch.setattr(removal.down, "_stop_worker", lambda *args: steps.append("stop"))
    monkeypatch.setattr(removal, "_remove", lambda *args: steps.append("remove") or 0)
    return path, steps


def test_detached_cleanup_stops_then_rechecks_before_removal(context, monkeypatch):
    """Bug: a self-cleanup removed a still-occupied workspace or skipped its second guards."""
    path, steps = context
    monkeypatch.setattr(removal.down, "_detach", lambda log: steps.append("detach") or True)
    assert removal.main([str(path), "--self"]) == 0
    assert steps == [
        "slot",
        "claim",
        "caller",
        "detach",
        "stop",
        "slot",
        "claim",
        "occupants",
        "remove",
    ]


def test_original_command_reports_pending_and_never_deletes(context, monkeypatch, capsys):
    """Bug: returning from the command claimed completed cleanup or deleted before shutdown."""
    path, steps = context
    monkeypatch.setattr(removal.down, "_detach", lambda log: False)
    assert removal.main([str(path), "--self"]) == 0
    assert "cleanup pending" in capsys.readouterr().out and path.exists()
    assert "remove" not in steps and "stop" not in steps


def test_shutdown_failure_keeps_the_workspace(context, monkeypatch):
    """Bug: deletion continued after the worker failed to stop."""
    path, steps = context
    monkeypatch.setattr(removal.down, "_detach", lambda log: True)

    def fail(*args):
        raise SlopmeisterError("worker did not stop")

    monkeypatch.setattr(removal.down, "_stop_worker", fail)
    with pytest.raises(SlopmeisterError, match="did not stop"):
        removal.main([str(path), "--self"])
    assert path.exists() and "remove" not in steps


def test_active_claim_refuses_before_detachment(context, monkeypatch):
    """Bug: self-cleanup stopped a worker before discovering its claim remained active."""
    path, steps = context

    def refuse(*args):
        raise SlopmeisterError("active claim")

    monkeypatch.setattr(removal.claimed, "refuse", refuse)
    monkeypatch.setattr(removal.down, "_detach", lambda log: pytest.fail("detached before refusal"))
    with pytest.raises(SlopmeisterError, match="active claim"):
        removal.main([str(path), "--self"])
    assert path.exists() and "stop" not in steps


def test_git_lock_refuses_self_cleanup_before_the_worker_is_stopped(context, monkeypatch):
    """Bug: self-cleanup stopped its worker before Git refused the locked registration."""
    path, steps = context
    (path / "locked").touch()
    monkeypatch.setattr(
        removal.down, "_detach", lambda log: pytest.fail("detached before lock check")
    )
    with pytest.raises(SlopmeisterError, match="locked"):
        removal.main([str(path), "--self", "--force"])
    assert path.exists() and "stop" not in steps
