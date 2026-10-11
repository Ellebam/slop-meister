"""Native prefix selection gates broad cleanup while leaving owned-PID cleanup unlisted."""

import json
from pathlib import Path
import subprocess

import pytest

from tests.native.install.discovery_fixture import CODEX

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    "command",
    [
        ["pkill", "-f", "x"],
        ["killall", "x"],
        ["docker", "volume", "prune"],
        ["docker", "system", "prune"],
        ["docker", "image", "prune"],
        ["docker", "container", "prune"],
    ],
)
def test_broad_cleanup_prompts_despite_an_inherited_allow(tmp_path, command):
    """Bug: an inherited executable-wide allow bypasses the cleanup intent rule."""
    saved = tmp_path / "saved.rules"
    saved.write_text(f'prefix_rule(pattern={json.dumps(command[:1])}, decision="allow")\n')
    result = subprocess.run(
        [
            str(CODEX),
            "execpolicy",
            "check",
            "--rules",
            str(saved),
            "--rules",
            str(ROOT / "dist/codex/rules/permissions.rules"),
            "--",
            *command,
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    assert json.loads(result.stdout)["decision"] == "prompt"


def test_direct_recorded_pid_kill_has_no_permission_prefix_rule():
    """Bug: guarding broad cleanup also adds a rule that blocks individual PID cleanup."""
    result = subprocess.run(
        [
            str(CODEX),
            "execpolicy",
            "check",
            "--rules",
            str(ROOT / "dist/codex/rules/permissions.rules"),
            "--",
            "kill",
            "12345",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    assert json.loads(result.stdout)["matchedRules"] == []
