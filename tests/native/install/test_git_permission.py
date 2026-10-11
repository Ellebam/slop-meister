"""Installed Codex Git policy keeps agent writes behind native approval."""

import json
from pathlib import Path
import subprocess

from tests.integration.install.installer_helpers import prepared


def _decision(base, argv):
    result = subprocess.run([*base, *argv], capture_output=True, text=True, check=True, timeout=10)
    return json.loads(result.stdout)["decision"]


def test_deny_prompt_wins_over_saved_allow_without_prompting_read_only_git(tmp_path):
    """Bug: a broad home allow bypasses deny, or the project policy prompts harmless Git reads."""
    installed = prepared(tmp_path, "deny")
    saved = tmp_path / "saved.rules"
    saved.write_text('prefix_rule(pattern=["git"], decision="allow")\n')
    base = [
        str(Path.home() / ".local/bin/codex"),
        "execpolicy",
        "check",
        "--rules",
        str(installed.workspace / ".codex/rules/git-permission.rules"),
        "--rules",
        str(saved),
        "--",
    ]
    for command in ("commit", "merge", "rebase", "cherry-pick", "revert", "am", "pull", "push"):
        for argv in (
            ["git", command, "example"],
            ["git", "-C", str(installed.workspace), command, "example"],
        ):
            assert _decision(base, argv) == "prompt"
    for command in ("status", "diff", "add"):
        assert _decision(base, ["git", command, "example"]) == "allow"
