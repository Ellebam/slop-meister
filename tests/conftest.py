"""The layer is the directory. Every test gets the marker of the layer it sits in."""

import os
from pathlib import Path
import shutil
import tempfile

import pytest

from slopmeister.removal import remove_tree

LAYERS = ("unit", "integration", "native", "live")


@pytest.fixture
def tmp_path(tmp_path, request):
    """Directory launches also inspect ancestor instructions, so a Git ceiling is insufficient."""
    if request.node.path.parent == Path(__file__).parent / "integration/launch":
        tmp_path = Path(tempfile.mkdtemp(prefix="slopmeister-launch-", dir=Path("/tmp").resolve()))
    try:
        yield tmp_path
    finally:
        # Retained test repositories can strand linked worktrees below a worker's scratch.
        if not request.node.get_closest_marker("real_home") and tmp_path.exists():
            remove_tree(tmp_path)


@pytest.fixture(autouse=True)
def isolated_home(request, monkeypatch, tmp_path_factory):
    """Defaults follow a fresh home, even when a subject gives its child another HOME."""
    if request.node.get_closest_marker("real_home"):
        return
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    # The installed launcher pins HOME to its own location, so PATH must find a private copy.
    entry = home / ".local/bin/slopmeister-vault"
    entry.parent.mkdir(parents=True)
    shutil.copy2(Path(__file__).resolve().parents[1] / "plots/vault/bin/slopmeister-vault", entry)
    entry.chmod(0o700)
    monkeypatch.setenv("PATH", f"{entry.parent}{os.pathsep}{os.environ.get('PATH', '')}")
    for name in (
        "SLOPMEISTER_VAULT",
        "VAULT_GIT_DIR",
        "VAULTGIT",
        "VAULT_LOCK",
        "SLOPMEISTER_VAULT_LAUNCHER",
        "SLOPMEISTER_VAULT_LOCKED",
        "CODEX_HOME",
        "ORCA_USER_DATA_PATH",
        "CLAUDE_CONFIG_DIR",
        "ORCA_CLAUDE_PROFILE_POINTER",
        "ORCA_CLAUDE_INJECTED_CONFIG_DIR",
        "ORCA_CLAUDE_USER_CONFIG_DIR",
        "XDG_CONFIG_HOME",
        "XDG_STATE_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def no_orca(monkeypatch, tmp_path_factory):
    """Removal tells Orca, so a test that names no stand-in reaches no Orca at all."""
    monkeypatch.setenv("PLOT_SESSION_ORCA", str(tmp_path_factory.getbasetemp() / "no-orca"))


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    tests_root = Path(config.rootpath) / "tests"
    for item in items:
        layer = Path(item.path).relative_to(tests_root).parts[0]
        if layer not in LAYERS:
            raise pytest.UsageError(f"{item.path} is outside the four layers {LAYERS}")
        item.add_marker(getattr(pytest.mark, layer))
    live = [item for item in items if item.get_closest_marker("live")]
    if live and not any("tests/live" in arg for arg in config.args):
        # Live tests start paid sessions, so only a command naming tests/live collects them.
        config.hook.pytest_deselected(items=live)
        items[:] = [item for item in items if item not in live]
