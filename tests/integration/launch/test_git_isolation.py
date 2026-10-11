"""Prepared worktrees isolate delivered files without replacing repository hooks."""

from pathlib import Path
import subprocess

from tests.integration.install.installer_helpers import git_result
from tests.integration.launch.helpers import executable, launch, machine, snapshot, target
from tests.support.repos import git


def _shared(repo: Path) -> tuple[list[str], list]:
    config = git(repo, "config", "--file", str(repo / ".git/config"), "--list")
    return config.splitlines(), snapshot(repo / ".git/hooks")


def _owner_commits(repo: Path, checkout: Path) -> bool:
    if checkout != repo and not checkout.exists():
        git(repo, "worktree", "add", "-q", "--no-track", "-b", checkout.name, str(checkout))
    result = git_result(checkout, "commit", "--allow-empty", "-m", "owner")
    return result.returncode == 0 and "owner-hook-ran" in result.stderr


def test_delivery_isolation_is_local_and_project_hooks_remain_normal(tmp_path):
    """Bug: injected-file isolation rewrites hooks or leaks unrelated worktree Git settings."""
    world = machine(tmp_path)
    repo = target(tmp_path / "repo")
    hook = executable(tmp_path / "owner/pre-commit", "#!/bin/sh\necho owner-hook-ran >&2\n")
    git(repo, "config", "core.hooksPath", str(hook.parent))
    executable(repo / ".git/hooks/pre-commit.sample", "#!/bin/sh\n")
    config, hooks = _shared(repo)
    expected = ([*config, "extensions.worktreeconfig=true"], hooks)

    launch(world, str(repo), "example-client", "example-client-wt1")
    worktree = repo / ".worktrees/example-client-wt1"
    gitdir = Path(git(worktree, "rev-parse", "--absolute-git-dir").strip())
    local_hooks = subprocess.run(
        ["git", "config", "--file", str(gitdir / "config.worktree"), "--get", "core.hooksPath"],
        capture_output=True,
        text=True,
    )
    exclude = git(worktree, "config", "--worktree", "--get", "core.excludesFile").strip()

    assert _shared(repo) == expected
    assert local_hooks.returncode != 0
    assert git(worktree, "config", "core.hooksPath").strip() == str(hook.parent)
    assert not Path(exclude).is_absolute() and (worktree / exclude).is_file()
    assert not (gitdir / "slopmeister-config/hooks").exists()
    assert _owner_commits(repo, worktree)
    assert _owner_commits(repo, repo)
    assert _owner_commits(repo, tmp_path / "theirs")
    assert git(repo, "status", "--porcelain") == ""
