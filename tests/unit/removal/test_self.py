"""Self-cleanup validates first, stops its worker, and rechecks before deleting."""

import json

import pytest

from slopmeister import removal as guards
from slopmeister import workspace_removal as removal
from slopmeister.errors import SlopmeisterError
from slopmeister.slots import tester


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
    monkeypatch.setattr(guards, "git", removal._git)
    monkeypatch.setattr(removal, "check_companions", lambda *_: [])
    monkeypatch.setattr(removal, "_slot", lambda path, repo, **_: steps.append("slot"))
    monkeypatch.setattr(removal.claimed, "refuse", lambda *args: steps.append("claim"))
    caller = removal.occupants.Process(50, "codex", "?", "started", str(path), True, False)
    monkeypatch.setattr(
        removal.down, "_calling_worker", lambda *args: steps.append("caller") or caller
    )
    monkeypatch.setattr(removal, "_occupied", lambda path: steps.append("occupants"))

    def stop(request, repo, path, expected):
        assert expected is caller
        steps.append("stop")

    monkeypatch.setattr(removal.down, "_stop_worker", stop)
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
    with pytest.raises(SlopmeisterError, match="did not stop") as raised:
        removal.main([str(path), "--self"])
    assert path.exists() and "remove" not in steps
    # Raised before the fork, the session itself still runs and can act on the plain error.
    assert "workspace kept" not in str(raised.value)


def _forked(monkeypatch):
    """The detached helper is a fork, so it runs under another process identity."""
    forked = []
    monkeypatch.setattr(removal.down, "_detach", lambda log: forked.append(True) or True)
    monkeypatch.setattr(removal.os, "getpid", lambda: 2 if forked else 1)


@pytest.mark.parametrize("failing", ["_stop_worker", "_occupied", "_remove"])
def test_failed_detached_cleanup_names_the_workspace_and_its_command(context, monkeypatch, failing):
    """Bug: the terminal closes late or the final check refuses after the worker was told to
    stop, and the private log names neither the leftover workspace nor the command that removes
    it."""
    path, steps = context
    _forked(monkeypatch)

    def fail(*args):
        raise OSError("disk") if failing == "_remove" else SlopmeisterError("terminal still open")

    monkeypatch.setattr(removal.down if failing == "_stop_worker" else removal, failing, fail)
    command = f"task --dir {removal.ROOT} workspace:remove -- {path}"
    with pytest.raises(SlopmeisterError) as raised:
        removal.main([str(path), "--self"])
    text = str(raised.value)
    assert ("disk" if failing == "_remove" else "terminal still open") in text
    assert text.endswith(f"; workspace kept: {path}; when its worker has stopped, run: {command}")
    assert path.exists()


def test_failed_detached_slot_cleanup_names_the_slot_command(context, monkeypatch):
    """Bug: a slot whose release failed after its worker stopped is told to remove the plain
    workspace, which is refused for slots and frees none of its resources."""
    path, _ = context
    _forked(monkeypatch)
    repo = str(path.parent.parent)
    request = removal.down.Request(repo, "slopmeister", path.name, False, "3", True)
    monkeypatch.setattr(removal, "_slot", lambda *_, **__: request)
    monkeypatch.setattr(tester, "find", lambda *_: False)
    monkeypatch.setattr(removal.down, "_context", lambda _: None)

    def fail(_):
        raise SlopmeisterError("resource release failed")

    monkeypatch.setattr(removal.down, "_release", fail)
    with pytest.raises(SlopmeisterError) as raised:
        removal.main(["--self", "--", str(path)])
    command = f"task --dir {removal.ROOT} slot:down -- {repo} slopmeister {path.name} --slot 3"
    assert str(raised.value).endswith(f"; when its worker has stopped, run: {command}")


def test_failed_stop_only_names_no_cleanup(context, monkeypatch):
    """Bug: a paused session that failed to stop is told to remove its unfinished work."""
    path, _ = context
    _forked(monkeypatch)

    def fail(*args):
        raise SlopmeisterError("terminal still open")

    monkeypatch.setattr(removal.down, "_stop_worker", fail)
    with pytest.raises(SlopmeisterError) as raised:
        removal.main([str(path), "--self", "--stop-only"])
    assert str(raised.value) == "terminal still open"


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


@pytest.mark.parametrize("stop_only", [[], ["--stop-only"]])
def test_appended_force_after_the_terminator_never_reaches_shutdown(context, stop_only):
    """Codex matches prefixes, so an allowed tail must not turn on destructive options."""
    path, steps = context
    with pytest.raises(SystemExit) as error:
        removal.main(["--self", *stop_only, "--", str(path), "--force"])
    assert error.value.code == 2 and steps == [] and path.exists()


@pytest.mark.parametrize("flags", [["--stop-only"], ["--self", "--stop-only", "--force"]])
def test_stop_only_cannot_enable_removal_or_force(context, capsys, flags):
    path, steps = context
    with pytest.raises(SystemExit) as error:
        removal.main([*flags, "--", str(path)])
    assert error.value.code == 2 and steps == []
    assert "--stop-only requires --self and refuses --force" in capsys.readouterr().err


def test_stop_only_skips_deletion_guards_and_never_removes(context, monkeypatch, capsys):
    path, steps = context
    monkeypatch.setattr(removal.down, "_detach", lambda log: steps.append("detach") or True)
    assert removal.main(["--self", "--stop-only", "--", str(path)]) == 0
    assert steps == ["caller", "detach", "stop"]
    assert path.exists() and "session stopped; workspace kept:" in capsys.readouterr().out


@pytest.mark.parametrize("refusal", ["", "lease", "allocation"])
def test_slot_preflight_precedes_shared_shutdown(context, monkeypatch, capsys, refusal):
    """A slot uses the same entry and unique report log, with refusals before any stop."""
    path, steps = context
    request = removal.down.Request(
        str(path.parent.parent), "slopmeister", path.name, False, "1", True
    )
    monkeypatch.setattr(removal, "_slot", lambda *_, **__: request)
    monkeypatch.setattr(tester, "find", lambda *_: refusal == "lease")

    def prepare(_):
        steps.append("slot preflight")
        if refusal == "allocation":
            raise SlopmeisterError("allocation disagrees")

    monkeypatch.setattr(removal.down, "_context", prepare)
    monkeypatch.setattr(removal.down, "_detach", lambda log: steps.append(str(log)) or True)
    monkeypatch.setattr(removal.down, "_release", lambda _: steps.append("release") or 0)
    if refusal:
        with pytest.raises(SlopmeisterError, match="check lease|allocation disagrees"):
            removal.main(["--self", "--", str(path)])
        assert "stop" not in steps and "release" not in steps and path.exists()
    else:
        assert removal.main(["--self", "--", str(path)]) == 0
        assert steps.index("slot preflight") < steps.index("stop") < steps.index("release")
        assert any("scratch.remove." in step for step in steps)
        assert "remove" not in steps
