"""Native records must belong to the exact delivered worker."""

import json

import pytest

from slopmeister.claims import evidence
from slopmeister.opencode import launch as opencode_launch
from tests.support import trees

SESSION = "11111111-1111-4111-8111-111111111111"


def test_symlinked_receipt_never_redirects_a_write(tmp_path):
    original = trees.write(tmp_path, "original", "keep")
    link = tmp_path / "issue.json"
    link.symlink_to(original)
    with pytest.raises(ValueError):
        evidence.save(link, {"phase": "claimed"})
    assert original.read_text() == "keep"


def _rows(tool, workspace, text):
    if tool == "claude":
        rows = [
            {"type": "user", "sessionId": SESSION, "cwd": workspace, "message": {"content": text}}
        ]
        model = {"type": "assistant", "message": {"model": "claude-opus-version"}}
    else:
        rows = [
            {"type": "session_meta", "payload": {"id": SESSION, "cwd": workspace}},
            {
                "type": "response_item",
                "payload": {
                    "role": "user",
                    "type": "message",
                    "content": [{"type": "input_text", "text": text}],
                },
            },
        ]
        model = {"type": "turn_context", "payload": {"model": "native-model"}}
    return rows, model


def _lines(rows):
    return "".join(json.dumps(row) + "\n" for row in rows)


def _record(tmp_path, tool, rows):
    kickoff = trees.write(tmp_path, "kickoff.md", "Mode: spine\nDo the task.\n")
    transcript = trees.write(tmp_path, "native.jsonl", _lines(rows))
    record = {
        "workspace": str(tmp_path),
        "kickoff": str(kickoff),
        "kickoff_sha256": evidence.digest(kickoff, kickoff=True),
        "delivery": {"tool": tool, "session": SESSION, "evidence": str(transcript)},
    }
    return record, transcript


@pytest.mark.parametrize("tool", ["claude", "codex"])
def test_native_delivery_belongs_to_this_worker_whatever_the_model_rows(tmp_path, tool):
    """Bug: claims gates ownership on model row order, so a normal Codex first turn that
    records its model before the kickoff leaves a delivered worker unclaimed."""
    rows, model = _rows(tool, str(tmp_path), "Mode: spine\nDo the task.")
    record, transcript = _record(tmp_path, tool, rows)
    for order in (rows, rows[:-1] + [model, rows[-1]], rows + [model]):
        transcript.write_text(_lines(order))
        evidence.delivery_evidence(record)
    transcript.write_text(_lines(rows).rstrip("\n"))
    with pytest.raises(ValueError, match="delivery"):
        evidence.delivery_evidence(record)
    transcript.write_text(_lines(rows))
    record["delivery"]["session"] = "foreign"
    with pytest.raises(ValueError, match="delivery"):
        evidence.delivery_evidence(record)


@pytest.mark.parametrize("tool", ["claude", "codex"])
def test_foreign_cwd_transcript_is_not_delivery(tool, tmp_path):
    rows, _ = _rows(tool, str(tmp_path / "elsewhere"), "Mode: spine\nDo the task.")
    record, _ = _record(tmp_path, tool, rows)
    with pytest.raises(ValueError, match="delivery"):
        evidence.delivery_evidence(record)


@pytest.mark.parametrize("cwd", ["this", "elsewhere"])
def test_opencode_receipt_written_by_the_launcher_proves_delivery(tmp_path, cwd):
    """Bug: the launcher's OpenCode receipt and the claim check disagree, so a real worker's
    claim is refused or a foreign directory's session is accepted."""
    text = "Mode: spine\nDo the task."
    workspace = str(tmp_path) if cwd == "this" else str(tmp_path / "elsewhere")
    record, transcript = _record(tmp_path, "opencode", [])
    found = {"session": SESSION, "directory": workspace, "models": ["prov/model-a"]}
    transcript.chmod(0o644)
    opencode_launch._write(transcript, found, text)
    assert transcript.stat().st_mode & 0o777 == 0o600
    if cwd == "this":
        evidence.delivery_evidence(record)
    else:
        with pytest.raises(ValueError, match="delivery"):
            evidence.delivery_evidence(record)
