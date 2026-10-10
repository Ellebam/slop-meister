"""Bootstrap creates the external vault repository through the package command."""

import os
from pathlib import Path
import subprocess

from tests.support.repos import GIT_ENV

ROOT = Path(__file__).resolve().parents[3]


def test_vault_init_writes_only_under_home_and_repeats_as_current(tmp_path):
    """Escaping bug, the repository lands outside HOME or a second run rebuilds it."""
    home, vault = tmp_path / "home", tmp_path / "vault"
    (vault / "_system").mkdir(parents=True)
    (vault / "_system/start.md").write_text("# Fixture\n")
    home.mkdir()
    env = {**os.environ, **GIT_ENV, "HOME": str(home)}
    command = [str(ROOT / "bin/slopmeister"), "vault", "init", str(vault)]
    first = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
    second = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
    assert first.returncode == 0, first.stderr
    assert (home / ".vault-git/obsidian.git/info/exclude").is_file()
    assert sorted(p.name for p in vault.iterdir()) == ["_system"]
    assert second.returncode == 0 and "repository already exists" in second.stdout
