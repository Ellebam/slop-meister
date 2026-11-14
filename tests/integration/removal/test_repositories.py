"""An entire session is checked before its first companion is removed."""

import subprocess

from tests.integration.launch.helpers import CLI, declare, executable, launch, machine, target
from tests.support.repos import git


def test_dirty_companion_preserves_the_set_then_clean_removal_unregisters_it(tmp_path):
    world = machine(tmp_path)
    declare(tmp_path / "plots", "example-app", "committed")
    sources = [target(tmp_path / name) for name in ("entry", "service")]
    for repo in sources:
        (repo / "subject.txt").write_text("saved\n")
        git(repo, "add", "subject.txt")
        git(repo, "commit", "-qm", "Seed input")
    launch(
        world, str(sources[0]), "example-app", "example-app-clean", "--repository", str(sources[1])
    )
    executable(tmp_path / "bin/ps", "#!/bin/sh\nexit 0\n")
    primary = sources[0] / ".worktrees/example-app-clean"
    companion = primary / ".slopmeister-repos/service"
    (companion / "subject.txt").write_text("unsaved\n")
    argv = [str(CLI), "workspace-remove", str(primary)]
    refused = subprocess.run(argv, env=world.env, capture_output=True, text=True, timeout=30)
    assert refused.returncode != 0 and "uncommitted work" in refused.stderr
    assert primary.is_dir() and (companion / "subject.txt").read_text() == "unsaved\n"
    git(companion, "restore", "subject.txt")
    removed = subprocess.run(argv, env=world.env, capture_output=True, text=True, timeout=30)
    assert removed.returncode == 0, removed.stdout + removed.stderr
    assert not primary.exists()
    for repo in sources:
        assert "example-app-clean" not in git(repo, "worktree", "list")
        assert git(repo, "rev-parse", "--verify", "refs/heads/example-app-clean")
