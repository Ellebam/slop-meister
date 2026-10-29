"""Named-commit refusal and cleanup preserve notes and report the actual child status."""

import errno
import fcntl
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

from tests.integration.vault.test_lock import LOCK
from tests.integration.vault.test_repository import repository as repository
from tests.integration.vault.test_repository import run, vaultgit
from tests.integration.vault.test_transaction_lifecycle import LOAD

CLEANUP = """from pathlib import Path
finish = lease.finish
def checked_finish(process, stopped, fd):
    assert lease.exit_status(process) is not None
    Path({marker}).write_text(str(process.pid))
    if {denied}:
        def denied(group, signum):
            assert group == process.pid
            assert signum in (lease.signal.SIGTERM, lease.signal.SIGKILL)
            raise PermissionError('cleanup denied')
        lease.os.killpg = denied
    return finish(process, stopped, fd)
lease.finish = checked_finish
raise SystemExit(lease.main())
"""


@pytest.fixture
def lease_repository(repository, tmp_path):
    env, vault = repository
    holder = tmp_path / "lease/vault-lock.py"
    holder.parent.mkdir(mode=0o700)
    holder.write_text(LOAD)
    holder.chmod(0o755)
    return env | {"VAULT_LOCK": str(holder)}, vault


@pytest.mark.parametrize("deny_cleanup", [False, True], ids=["natural", "denied"])
def test_named_commit_survives_exited_group_cleanup_denial(
    lease_repository, tmp_path, deny_cleanup
):
    original, vault = lease_repository
    env = {key: value for key, value in original.items() if key != "SLOPMEISTER_VAULT_LOCKED"}
    marker = tmp_path / "cleanup-group"
    holder = Path(env["VAULT_LOCK"])
    cleanup = CLEANUP.format(marker=repr(str(marker)), denied=deny_cleanup)
    holder.write_text(
        LOAD.replace("lease.COMMAND_TIMEOUT = 5", "lease.COMMAND_TIMEOUT = 10").replace(
            "raise SystemExit(lease.main())", cleanup
        )
    )
    holder.chmod(0o755)
    note = vault / "note.md"
    note.write_text("preserve this note\n")
    result = run("commit", "Record note", "--", "note.md", env=env)
    assert marker.exists(), result.stderr
    group = int(marker.read_text())
    committed = vaultgit(env, "show", f"HEAD:{note.relative_to(vault)}").stdout
    assert committed == note.read_text()
    assert result.returncode == 0, result.stderr
    warnings = [line for line in result.stderr.splitlines() if line.startswith("warning:")]
    assert len(warnings) <= 1
    message = f"vault process group {group} cleanup denied after child exit:"
    assert all(message in warning for warning in warnings)
    assert not deny_cleanup or len(warnings) == 1
    print(result.stderr, end="")


@pytest.fixture
def lease():
    spec = importlib.util.spec_from_file_location("vault_lock", LOCK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("denial", [errno.EPERM, errno.EACCES])
def test_terminal_denial_does_not_block_transaction(monkeypatch, lease, tmp_path, denial):
    def denied_open(path, flags):
        assert path == "/dev/tty"
        assert flags == lease.os.O_RDWR | lease.os.O_NOCTTY
        raise PermissionError(denial, "terminal denied", path)

    marker = tmp_path / "ran"
    command = [sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"]
    with monkeypatch.context() as terminal:
        terminal.setattr(lease.os, "open", denied_open)
        result = lease.transaction(command, {}, 2)
    assert result == 0
    assert marker.exists()


def test_cleanup_denial_while_child_runs_is_not_suppressed(monkeypatch, lease):
    def denied(*_):
        raise PermissionError("running child cleanup denied")

    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"], process_group=0
    )
    monkeypatch.setattr(lease.os, "killpg", denied)
    try:
        assert lease.exit_status(process) is None
        with pytest.raises(PermissionError, match="running child cleanup denied"):
            lease.finish(process, True, None)
    finally:
        process.kill()
        process.wait(timeout=3)


def test_busy_named_commit_keeps_the_file_uncommitted(lease_repository):
    original, vault = lease_repository
    env = {key: value for key, value in original.items() if key != "SLOPMEISTER_VAULT_LOCKED"}
    note = vault / "note.md"
    note.write_text("keep this note\n")
    before = vaultgit(env, "rev-parse", "HEAD").stdout
    lock = Path(env["VAULT_GIT_DIR"]) / "slopmeister-coordination/commit.lock"
    lock.parent.mkdir(exist_ok=True)
    with lock.open("a") as lease:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = run("commit", "Record note", "--", "note.md", env=env)
    assert result.returncode == 75 and "vault transaction busy" in result.stderr
    assert note.read_text() == "keep this note\n"
    assert vaultgit(env, "rev-parse", "HEAD").stdout == before
    assert vaultgit(env, "ls-files", "--", "note.md").stdout == ""


def test_timed_out_named_commit_keeps_notes_and_cleans_git_lock(lease_repository, tmp_path):
    original, vault = lease_repository
    env = dict(original)
    env.pop("SLOPMEISTER_VAULT_LOCKED")
    holder = Path(env["VAULT_LOCK"])
    holder.write_text(f"#!{sys.executable}\n" + LOAD.replace("0.2", "5"))
    holder.chmod(0o755)
    env["VAULT_LOCK"] = str(holder)
    entered = tmp_path / "hook-entered"
    hook = Path(env["VAULT_GIT_DIR"]) / "hooks/pre-commit"
    hook.write_text(
        f"#!{sys.executable}\nfrom pathlib import Path\nimport time\n"
        f"Path({str(entered)!r}).touch()\ntime.sleep(10)\n"
    )
    hook.chmod(0o755)
    (vault / "timeout.md").write_text("keep this note\n")
    before = vaultgit(env, "rev-parse", "HEAD").stdout
    result = run("commit", "Timeout", "--", "timeout.md", env=env)
    assert entered.exists() and result.returncode == 124, result.stderr
    assert "vault transaction timed out" in result.stderr
    assert (vault / "timeout.md").read_text() == "keep this note\n"
    assert vaultgit(env, "rev-parse", "HEAD").stdout == before
    assert not (Path(env["VAULT_GIT_DIR"]) / "index.lock").exists()
    hook.write_text("#!/bin/sh\nexit 0\n")
    assert run("commit", "Recovered", "--", "timeout.md", env=env).returncode == 0
