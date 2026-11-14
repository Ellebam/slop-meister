"""A worker start and a redispatch run on the Claude account selected in Orca at that moment."""

import json
from pathlib import Path

import pytest

from tests.integration.launch.helpers import Machine, launch, machine, target
from tests.support.repos import git


@pytest.fixture
def world(tmp_path) -> Machine:
    """An Orca terminal on System default with two account homes and no selection yet."""
    world = machine(tmp_path)
    del world.env["CLAUDE_CONFIG_DIR"]
    for name in ("first", "second"):
        (tmp_path / "accounts" / name / "home").mkdir(parents=True)
    world.env["ORCA_CLAUDE_PROFILE_POINTER"] = str(tmp_path / "selected-host")
    return world


def _select(world: Machine, name: str) -> Path:
    home = world.root / "accounts" / name / "home"
    (world.root / "selected-host").write_text(f"{home}\n")
    return home


def _trusted(store: Path, repo: Path) -> bool:
    if not store.is_file():
        return False
    project = json.loads(store.read_text())["projects"].get(str(repo), {})
    return project.get("hasTrustDialogAccepted") is True


def test_launch_and_redispatch_follow_the_selection_of_the_moment(world, tmp_path):
    """Bug: a worker starts on the system login, or a redispatch keeps the account it had."""
    repo = target(tmp_path / "repo")
    git(repo, "remote", "add", "origin", "https://example.invalid/fixture/scratch.git")
    args = [str(repo), "example-client", "example-client-one", "--tool", "claude"]
    first = _select(world, "first")
    started = launch(world, *args)
    assert f"env CLAUDE_CONFIG_DIR='{first}'" in started.stdout
    assert _trusted(first / ".claude.json", repo)

    second = _select(world, "second")
    moved = launch(world, *args, "--redispatch")
    assert f"env CLAUDE_CONFIG_DIR='{second}'" in moved.stdout
    assert _trusted(second / ".claude.json", repo)

    (tmp_path / "selected-host").write_text("")
    # The redispatching session itself still runs on the account Orca gave it.
    stale = {"CLAUDE_CONFIG_DIR": str(second), "ORCA_CLAUDE_INJECTED_CONFIG_DIR": str(second)}
    default = launch(world, *args, "--redispatch", **stale)
    assert "env -u CLAUDE_CONFIG_DIR" in default.stdout
    assert _trusted(tmp_path / "home/.claude.json", repo)


def test_missing_account_folder_stops_before_any_workspace(world, tmp_path):
    """Bug: a selection without its folder starts the worker on another account."""
    repo = target(tmp_path / "repo")
    (tmp_path / "selected-host").write_text(f"{tmp_path / 'accounts/gone/home'}\n")
    refused = launch(
        world, str(repo), "example-client", "example-client-one", "--tool", "claude", ok=False
    )
    assert f"{tmp_path / 'accounts/gone/home'} is not an existing directory" in refused.stderr
    assert "System default in Orca" in refused.stderr
    assert not (repo / ".worktrees/example-client-one").exists()
    assert not (tmp_path / "home/.claude.json").exists()
