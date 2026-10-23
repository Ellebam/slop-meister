"""Redispatch adopts a prepared workspace as it is, or refuses without repairing anything."""

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess

import pytest

from slopmeister.launch import closure
from slopmeister.launch.model import Stop
from tests.integration.launch.helpers import (
    CLI,
    Machine,
    codex_writable,
    declare,
    launch,
    launch_here,
    machine,
    snapshot,
    target,
    temporary_roots,
)
from tests.support.repos import git

PLOTS = {
    "inject": "example-client",
    "committed": "slopmeister",
    "seed": "example-app",
    "directory": "example-client",
}
CONFIG_REFUSED = "config-install:"


@dataclass
class Scene:
    world: Machine
    wt: Path
    args: list[str]


def _prepared(tmp_path: Path, mode: str, tool: str = "claude") -> Scene:
    world = machine(tmp_path)
    plot = PLOTS[mode]
    plots = declare(tmp_path / "declared", plot, "-" if mode == "directory" else mode)
    world.env["PLOT_DECLARATIONS"] = str(plots)
    name = f"{plot}-worker"
    if mode == "directory":
        wt, args = world.sessions / name, [plot, name]
    else:
        repo = target(tmp_path / "repo")
        git(repo, "remote", "add", "origin", "https://example.invalid/fixture/scratch.git")
        wt, args = repo / ".worktrees" / name, [str(repo), plot, name]
    launch(world, *args, "--tool", tool)
    return Scene(world, wt, [*args, "--tool", tool])


def _install(world: Machine, *args: str) -> None:
    subprocess.run([str(CLI), "install", *args], env=world.env, check=True, capture_output=True)


@pytest.mark.parametrize("tool", ["claude", "codex"])
@pytest.mark.parametrize("mode", ["inject", "committed", "seed", "directory"])
def test_adoption_preserves_workspace(tmp_path, mode, tool):
    """Bug: redispatch replays preparation and rewrites files, staging, branch or session state."""
    scene = _prepared(tmp_path, mode, tool)
    (scene.wt / f"{scene.wt.name}-NOTES.md").write_text("saved handoff\n")
    (scene.wt / ".slot.env").write_text("keep allocation\n")
    if mode != "directory":
        (scene.wt / "work.txt").write_text("staged\n")
        git(scene.wt, "add", "work.txt")
        (scene.wt / "work.txt").write_text("staged\nunstaged\n")
    root = tmp_path / ("sessions" if mode == "directory" else "repo")
    before = snapshot(root)
    result = launch(scene.world, *scene.args, "--redispatch")
    assert "existing workspace adopted" in result.stdout
    assert snapshot(root) == before
    upstream = {str(root.resolve())} if mode == "committed" else set()
    vault = str(scene.world.vault.resolve())
    assert codex_writable(scene.wt) == {
        vault,
        *upstream,
        *temporary_roots(scene.world),
        str(scene.wt / ".slopmeister-tmp"),
    }
    assert "--add-dir" not in result.stdout
    if mode != "directory":
        git(scene.wt, "commit", "-qm", "application")
        assert git(scene.wt, "branch", "--show-current").strip() == scene.wt.name


def _refuse_closure(monkeypatch) -> list[str]:
    """A regression would reach the real closure, so it stops here instead of closing a worker."""
    closed = []

    def close(launch):
        closed.append(launch.name)
        raise Stop(99, "closure reached")

    monkeypatch.setattr(closure, "close", close)
    return closed


def test_old_grant_refuses_before_closure(tmp_path, monkeypatch, capfd):
    """Bug: a pre-vault grant closes the running worker before refusing its replacement."""
    world = machine(tmp_path)
    repo = target(tmp_path / "repo")
    old, fresh = repo / ".worktrees/slopmeister-old", repo / ".worktrees/slopmeister-fresh"
    git(repo, "worktree", "add", "-q", "--no-track", "-b", old.name, str(old))
    _install(world, "--prepare", "slopmeister", str(old), "--grant", str(repo))
    before = snapshot(old)
    closed = _refuse_closure(monkeypatch)
    live = {"PLOT_SESSION_NO_LAUNCH": "0"}
    args = str(repo), "slopmeister", old.name, "--redispatch"
    assert launch_here(monkeypatch, world, *args, **live) == 1
    stderr = capfd.readouterr().err
    assert "saved configuration identity or permission disagrees" in stderr
    assert "report the refusal to the operator" in stderr
    assert (closed, snapshot(old)) == ([], before)
    launch(world, str(repo), "slopmeister", fresh.name)
    grants = "--grant", str(repo), "--grant", str(world.vault)
    _install(world, "--check", "slopmeister", str(fresh), *grants)
    assert snapshot(old) == before


def _state_dir(scene: Scene) -> Path:
    gitdir = Path(git(scene.wt, "rev-parse", "--absolute-git-dir").strip())
    return gitdir / "slopmeister-config"


def _remove(relative: str, state: bool = False):
    def damage(scene: Scene) -> dict[str, str]:
        path = (_state_dir(scene) if state else scene.wt) / relative
        shutil.rmtree(path) if path.is_dir() else path.unlink()
        return {}

    return damage


def _link(relative: str):
    def damage(scene: Scene) -> dict[str, str]:
        path, held = scene.wt / relative, scene.world.root / "held"
        path.rename(held)
        path.symlink_to(held)
        return {}

    return damage


def _env(key: str, value: str):
    def damage(scene: Scene) -> dict[str, str]:
        (scene.world.root / "a-file").write_text("not a directory\n")
        return {key: value.format(wt=scene.wt, tmp=scene.world.root)}

    return damage


def _git(*args: str):
    def damage(scene: Scene) -> dict[str, str]:
        git(scene.wt, "-c", "core.hooksPath=/dev/null", *args)
        return {}

    return damage


def _kickoff_directory(scene: Scene) -> dict[str, str]:
    kickoff = scene.world.state / f"{scene.wt.name}.md"
    kickoff.unlink()
    kickoff.mkdir()
    return {}


def _foreign(scene: Scene) -> dict[str, str]:
    shutil.rmtree(scene.wt)
    git(target(scene.world.root / "foreign"), "worktree", "add", "-q", "-b", "x", str(scene.wt))
    return {}


def _unregistered(scene: Scene) -> dict[str, str]:
    shutil.rmtree(scene.wt)
    scene.wt.mkdir()
    return {}


def _empty_metadata(scene: Scene) -> dict[str, str]:
    (_state_dir(scene) / "state.json").write_text("{}\n")
    return {}


def _permission_changed(scene: Scene) -> dict[str, str]:
    declared = Path(scene.world.env["PLOT_DECLARATIONS"]) / "example-client/plot.toml"
    declared.write_text(declared.read_text().replace('"allow"', '"deny"'))
    return {}


def _paragraph_removed(scene: Scene) -> dict[str, str]:
    agreement = scene.wt / "AGENTS.md"
    lines = agreement.read_text().splitlines(keepends=True)
    agreement.write_text("".join(line for line in lines if "Agent commit permission" not in line))
    return {}


REFUSALS = [
    ("inject", _remove("."), "existing workspace not found"),
    ("inject", _remove("AGENTS.md"), "incomplete"),
    ("inject", _remove(".agents/skills/sow"), "saved session configuration"),
    ("inject", _remove(".agents/skills/sow/SKILL.md"), CONFIG_REFUSED),
    ("inject", _remove(".claude/access-settings.json"), CONFIG_REFUSED),
    ("inject", _remove("state.json", state=True), CONFIG_REFUSED),
    ("inject", _empty_metadata, CONFIG_REFUSED),
    ("inject", _link(".agents/skills/sow/SKILL.md"), CONFIG_REFUSED),
    ("inject", _env("PLOT_SESSION_STATE_DIR", "{wt}/state"), "inside the adopted workspace"),
    ("inject", _env("CLAUDE_CONFIG_DIR", "{wt}/account"), "inside the adopted workspace"),
    ("inject", _env("PLOT_SESSION_WORKTREE_FILE", "{tmp}/a-file"), "do not pass PLOT_SESSION"),
    ("inject", _env("PLOT_SESSION_STATE_DIR", "{tmp}/a-file"), "state path is not a directory"),
    ("inject", _kickoff_directory, "output path is not a regular file"),
    ("inject", _git("checkout", "-q", "--detach"), "must have branch example-client-worker"),
    ("inject", _git("checkout", "-qb", "wrong"), "must have branch example-client-worker"),
    ("inject", _link("."), "symlinked workspace"),
    ("inject", _foreign, "belongs to a different repository"),
    ("inject", _unregistered, "worktree root"),
    ("inject", _permission_changed, "report the refusal to the operator"),
    ("inject", _paragraph_removed, "saved session configuration"),
    ("directory", _env("SLOPMEISTER_VAULT", "{tmp}/no-vault"), "vault not found at"),
    ("directory", _git("init", "-q"), "session directory lies inside a git repository"),
]


@pytest.mark.parametrize(("mode", "damage", "message"), REFUSALS)
def test_damaged_workspace_is_refused_unrepaired(tmp_path, mode, damage, message):
    """Bug: redispatch adopts a damaged or foreign workspace, or repairs it while refusing."""
    scene = _prepared(tmp_path, mode)
    env = damage(scene)
    before = snapshot(tmp_path)
    result = launch(scene.world, *scene.args, "--redispatch", ok=False, **env)
    assert message in result.stderr
    assert snapshot(tmp_path) == before
