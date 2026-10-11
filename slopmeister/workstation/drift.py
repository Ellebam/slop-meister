"""Read-only drift report. Home differences are notices in linked worktrees."""

import json
from pathlib import Path
import subprocess

from slopmeister.install import cli as install_cli
from slopmeister.paths import ROOT
from slopmeister.workstation import state

PLOT = "slopmeister"


def _home_install(home: Path) -> int:
    print("=== home install, both tools from one source ===")
    drifted = [item for item in state.items(home) if item.status != state.UNCHANGED]
    for item in drifted:
        word = {state.DIFFERS: "drifted", state.UNSAFE: state.UNSAFE}.get(item.status, "missing")
        print(f"  {word}: ~/{item.name}")
    return len(drifted)


def _git(*args: str) -> str:
    result = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def _prepared_worktree() -> int:
    # The launcher writes state.json only into a linked worktree's own git dir. Its folder
    # alone proves nothing, the main checkout keeps review results in the same place, but
    # anything at the state path itself is launcher state and must verify.
    git_dir = _git("rev-parse", "--absolute-git-dir")
    snapshot = Path(git_dir) / "slopmeister-config" / "state.json" if git_dir else None
    if snapshot is None or not snapshot.exists(follow_symlinks=False):
        return 0
    print("=== prepared worktree, delivered configuration against its saved state ===")
    try:
        grants = json.loads(snapshot.read_text())["grants"]
        argv = ["--check", PLOT, str(ROOT), *(a for g in grants for a in ("--grant", g))]
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"  invalid Slopmeister configuration state: {error}")
        return 1
    return int(install_cli.main(argv) != 0)


def drift(home: Path) -> int:
    count = _home_install(home)
    git_dir = _git("rev-parse", "--absolute-git-dir")
    common = _git("rev-parse", "--path-format=absolute", "--git-common-dir")
    if count and git_dir and common and git_dir != common:
        print(f"Notice: {count} home-install differences in this linked worktree")
        count = 0
    count += _prepared_worktree()
    print(f"Drifted or missing: {count}")
    return int(count > 0)
