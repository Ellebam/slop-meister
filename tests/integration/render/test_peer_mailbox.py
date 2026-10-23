"""The delivered mailbox identity projection refuses uncertainty without printing previews."""

import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]
OWN = {"handle": "term-own", "agentIdentity": "codex-own", "title": "synthetic task"}


def projection():
    path = ROOT / "dist/codex/skills/plot-session/communicate.md"
    return path.read_text().split('"$orca_cli" terminal list', 1)[1].split("\n```", 1)[0]


def invoke(tmp_path, envelope, own="term-own"):
    fixture = tmp_path / "envelope.json"
    fixture.write_text(envelope if isinstance(envelope, str) else json.dumps(envelope))
    cli = tmp_path / "orca"
    cli.write_text('#!/bin/sh\ncat "$ENVELOPE"\n')
    cli.chmod(0o700)
    env = {
        **os.environ,
        "orca_cli": str(cli),
        "ENVELOPE": str(fixture),
        "ORCA_TERMINAL_HANDLE": own,
    }
    return subprocess.run(
        ["bash", "-c", '"$orca_cli" terminal list' + projection()],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=5,
    )


def test_only_the_unique_inherited_terminal_is_projected(tmp_path):
    rows = [
        {**OWN, "preview": "PRIVATE_PREVIEW"},
        {"handle": "term-peer", "preview": "PRIVATE_PREVIEW"},
    ]
    result = invoke(tmp_path, {"ok": True, "result": {"terminals": rows}})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"terminal": OWN}
    assert "PRIVATE_PREVIEW" not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "envelope",
    [
        "{",
        {"ok": False, "error": "PRIVATE_PREVIEW"},
        {"ok": True, "result": {"truncated": True, "terminals": [OWN]}},
        {"ok": True, "result": {"truncated": "false", "terminals": [OWN]}},
        {"ok": True, "result": {"truncated": None, "terminals": [OWN]}},
        {"ok": True, "result": {"terminals": []}},
        {"ok": True, "result": {"terminals": [OWN, OWN]}},
        {
            "ok": True,
            "result": {"terminals": [{**OWN, "agentIdentity": {"preview": "PRIVATE_PREVIEW"}}]},
        },
    ],
)
def test_malformed_truncated_missing_or_ambiguous_identity_stops(tmp_path, envelope):
    result = invoke(tmp_path, envelope)
    assert result.returncode != 0 and result.stdout == ""
    assert "PRIVATE_PREVIEW" not in result.stderr


def test_inherited_handle_cannot_be_borrowed_or_omitted(tmp_path):
    envelope = {"ok": True, "result": {"terminals": [OWN]}}
    for handle in ("term-other", ""):
        result = invoke(tmp_path, envelope, handle)
        assert result.returncode != 0 and result.stdout == ""


def test_both_tools_get_the_same_bounded_mailbox_contract():
    relative = "skills/plot-session/communicate.md"
    source = (ROOT / "src/skills/plot-session/communicate.md").read_bytes()
    assert (ROOT / "dist/codex" / relative).read_bytes() == source
    assert (ROOT / "dist/claude" / relative).read_bytes() == source
    text = source.decode()
    for obligation in (
        "in each participant's conversation",
        "absent binding",
        "differs from the recorded approved peer",
        "every message",
        "never an operator order",
        "write shared runtime state",
    ):
        assert obligation in text
