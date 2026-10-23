"""The public browser entry refuses unsafe requests without starting a browser or tool."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import pytest

from slopmeister.session import browser_state as state

ROOT = Path(__file__).resolve().parents[3]
ENTRY = ROOT / "src/skills/browser-login/scripts/browser.py"


def invoke(tmp_path, *arguments):
    env = {**os.environ, "HOME": str(tmp_path / "home"), "XDG_DATA_HOME": str(tmp_path / "data")}
    return subprocess.run(
        [sys.executable, str(ENTRY), *arguments],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_default_route_cannot_enable_persistent_authentication(tmp_path):
    result = invoke(tmp_path, "start", "https://example.com/", "--persistent")
    assert result.returncode == 1
    assert json.loads(result.stdout)["reason"] == "BROWSER_PERSISTENCE_REQUIRES_CHROME"
    assert not (tmp_path / "data").exists()


@pytest.mark.parametrize("route", ["orca", "chrome"])
@pytest.mark.parametrize(
    "command",
    [
        ["run-code", "process.exit()"],
        ["upload", "/tmp/private"],
        ["snapshot", "--filename=/tmp/output"],
        ["unknown"],
    ],
)
def test_page_refusal_keeps_owned_state_and_uses_no_installed_tool(tmp_path, route, command):
    with tempfile.TemporaryDirectory(prefix=state.PREFIX, dir=state.TEMP_ROOT) as created:
        root = Path(created)
        state.save(root, {"browser": route, "worktree": str(tmp_path)})
        before = (root / "owner.json").read_bytes()
        result = invoke(tmp_path, "page", str(root), *command)
        assert result.returncode == 1 and not result.stderr, result.stderr
        assert json.loads(result.stdout)["reason"] in {
            "BROWSER_COMMAND_REFUSED",
            "BROWSER_OPTION_REFUSED",
        }
        assert (root / "owner.json").read_bytes() == before
        assert {path.name for path in root.iterdir()} == {"owner.json"}
        assert not (tmp_path / "data").exists()


def test_legacy_orca_state_keeps_its_saved_route(tmp_path):
    with tempfile.TemporaryDirectory(prefix=state.PREFIX, dir=state.TEMP_ROOT) as created:
        root = Path(created)
        state.save(root, {"worktree": str(tmp_path)})
        result = invoke(tmp_path, "page", str(root), "snapshot")
        assert result.returncode == 1 and not result.stderr, result.stderr
        assert json.loads(result.stdout)["reason"] == "BROWSER_PAGE_REQUIRES_CHROME"
        assert not (tmp_path / "data").exists()


def test_explicit_clear_of_an_absent_profile_is_reported(tmp_path):
    result = invoke(tmp_path, "clear-profile")
    assert result.returncode == 0 and not result.stderr, result.stderr
    assert json.loads(result.stdout) == {"result": "BROWSER_PROFILE_ABSENT"}
    assert not (tmp_path / "data/slopmeister/browser/profile").exists()
