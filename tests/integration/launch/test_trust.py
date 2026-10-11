"""A launch trusts its root while preserving unrelated native project configuration."""

import json
import os
from pathlib import Path
import shutil
import tomllib

import pytest

from tests.integration.launch.helpers import launch, machine, target


def _claude_store(root: str, other: str) -> tuple[str, dict]:
    foreign = {"allowedTools": ["Edit"], "mcpServers": {"docs": {"command": "docs"}}}
    projects = {root: {"hasTrustDialogAccepted": False, "allowedTools": ["Read"]}, other: foreign}
    trusted = {root: {"hasTrustDialogAccepted": True, "allowedTools": ["Read"]}, other: foreign}
    owner = {"numStartups": 3, "oauthAccount": {"emailAddress": "owner@example.invalid"}}
    return json.dumps({**owner, "projects": projects}), {**owner, "projects": trusted}


def _codex_store(root: str, other: str) -> tuple[str, dict]:
    text = (
        f'model = "top"\n[projects."{root}"]\ntrust_level = "untrusted"\n'
        f'[projects."{other}"]\ntrust_level = "trusted"\nallowedTools = ["Read"]\n'
        f'[projects."{other}".mcp_servers.docs]\ncommand = "docs"\n'
        '[profiles.fast]\nmodel = "owner"'
    )
    projects = {
        other: {
            "trust_level": "trusted",
            "allowedTools": ["Read"],
            "mcp_servers": {"docs": {"command": "docs"}},
        },
        root: {"trust_level": "trusted"},
    }
    return text, {"model": "top", "profiles": {"fast": {"model": "owner"}}, "projects": projects}


STORES = {
    "claude": (".claude.json", _claude_store, json.loads),
    "codex": ("config.toml", _codex_store, tomllib.loads),
}


def _store(world, tool: str) -> Path:
    return (world.claude if tool == "claude" else world.codex) / STORES[tool][0]


@pytest.mark.parametrize("tool", ["claude", "codex"])
@pytest.mark.parametrize("missing", [False, True])
def test_launch_trusts_main_checkout_root(tmp_path, tool, missing):
    """Bug: a worktree keys trust per worktree or by a symlinked spelling, or owner state breaks."""
    world = machine(tmp_path)
    repo = target(tmp_path / "repo")
    (tmp_path / "link").symlink_to(repo)
    _, seeded, parse = STORES[tool]
    other = tmp_path / ("disconnected-volume/repo" if missing else "vault")
    text, expected = seeded(str(repo), str(other))
    _store(world, tool).write_text(text)
    backup = Path(str(_store(world, tool)) + ".plot-session.bak")
    backup.write_bytes(b"previous recovery copy")
    launch(world, str(tmp_path / "link"), "example-client", "example-client-wt1", "--tool", tool)
    first = _store(world, tool).read_bytes()
    launch(world, str(repo), "example-client", "example-client-wt2", "--tool", tool)
    assert parse(_store(world, tool).read_text()) == expected
    assert _store(world, tool).read_bytes() == first
    assert backup.read_bytes() == b"previous recovery copy"
    assert not _store(world, "codex" if tool == "claude" else "claude").exists()


@pytest.mark.parametrize(
    ("tool", "spelling", "keys"),
    [
        ("claude", "vault/../sessions", lambda real: {str(real)}),
        (
            "codex",
            "sessions",
            lambda real: {str(real / "example-client-d1"), str(real / "example-client-d2")},
        ),
    ],
    ids=("claude", "codex"),
)
def test_directory_trust_keys(tmp_path, tool, spelling, keys):
    """Bug: Claude trusts each session folder or an unresolved root, or Codex misses the folder."""
    world = machine(tmp_path)
    real = tmp_path / "sessions"
    for name in ("example-client-d1", "example-client-d2"):
        launch(
            world,
            "example-client",
            name,
            "--directory",
            "--tool",
            tool,
            PLOT_SESSION_ROOT=str(tmp_path / spelling),
        )
    projects = STORES[tool][2](_store(world, tool).read_text())["projects"]
    assert set(projects) == keys(real)


def test_launch_prunes_only_owned_kickoff_pairs(tmp_path):
    """Owned kickoff cleanup must not remove unrelated native trust configuration."""
    world = machine(tmp_path)
    for name in ("example-client-gone", "example-client-live"):
        launch(world, "example-client", name, "--directory")
    shutil.rmtree(world.sessions / "example-client-gone")
    store = world.claude / ".claude.json"
    data = json.loads(store.read_text())
    data["projects"][str(tmp_path / "removed-worktree")] = {"hasTrustDialogAccepted": True}
    data["oauthAccount"] = {"emailAddress": "owner@example.invalid"}
    store.write_text(json.dumps(data))
    repo = target(tmp_path / "repo")
    output = launch(world, str(repo), "example-client", "example-client-wt1").stdout
    projects = json.loads(store.read_text())["projects"]
    assert set(projects) == {
        str(world.sessions),
        os.path.realpath(repo),
        str(tmp_path / "removed-worktree"),
    }
    assert json.loads(store.read_text())["oauthAccount"] == data["oauthAccount"]
    assert not Path(f"{store}.plot-session.bak").exists()
    assert "stale trust entries" not in output
    remaining = sorted(path.name for path in world.state.iterdir())
    assert remaining == [
        "example-client-live.command",
        "example-client-live.md",
        "example-client-wt1.command",
        "example-client-wt1.md",
    ]
