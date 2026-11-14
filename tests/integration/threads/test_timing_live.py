"""The live command retains a running session when its records are unavailable."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]


def test_live_cli_keeps_unreadable_session_and_withholds_names(tmp_path):
    workspace = tmp_path / "sample-1-task"
    workspace.mkdir()
    notes = workspace / "sample-1-task-NOTES.md"
    notes.write_text("Keep this task state unchanged.\n")
    tools = tmp_path / "bin"
    tools.mkdir()
    terminal = {
        "handle": "term_one",
        "agentIdentity": "codex",
        "connected": True,
        "orphaned": False,
        "executionHostId": "local",
        "worktreePath": str(workspace),
        "preview": "PRIVATE-SCREEN",
        "title": "PRIVATE-TICKET",
    }
    envelope = {"ok": True, "result": {"truncated": False, "terminals": [terminal]}}
    binary = tools / "orca"
    binary.write_text(
        f"#!{sys.executable}\nimport sys, os\n"
        "assert sys.argv[1:] == ['terminal', 'list', '--json']\n"
        "assert 'ORCA_ENVIRONMENT' not in os.environ\n"
        f"print({json.dumps(envelope)!r})\n"
    )
    binary.chmod(0o755)
    env = os.environ | {"HOME": str(tmp_path), "PATH": f"{tools}:{os.environ['PATH']}"}
    env.pop("SLOPMEISTER_PRIVATE_PATTERNS", None)
    env["ORCA_ENVIRONMENT"] = "wrong-remote"
    before = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in tmp_path.rglob("*")
        if p.is_file()
    }
    result = subprocess.run(
        [sys.executable, "bin/slopmeister", "spine-timing", "--live"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    (row,) = [json.loads(line) for line in result.stdout.splitlines()]
    assert row["state"] == "unknown"
    assert row["name"] is None
    assert row["stage"] is None
    assert (row["expected_finish_at"], row["estimate_sessions"]) == (None, None)
    assert "PRIVATE" not in result.stdout + result.stderr
    after = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in tmp_path.rglob("*")
        if p.is_file()
    }
    assert after == before
