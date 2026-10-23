"""A prepared worktree leaves the target clean and follows normal Git behavior."""

import os
import shutil
import subprocess

import pytest

from tests.integration.launch.helpers import ROOT, executable, launch, machine, target
from tests.support.repos import GIT_ENV, git

DENY = (
    b"Agent commit permission for this plot is deny: the agent has no standing authority to create "
    b"commits or push, and only the operator can tell it to. When the operator explicitly asks for "
    b"a commit or push in this conversation, run that command through the native tool action. The "
    b"configured reviewer checks that the operator explicitly approved that exact command once; "
    b"without that instruction leave the change uncommitted and report it. Approval does not "
    b"change the saved permission.\nAgent shipping permission for this session "
    b"is deny: there is no standing authority to push or create or update a PR. An explicit "
    b"operator instruction may approve the fixed ship command once; approval changes no saved "
    b"permission and grants no merge or stronger remote action.\n"
)


def test_prepared_worktree_is_clean_untracked_and_rooted(tmp_path):
    """Bug: plot files or the worktree dirty the field checkout, a tracking branch pushes to the
    field remote, or a subdirectory argument nests the worktree where the exclude misses it."""
    world = machine(tmp_path)
    repo = target(tmp_path / "repo")
    (repo / "sub").mkdir()
    git(repo, "config", "branch.autoSetupMerge", "always")
    launch(world, str(repo), "example-client", "example-client-wt1")
    worktree = repo / ".worktrees/example-client-wt1"
    assert not (repo / "sub/.worktrees").exists()
    assert git(repo, "status", "--porcelain") == ""
    assert git(worktree, "status", "--porcelain", "--untracked-files=all") == ""
    for tool, agreement in (("claude", "CLAUDE.md"), ("codex", "AGENTS.md")):
        render = (ROOT / f"dist/{tool}/plots/example-client.md").read_bytes()
        assert (worktree / agreement).read_bytes() == render + b"\n" + DENY
    upstream = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "example-client-wt1@{upstream}"],
        capture_output=True,
        env={**os.environ, **GIT_ENV},
    )
    assert upstream.returncode != 0, upstream.stdout


def test_exclude_append_is_idempotent_and_newline_safe(tmp_path):
    """Bug: every launch appends another exclude line, or glues it onto the owner's last line."""
    world = machine(tmp_path)
    repo = target(tmp_path / "repo")
    exclude = repo / ".git/info/exclude"
    exclude.write_text("their-last-line")
    launch(world, str(repo), "example-client", "example-client-wt1")
    launch(world, str(repo), "example-client", "example-client-wt2")
    lines = exclude.read_text().splitlines()
    assert "their-last-line" in lines
    assert lines.count("/.worktrees/") == 1


def test_target_checkout_hook_runs_normally(tmp_path):
    """Bug: worktree creation suppresses a repository hook through Slopmeister Git overrides."""
    world = machine(tmp_path)
    repo = target(tmp_path / "repo")
    canary = tmp_path / "canary"
    executable(repo / ".git/hooks/post-checkout", f"#!/bin/sh\ntouch '{canary}'\n")
    launch(world, str(repo), "example-client", "example-client-wt1")
    assert (repo / ".worktrees/example-client-wt1").is_dir()
    assert canary.exists()


@pytest.mark.parametrize("origin", [None, "https://example.invalid/other/scratch.git"])
def test_seed_never_contacts_origin(tmp_path, origin):
    """Bug: seed preparation reads an absent or unrelated origin and fails or leaks the target."""
    world = machine(tmp_path)
    repo = target(tmp_path / "repo")
    if origin:
        git(repo, "remote", "add", "origin", origin)
    log = tmp_path / "origin-reads"
    executable(
        tmp_path / "bin/git",
        f'#!/bin/sh\ncase " $* " in *" ls-remote "*|*" fetch "*|*" pull "*)\n'
        f"  echo \"$*\" >> '{log}'; exit 93 ;;\nesac\nexec '{shutil.which('git')}' \"$@\"\n",
    )
    launch(world, str(repo), "example-app", "example-app-seed")
    assert (repo / ".worktrees/example-app-seed/AGENTS.md").is_file()
    assert not log.exists()
