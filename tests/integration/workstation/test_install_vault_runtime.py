"""The installed vault runtime and vaultgit under a scratch home. Nothing live is touched."""

import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.integration.workstation.test_install import ROOT, machine, workstation
from tests.support.fakes import fake_binary
from tests.support.repos import GIT_ENV

VAULT_RUNTIME_FILES = (
    "__init__.py",
    "__main__.py",
    "repository.py",
    "lint.py",
    "conflicts.py",
    "obsidian.py",
    "retro.py",
    "exclude",
)


def test_installed_vault_runtime_uses_exact_snapshot_and_safe_python_command(tmp_path):
    home, bin_dir = machine(tmp_path)
    assert workstation(home, bin_dir, "install", "--all").returncode == 0
    (bin_dir / "python3").unlink()
    fake_binary(bin_dir, "python3", "echo intercepted >&2; exit 91")
    launcher = home / ".vault-git/bin/slopmeister-vault"
    launcher_text = launcher.read_text()
    assert "/usr/local/bin/python3.14 /usr/bin/python3.14; do" in launcher_text
    assert 'exec "$python" -P -s -m slopmeister_vault "$@"' in launcher_text
    installed = home / ".vault-git/lib/slopmeister_vault"
    hostile = tmp_path / "hostile"
    (hostile / "slopmeister_vault").mkdir(parents=True)
    (hostile / "slopmeister_vault/__main__.py").write_text("print('hostile package')\n")
    (hostile / "argparse.py").write_text("raise RuntimeError('hostile argparse')\n")
    result = subprocess.run(
        [sys.executable, "-P", "-s", "-m", "slopmeister_vault", "--help"],
        cwd=hostile,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": str(bin_dir),
            "PYTHONPATH": str(installed.parent),
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0 and "hostile" not in result.stdout + result.stderr
    for name in VAULT_RUNTIME_FILES:
        source = ROOT / "slopmeister/vault/runtime" / name
        assert (installed / name).read_bytes() == source.read_bytes()


def test_the_launcher_is_also_on_path_under_the_name_the_allow_rules_use(tmp_path):
    """Without it the instructed bare command does not resolve and every commit prompts."""
    home, bin_dir = machine(tmp_path)
    assert workstation(home, bin_dir, "install", "--all").returncode == 0
    on_path = home / ".local/bin/slopmeister-vault"
    assert on_path.read_bytes() == (ROOT / "plots/vault/bin/slopmeister-vault").read_bytes()
    assert os.access(on_path, os.X_OK)


def linked_vault(tmp_path: Path, home: Path) -> Path:
    """A synced folder with a space in its path, reached through the one per-machine link."""
    vault = tmp_path / "My Drive/obsidian"
    (vault / "_system").mkdir(parents=True)
    (vault / "_system/start.md").write_text("# Start\n")
    (home / ".slopmeister").mkdir()
    (home / ".slopmeister/vault").symlink_to(vault)
    return vault


def runtime_env(home: Path, bin_dir: Path) -> dict[str, str]:
    env = {**os.environ, **GIT_ENV, "HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin"}
    for name in ("SLOPMEISTER_VAULT", "VAULT_GIT_DIR", "VAULTGIT"):
        env.pop(name, None)
    return env


def test_installed_named_commit_reaches_the_linked_default_vault(tmp_path):
    """Escaping bug: a runtime or wrapper default left on the old path fails every named commit."""
    home, bin_dir = machine(tmp_path)
    assert workstation(home, bin_dir, "install", "--all").returncode == 0
    vault = linked_vault(tmp_path, home)
    env = {
        **runtime_env(home, bin_dir),
        "PYTHONPATH": str(home / ".vault-git/lib"),
        "SLOPMEISTER_VAULT_LOCKED": "1",
    }
    runtime = [sys.executable, "-P", "-s", "-m", "slopmeister_vault"]
    init = subprocess.run([*runtime, "init"], env=env, capture_output=True, text=True)
    assert init.returncode == 0, init.stderr
    (vault / "_system/moved.md").write_text("# Moved\n")
    commit = subprocess.run(
        [*runtime, "commit", "Record the move", "--", "_system/moved.md"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert commit.returncode == 0, commit.stderr
    log = subprocess.run(
        [str(home / ".vault-git/bin/vaultgit"), "log", "-1", "--name-only", "--format=%s"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert log.stdout.split() == ["Record", "the", "move", "_system/moved.md"]


@pytest.mark.parametrize("override", [None, "home/.slopmeister/vault"])
def test_scheduled_job_writes_the_bundle_beside_the_linked_vault(tmp_path, override):
    """Escaping bug: the bundle lands beside the link or, for a relative override, in /Backups."""
    home, bin_dir = machine(tmp_path)
    assert workstation(home, bin_dir, "install", "--all").returncode == 0
    vault = linked_vault(tmp_path, home)
    env = {**runtime_env(home, bin_dir), "SLOPMEISTER_VAULT_LOCKED": "1", "VAULT_NOTIFY": "0"}
    if override:
        env["SLOPMEISTER_VAULT"] = override
    repository = home / ".vault-git/obsidian.git"
    subprocess.run(["git", "init", "--bare", "-q", str(repository)], check=True)
    job = subprocess.run(
        [str(home / ".vault-git/bin/vault-commit.sh")],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    log = (home / ".vault-git/vault-commit.log").read_text()
    assert job.returncode == 0 and "committed" in log and "bundle written" in log, log
    assert (vault.parent / "Backups/vault-history.bundle").is_file()
    assert not (home / ".slopmeister/Backups").exists()
