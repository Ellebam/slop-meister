"""A file Claude Code writes at runtime blocks shipping, or a configuration change goes unnamed."""

import hashlib
import json

import pytest

from slopmeister.session import verify
from tests.support.trees import write

LOCK = ".claude/scheduled_tasks.lock"


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A directory workspace that matches its saved record, with the verifier bound to it."""
    repo = tmp_path / "workspace"
    write(repo, ".claude/settings.json", "{}\n")
    write(repo, ".claude/skills/ship/SKILL.md", "procedure\n")
    for name in verify.DIRECTORIES:
        (repo / name).mkdir(parents=True, exist_ok=True)
    helper = write(tmp_path, "state/config-install.py", "")
    state = {
        "version": verify.VERSION,
        "worktree": str(repo),
        "commit": "allow",
        "grants": [],
        "roots": list(verify.ROOTS),
        "allocation": None,
        "files": verify.snapshot(repo, list(verify.ROOTS)),
        "helper_sha256": hashlib.sha256(b"").hexdigest(),
        "directory": True,
    }
    write(tmp_path, "state/state.json", json.dumps(state))
    monkeypatch.setattr(verify, "entry", lambda: helper)
    return repo


def test_scheduler_lock_alone_still_verifies(workspace, capsys):
    """Bug: a session that scheduled a task cannot ship until the lock file is deleted by hand."""
    write(workspace, LOCK, '{"sessionId": "s", "pid": 1}\n')
    assert verify.main(["--verify-shipping"]) == 0, capsys.readouterr().err


@pytest.mark.parametrize(
    "changed",
    [
        ".claude/settings.json",
        ".claude/skills/ship/extra.md",
        ".claude/scheduled_tasks.json",
        LOCK + "-extra",
    ],
)
def test_changed_or_added_configuration_refuses_and_names_the_path(workspace, capsys, changed):
    """Bug: the lock exemption lets a configuration change ship, or the refusal names no path."""
    write(workspace, LOCK, "{}\n")
    write(workspace, changed, "tampered\n")
    assert verify.main(["--verify-shipping"]) == 1
    assert f'has changed or is incomplete: "{changed}";' in capsys.readouterr().err


def test_missing_file_with_a_null_saved_record_still_refuses(workspace, tmp_path, capsys):
    """Bug: a saved null compares equal to a missing file, so a deleted skill passes as verified."""
    skill = ".claude/skills/ship/SKILL.md"
    saved = tmp_path / "state/state.json"
    state = json.loads(saved.read_text())
    state["files"][skill] = None
    saved.write_text(json.dumps(state))
    (workspace / skill).unlink()
    assert verify.main(["--verify-shipping"]) == 1
    assert f'has changed or is incomplete: "{skill}";' in capsys.readouterr().err
