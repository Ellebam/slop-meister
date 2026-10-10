"""Vault repository creation and named commits through the package command."""

import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.support.fakes import fake_binary
from tests.support.repos import GIT_ENV

ROOT = Path(__file__).resolve().parents[3]
COMMAND = [str(ROOT / "bin/slopmeister"), "vault"]


def run(*args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(COMMAND + list(args), env=env, capture_output=True, text=True)


def vaultgit(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "git",
            f"--git-dir={env['VAULT_GIT_DIR']}",
            f"--work-tree={env['SLOPMEISTER_VAULT']}",
            *args,
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def repository(tmp_path: Path) -> tuple[dict[str, str], Path]:
    home, vault, git_dir = tmp_path / "home", tmp_path / "vault", tmp_path / "vault.git"
    home.mkdir()
    (vault / "_system").mkdir(parents=True)
    (vault / "_system/start.md").write_text("# Fixture\n")
    (vault / "_system/start.md").write_text("# Fixture\n")
    env = {
        **os.environ,
        **GIT_ENV,
        "HOME": str(home),
        "SLOPMEISTER_VAULT": str(vault),
        "VAULT_GIT_DIR": str(git_dir),
        "SLOPMEISTER_VAULT_LOCKED": "1",
    }
    result = run("init", env=env)
    assert result.returncode == 0, result.stderr
    wrapper = tmp_path / "vaultgit"
    wrapper.write_text(
        '#!/bin/sh\nexec git --git-dir="$VAULT_GIT_DIR" --work-tree="$SLOPMEISTER_VAULT" "$@"\n'
    )
    wrapper.chmod(0o755)
    env["VAULTGIT"] = str(wrapper)
    return env, vault


def test_init_is_external_idempotent_and_refuses_vault_git(tmp_path: Path) -> None:
    home, vault = tmp_path / "home", tmp_path / "vault"
    home.mkdir()
    (vault / "_system").mkdir(parents=True)
    (vault / "_system/start.md").write_text("# Fixture\n")
    env = {**os.environ, **GIT_ENV, "HOME": str(home), "SLOPMEISTER_VAULT": str(vault)}
    first = run("init", env=env)
    second = run("init", env=env)
    assert first.returncode == 0 and second.returncode == 0
    assert "repository already exists" in second.stdout
    assert sorted(path.name for path in vault.iterdir()) == ["_system"]
    assert (home / ".vault-git/obsidian.git/info/exclude").is_file()
    other = tmp_path / "other"
    (other / "_system").mkdir(parents=True)
    (other / ".git").mkdir()
    refused = run("init", str(other), env={**env, "VAULT_GIT_DIR": str(tmp_path / "other.git")})
    assert refused.returncode == 1 and "must hold nothing git-shaped" in refused.stderr


def test_init_restores_bundle_without_putting_git_in_vault(
    repository: tuple[dict[str, str], Path], tmp_path: Path
) -> None:
    env, _ = repository
    bundle = tmp_path / "history.bundle"
    assert vaultgit(env, "bundle", "create", str(bundle), "--all").returncode == 0
    restored, restored_git = tmp_path / "restored", tmp_path / "restored.git"
    (restored / "_system").mkdir(parents=True)
    result = run(
        "init",
        "--from-bundle",
        str(bundle),
        str(restored),
        env={**env, "SLOPMEISTER_VAULT": str(restored), "VAULT_GIT_DIR": str(restored_git)},
    )
    assert result.returncode == 0, result.stderr
    assert restored_git.is_dir() and not (restored / ".git").exists()


def test_named_commit_preserves_foreign_index_and_treats_specs_literally(
    repository: tuple[dict[str, str], Path],
) -> None:
    env, vault = repository
    (vault / "a.md").write_text("a\n")
    (vault / "foreign.md").write_text("foreign\n")
    assert vaultgit(env, "add", "--", "foreign.md").returncode == 0
    result = run("commit", "Move", "a", "--", "a.md", env=env)
    assert result.returncode == 0, result.stderr
    names = vaultgit(env, "show", "--name-only", "--format=", "HEAD").stdout.splitlines()
    assert names == ["a.md"]
    assert vaultgit(env, "diff", "--cached", "--name-only").stdout.strip() == "foreign.md"
    head = vaultgit(env, "rev-parse", "HEAD").stdout
    # Re-entry after a milestone commit must not commit again or report the clean path as failed.
    again = run("commit", "Milestone", "again", "--", "a.md", env=env)
    assert again.returncode != 0 and "nothing to commit" in again.stderr
    assert vaultgit(env, "rev-parse", "HEAD").stdout == head
    for spec in ("*.md", ":!a.md"):
        refused = run("commit", "Sweep", "--", spec, env=env)
        assert refused.returncode != 0
        assert vaultgit(env, "rev-parse", "HEAD").stdout == head
        assert vaultgit(env, "diff", "--cached", "--name-only").stdout.strip() == "foreign.md"


def test_named_commit_passes_the_message_as_one_argument_never_a_shell_word(
    repository: tuple[dict[str, str], Path],
) -> None:
    """Argv preservation only. A future shell call here would run unsandboxed in every session."""
    env, vault = repository
    (vault / "note.md").write_text("note\n")
    marker = vault / "marker"
    result = run("commit", f"Milestone $(touch {marker})", "--", "note.md", env=env)
    assert result.returncode == 0, result.stderr
    assert not marker.exists()
    assert vaultgit(env, "log", "-1", "--format=%s").stdout.strip() == (
        f"Milestone $(touch {marker})"
    )


def test_named_commit_requires_paths_and_uses_vault_relative_paths_from_any_cwd(
    repository: tuple[dict[str, str], Path], tmp_path: Path
) -> None:
    env, vault = repository
    before = vaultgit(env, "rev-parse", "HEAD").stdout
    refused = run("commit", "Sweep", env=env)
    assert refused.returncode == 2 and "explicit paths are required" in refused.stderr
    assert vaultgit(env, "rev-parse", "HEAD").stdout == before
    (vault / "sub").mkdir()
    (vault / "sub/note.md").write_text("note\n")
    result = subprocess.run(
        COMMAND + ["commit", "From", "outside", "--", "sub/note.md"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert vaultgit(env, "show", "-s", "--format=%s", "HEAD").stdout.strip() == "From outside"


def test_failed_named_commit_leaves_the_file_dirty_and_names_the_failed_phase(
    repository: tuple[dict[str, str], Path], tmp_path: Path
) -> None:
    env, vault = repository
    note = vault / "failed.md"
    note.write_text("retained\n")
    wrapper = fake_binary(
        tmp_path / "fail-bin",
        "vaultgit",
        'if [ "$1" = commit ]; then exit 9; fi; '
        'exec git --git-dir="$VAULT_GIT_DIR" --work-tree="$SLOPMEISTER_VAULT" "$@"',
    )
    result = run(
        "commit", "Fail", "safely", "--", "failed.md", env={**env, "VAULTGIT": str(wrapper)}
    )
    assert result.returncode == 1
    assert "commit failed; named paths remain dirty: failed.md" in result.stderr
    assert note.read_text() == "retained\n"
    assert vaultgit(env, "status", "--short", "--", "failed.md").stdout.strip() == "A  failed.md"


def test_named_commit_refuses_root_parent_absolute_and_control_paths(
    repository: tuple[dict[str, str], Path],
) -> None:
    env, vault = repository
    (vault / "changed.md").write_text("changed\n")
    head = vaultgit(env, "rev-parse", "HEAD").stdout
    for path in (".", "./", "././", "..", str(vault / "changed.md"), "bad\nname"):
        result = run("commit", "Refuse", "sweep", "--", path, env=env)
        assert result.returncode == 2 and "vault-relative" in result.stderr
        assert vaultgit(env, "rev-parse", "HEAD").stdout == head
    # A directory would sweep every changed note inside it, and this command is exempt from the
    # sandbox and the approval question in every session.
    (vault / "named").mkdir()
    (vault / "named/note.md").write_text("note\n")
    refused = run("commit", "Named", "directory", "--", "named", env=env)
    assert refused.returncode == 2 and "name each note, never a directory" in refused.stderr
    assert vaultgit(env, "rev-parse", "HEAD").stdout == head
    assert run("commit", "Named", "note", "--", "named/note.md", env=env).returncode == 0


def test_named_commit_pins_the_lock_interpreter(
    repository: tuple[dict[str, str], Path], tmp_path: Path
) -> None:
    original, vault = repository
    env = dict(original)
    env.pop("SLOPMEISTER_VAULT_LOCKED")
    env["VAULT_LOCK"] = str(ROOT / "plots/vault/bin/vault-lock.py")
    bin_dir = tmp_path / "bin"
    fake_binary(bin_dir, "python3", "echo intercepted >&2; exit 91")
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    launcher = tmp_path / "slopmeister-vault"
    launcher.write_text(
        f'#!/bin/sh\nexec "{Path(sys.executable)}" -P -m slopmeister.vault.runtime "$@"\n'
    )
    launcher.chmod(0o755)
    env["PYTHONPATH"] = str(ROOT)
    env["SLOPMEISTER_VAULT_LAUNCHER"] = str(launcher)
    (vault / "named").mkdir()
    (vault / "named/note.md").write_text("note\n")
    command = [sys.executable, "-P", "-m", "slopmeister", "vault", "commit"]
    result = subprocess.run(
        [*command, "Named", "note", "--", "named/note.md"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0 and "intercepted" not in result.stderr
    assert vaultgit(env, "show", "--name-only", "--format=", "HEAD").stdout.splitlines() == [
        "named/note.md"
    ]
