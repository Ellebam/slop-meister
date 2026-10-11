"""Session preparation inherits Git identity and signing without rewriting global files."""

from pathlib import Path
import subprocess

import pytest

from tests.integration.launch.helpers import launch, machine, target

IDENTITY_CONFIG = (
    "[user]\n"
    "\tname = Conditional Operator\n"
    "\temail = conditional@example.invalid\n"
    "\tsigningkey = {key}\n"
    "[gpg]\n\tformat = ssh\n"
    "[commit]\n\tgpgsign = true\n"
)


def _git(env: dict[str, str], repo: Path, *args: str, ok: bool = True):
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        env=env,
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) is ok, result.stdout + result.stderr
    return result


def _global_files(world, tmp_path: Path) -> dict[Path, bytes]:
    home = Path(world.env["HOME"])
    xdg = tmp_path / "xdg-config/git"
    xdg.mkdir(parents=True)
    files = {
        home / ".gitconfig": b'[includeIf "gitdir:~/elsewhere/**"]\n\tpath = ~/.elsewhere\n',
        xdg / "config": b"[user]\n\tname = XDG Operator\n",
        Path(world.env["GIT_CONFIG_GLOBAL"]): (
            b'[includeIf "gitdir:/unrelated/a/**"]\n\tpath = /tmp/a\n'
            b'[includeIf "gitdir:/unrelated/b/**"]\n\tpath = /tmp/b\n'
        ),
    }
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    world.env["XDG_CONFIG_HOME"] = str(tmp_path / "xdg-config")
    return files


def _signing_workspace(tmp_path: Path):
    world = machine(tmp_path)
    files = _global_files(world, tmp_path)
    repo = target(tmp_path / "customer/repo")
    key = tmp_path / "signing-key"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
        check=True,
    )
    identity = tmp_path / "customer.gitconfig"
    identity.write_text(IDENTITY_CONFIG.format(key=key))
    explicit = Path(world.env["GIT_CONFIG_GLOBAL"])
    explicit.write_bytes(
        explicit.read_bytes() + f'[includeIf "gitdir:{repo}/**"]\n\tpath = {identity}\n'.encode()
    )
    files[explicit] = explicit.read_bytes()
    for name in (
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
    ):
        world.env.pop(name, None)
    launch(world, str(repo), "example-client", "example-client-signed")
    return world, files, repo / ".worktrees/example-client-signed", key


@pytest.mark.parametrize("tool", ["claude", "codex"])
def test_launch_trust_and_redispatch_preserve_global_git_bytes(tmp_path, tool):
    """Bug: trust or session preparation rewrites a global Git config as collateral state."""
    world = machine(tmp_path)
    files = _global_files(world, tmp_path)
    repo = target(tmp_path / "repo")
    before = dict(files)

    launch(world, str(repo), "example-client", "example-client-git-config", "--tool", tool)
    assert {path: path.read_bytes() for path in files} == before
    launch(
        world,
        str(repo),
        "example-client",
        "example-client-git-config",
        "--tool",
        tool,
        "--redispatch",
    )
    assert {path: path.read_bytes() for path in files} == before
    launch(world, "example-client", "example-client-git-directory", "--directory", "--tool", tool)
    assert {path: path.read_bytes() for path in files} == before


def test_path_conditional_identity_and_signing_survive_operator_commit(tmp_path):
    """Bug: a prepared deny worktree loses its includeIf identity or produces unsigned commits."""
    world, files, worktree, key = _signing_workspace(tmp_path)
    (worktree / "application.txt").write_text("signed\n")
    _git(world.env, worktree, "add", "application.txt")
    _git(world.env, worktree, "commit", "-m", "Signed checkpoint")
    commit = _git(world.env, worktree, "cat-file", "commit", "HEAD").stdout
    assert "gpgsig -----BEGIN SSH SIGNATURE-----" in commit
    assert _git(world.env, worktree, "show", "-s", "--format=%ae", "HEAD").stdout.strip() == (
        "conditional@example.invalid"
    )
    assert {path: path.read_bytes() for path in files} == files

    (worktree / "application.txt").write_text("signer missing\n")
    _git(world.env, worktree, "add", "application.txt")
    head = _git(world.env, worktree, "rev-parse", "HEAD").stdout
    staged_tree = _git(world.env, worktree, "write-tree").stdout
    state = (
        Path(_git(world.env, worktree, "rev-parse", "--absolute-git-dir").stdout.strip())
        / "slopmeister-config/state.json"
    )
    state_bytes = state.read_bytes()
    key.unlink()

    failed = _git(world.env, worktree, "commit", "-m", "Unsigned checkpoint", ok=False)
    assert "No private key found" in failed.stderr
    assert _git(world.env, worktree, "rev-parse", "HEAD").stdout == head
    assert _git(world.env, worktree, "write-tree").stdout == staged_tree
    assert state.read_bytes() == state_bytes
    assert {path: path.read_bytes() for path in files} == files
