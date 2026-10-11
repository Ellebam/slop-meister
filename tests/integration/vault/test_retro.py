import os
from pathlib import Path
import subprocess

import pytest

from tests.support.fakes import fake_binary
from tests.support.repos import GIT_ENV

ROOT = Path(__file__).resolve().parents[3]
COMMAND = [str(ROOT / "bin/slopmeister"), "vault", "retro"]
ARGS = ["--repo", "fixture", "--task", "task", "--title", "title"]
ARGS += ["--tool", "codex", "--model", "model"]


def vaultgit(env: dict[str, str], *args: str, text: bool = False):
    return subprocess.run(
        [env["VAULTGIT"], *args],
        env={**os.environ, **env},
        capture_output=True,
        text=text,
        check=True,
    ).stdout


def fixture(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "fixture.md"
    note.write_text("# Retro\n")
    return note, repository_env(tmp_path, vault)


def run(
    tmp_path: Path,
    stdin: str,
    *,
    path: Path | None = None,
    arguments: list[str] | None = None,
    isolated_spill: bool = True,
    **extra: str,
):
    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "PATH": f"{path}:{os.environ['PATH']}" if path else os.environ["PATH"],
        **extra,
    }
    if isolated_spill:
        env["RETRO_SPILL_DIR"] = str(tmp_path / "spill")
    return subprocess.run(
        COMMAND + (arguments or [*ARGS, "--note", "fixture.md"]),
        input=stdin,
        env=env,
        capture_output=True,
        text=True,
    )


def repository_env(tmp_path: Path, vault: Path) -> dict[str, str]:
    git_dir = tmp_path / "vault.git"
    subprocess.run(["git", "init", "--bare", "-q", "-b", "main", git_dir], check=True)
    wrapper = fake_binary(
        tmp_path / "git-bin",
        "vaultgit",
        'exec git --git-dir="$VAULT_GIT_DIR" --work-tree="$SLOPMEISTER_VAULT" "$@"',
    )
    env = {
        **GIT_ENV,
        "SLOPMEISTER_VAULT": str(vault),
        "VAULT_GIT_DIR": str(git_dir),
        "VAULTGIT": str(wrapper),
        "SLOPMEISTER_VAULT_LOCKED": "1",
    }
    vaultgit(env, "add", "--", "fixture.md")
    vaultgit(env, "commit", "-q", "-m", "Fixture")
    return env


def unlocked_repository_env(tmp_path: Path, vault: Path) -> dict[str, str]:
    env = repository_env(tmp_path, vault)
    env.pop("SLOPMEISTER_VAULT_LOCKED")
    env["VAULT_LOCK"] = str(ROOT / "plots/vault/bin/vault-lock.py")
    env["RETRO_SPILL_DIR"] = str(tmp_path / "spill")
    slow = (
        '[ "$1" != add ] || sleep 0.2; exec git --git-dir="$VAULT_GIT_DIR" '
        '--work-tree="$SLOPMEISTER_VAULT" "$@"'
    )
    env["VAULTGIT"] = str(fake_binary(tmp_path / "slow-git", "vaultgit", slow))
    return env


def retro_writer(env: dict[str, str], task: str) -> subprocess.Popen[str]:
    arguments = [*ARGS, "--note", "fixture.md"]
    arguments[arguments.index("--task") + 1] = task
    return subprocess.Popen(
        [*COMMAND, *arguments],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )


def assert_late_replay_is_committed(
    tmp_path: Path, note: Path, spill: Path, git_env: dict[str, str]
) -> None:
    (spill / "late.md").write_text("### late owed\n\n- d\n- e\n- f\n")
    replayed = run(tmp_path, "good\nbad\nchange\n", **git_env)
    committed = vaultgit(git_env, "show", "HEAD:fixture.md", text=True)
    assert replayed.returncode == 0 and not list(spill.glob("*.md"))
    assert committed == note.read_text()


def test_retro_never_calls_obsidian_for_mission_critical_append(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "fixture.md"
    note.write_text("# Retro\n")
    marker = tmp_path / "obsidian-called"
    bin_dir = tmp_path / "bin"
    fake_binary(bin_dir, "obsidian", f"touch {marker}; exit 99")
    git_env = repository_env(tmp_path, vault)
    result = run(tmp_path, "good\nbad\nchange\n", path=bin_dir, **git_env)
    assert result.returncode == 0, result.stderr
    assert not marker.exists()
    assert note.read_text().count("### fixture, task, title,") == 1
    assert "### fixture, task, title," in vaultgit(git_env, "show", "HEAD:fixture.md", text=True)


def test_retro_appends_verifies_and_replays_once(tmp_path: Path) -> None:
    note, git_env = fixture(tmp_path)
    foreign = note.parent / "foreign.md"
    foreign.write_text("foreign\n")
    vaultgit(git_env, "add", "--", "foreign.md")
    spill = tmp_path / "spill"
    spill.mkdir()
    owed = "### owed\n\n- a\n- b\n- c\n"
    (spill / "old.md").write_text(owed)
    result = run(tmp_path, "good\nbad\nchange\n", **git_env)
    assert result.returncode == 0, result.stderr
    text = note.read_text()
    assert owed in text and "### fixture, task, title," in text
    assert "- good\n- bad\n- change\n" in text
    assert not list(spill.glob("*.md"))
    committed = vaultgit(git_env, "show", "HEAD:fixture.md", text=True)
    assert committed == text
    head = vaultgit(git_env, "rev-parse", "HEAD", text=True)
    again = run(tmp_path, "good\nbad\nchange\n", **git_env)
    assert again.returncode == 0
    assert note.read_text().count("### fixture, task, title,") == 1
    assert vaultgit(git_env, "rev-parse", "HEAD", text=True) == head
    assert_late_replay_is_committed(tmp_path, note, spill, git_env)
    staged = vaultgit(git_env, "diff", "--cached", "--name-only", text=True).splitlines()
    assert staged == ["foreign.md"]


def test_contended_retro_writers_replay_without_loss_or_duplicate(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "fixture.md"
    note.write_text("# Retro\n")
    env = {**os.environ, **unlocked_repository_env(tmp_path, vault)}
    (vault / "foreign.md").write_text("foreign\n")
    vaultgit(env, "add", "--", "foreign.md")
    tasks = tuple(f"writer-{index}" for index in range(5))
    commands = [retro_writer(env, task) for task in tasks]
    for process in commands:
        assert process.stdin is not None
        process.stdin.write("good\nbad\nchange\n")
        process.stdin.close()
        process.stdin = None
    results = [process.communicate(timeout=15) for process in commands]
    codes = [process.returncode for process in commands]
    assert all(code in (0, 1) for code in codes) and 0 in codes and 1 in codes, results
    settled = retro_writer(env, tasks[0])
    settled_result = settled.communicate("good\nbad\nchange\n", timeout=15)
    assert settled.returncode == 0, settled_result
    current = note.read_text()
    committed = vaultgit(env, "show", "HEAD:fixture.md", text=True)
    assert current == committed
    assert all(current.count(f"### fixture, {task}, title,") == 1 for task in tasks)
    assert not list((tmp_path / "spill").glob("*.md"))
    assert vaultgit(env, "diff", "--cached", "--name-only", text=True).splitlines() == [
        "foreign.md"
    ]


def test_retro_commit_failure_keeps_one_deduplicated_spill(tmp_path: Path) -> None:
    note, git_env = fixture(tmp_path)
    failed = {**git_env, "VAULTGIT": str(fake_binary(tmp_path / "fail-bin", "vaultgit", "exit 1"))}
    first = run(tmp_path, "good\nbad\nchange\n", **failed)
    second = run(tmp_path, "good\nbad\nchange\n", **failed)
    spills = list((tmp_path / "spill").glob("*.md"))
    assert first.returncode == second.returncode == 1
    assert "inspect Markdown and Git state for fixture.md" in first.stderr
    assert len(spills) == 1 and "### fixture, task, title," in spills[0].read_text()
    assert note.read_text().count("### fixture, task, title,") == 1
    assert (
        vaultgit(git_env, "status", "--short", "--", "fixture.md", text=True).strip()
        == "M fixture.md"
    )


def test_retro_failure_spills_exact_entry_and_invalid_input_never_writes(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    marker = tmp_path / "called"
    fake_binary(bin_dir, "obsidian", f"touch {marker}; echo 'Vault not found.'")
    result = run(tmp_path, "one\ntwo\nthree\n", path=bin_dir)
    assert result.returncode == 1 and "spilled to" in result.stderr
    spilled = list((tmp_path / "spill").glob("*.md"))
    assert len(spilled) == 1 and "- one\n- two\n- three\n" in spilled[0].read_text()
    assert not marker.exists()
    invalid = run(tmp_path, "one\ntwo\n", path=bin_dir)
    assert invalid.returncode == 2 and "exactly three lines" in invalid.stderr
    assert not marker.exists()


@pytest.mark.parametrize(
    ("arguments", "isolated", "extra", "message"),
    (
        (None, True, {"RETRO_FORBID_NOTE": "fixture.md"}, "forbidden"),
        (None, False, {}, "RETRO_SPILL_DIR"),
        ([*ARGS, "--note", "./fixture.md"], True, {"RETRO_FORBID_NOTE": "fixture.md"}, "forbidden"),
        ([*ARGS, "--note", "../outside.md"], True, {}, "vault-relative"),
        ([*ARGS, "--note", "/tmp/outside.md"], True, {}, "vault-relative"),
    ),
)
def test_retro_target_guards_precede_every_cli_call(
    tmp_path: Path,
    arguments: list[str] | None,
    isolated: bool,
    extra: dict[str, str],
    message: str,
) -> None:
    bin_dir = tmp_path / "bin"
    marker = tmp_path / "called"
    fake_binary(bin_dir, "obsidian", f"touch {marker}")
    result = run(
        tmp_path,
        "one\ntwo\nthree\n",
        path=bin_dir,
        arguments=arguments,
        isolated_spill=isolated,
        **extra,
    )
    assert result.returncode == 2 and message in result.stderr
    assert not marker.exists()
    assert not list((tmp_path / "spill").glob("*.md"))
