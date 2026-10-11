"""The OpenCode tester: a proven pass, and every failure named as blocked, never as fail."""

import argparse
import hashlib
import json
import os
from pathlib import Path

import pytest

from slopmeister.opencode import tester as opencode_tester
from slopmeister.spine.tester import launch, runs, supervise
from tests.support import opencode_fake
from tests.support.repos import git

SECRET = "Zq8vN1opaqueProviderValue9x"
REJECTED = "The user rejected permission to use this specific tool call."
STOP = [{"type": "step_start"}, {"type": "step_finish", "part": {"reason": "stop"}}]


def _verdict() -> str:
    return json.dumps(
        {
            "scenarios": [
                {
                    "id": "basic",
                    "verdict": "pass",
                    "evidence": [{"path": "evidence/output.txt", "quote": "actual command output"}],
                }
            ],
            "regressions": [],
        }
    )


def _checkout(root: Path) -> Path:
    checkout = root / "checkout"
    checkout.mkdir(parents=True)
    git(checkout, "init", "-q")
    git(checkout, "commit", "-q", "--allow-empty", "-m", "init")
    (root / "evidence").mkdir()
    (root / "evidence/output.txt").write_text("actual command output\n")
    for name in ("guide.md", "validation.md"):
        (root / name).write_text("Approved fixture inputs")
    return checkout


def _run(tmp_path: Path, monkeypatch, state: dict, model: str = "") -> Path:
    root = tmp_path / "run"
    checkout = _checkout(root)
    config = tmp_path / "opencode.json"
    config.write_text('{"provider":{"p":{"options":{"apiKey":"{env:FAKE_PROVIDER_KEY}"}}}}')
    monkeypatch.setenv("OPENCODE_CONFIG", str(config))
    monkeypatch.setenv("FAKE_PROVIDER_KEY", SECRET)
    exported = opencode_fake.exported("ses_t", os.path.realpath(checkout), "")
    opencode_fake.install(tmp_path / "bin", {"run_export": exported, "session": "ses_t", **state})
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}")
    run = {
        **opencode_tester.settings(argparse.Namespace(tester_model=model)),
        "commit": git(checkout, "rev-parse", "HEAD").strip(),
        "checkout": str(checkout),
        "required": ["basic"],
    }
    run["input_hashes"] = {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in ("guide.md", "validation.md")
    }
    run["command"] = launch.build_command(run, root)
    runs.save(root / "run.json", run)
    return root


def _result(root: Path) -> dict:
    return json.loads((root / "result.json").read_text())


def test_opencode_pass_is_proven_from_its_native_session_and_cleaned_up(tmp_path, monkeypatch):
    """Bug: a pass without the native session, directory, prompt and model behind it."""
    text = {"type": "text", "part": {"text": "```json\n" + _verdict() + "\n```"}}
    root = _run(tmp_path, monkeypatch, {"events": [STOP[0], text, STOP[1]]})
    assert supervise.supervise(root) == 0
    result = _result(root)
    assert result["status"] == "pass"
    assert result["session_id"] == "ses_t"
    assert result["observed_model"] == "prov/model-a"
    assert result["session_deleted"] is True
    assert opencode_fake.state(tmp_path / "bin")["deleted"] == ["ses_t"]
    assert json.loads((root / "native.json").read_text())["finish"] == "stop"
    call = next(c for c in opencode_fake.calls(tmp_path / "bin") if c["argv"][0] == "run")
    assert call["claude_off"] == "1"
    permission = json.loads(call["config"])["permission"]
    assert permission["edit"] == "deny"
    assert permission["external_directory"] == {f"{root}/*": "allow"}
    assert "--auto" not in call["argv"]


@pytest.mark.parametrize(
    ("state", "reason", "pointer"),
    [
        (
            {
                "events": [
                    {
                        "type": "error",
                        "error": {
                            "name": "APIError",
                            "data": {"message": "<html>blocked</html>", "statusCode": 418},
                        },
                    }
                ],
                "run_exit": 1,
            },
            "provider error",
            "events.jsonl:1",
        ),
        (
            {"events": [STOP[0], {"type": "text", "part": {"text": "half"}}]},
            "interrupted",
            "events.jsonl:2",
        ),
        ({"events": []}, "no native evidence", "stderr.log"),
        (
            {"events": [STOP[0], {"type": "step_finish", "part": {"reason": "tool-calls"}}]},
            "interrupted",
            "events.jsonl:2",
        ),
        (
            {
                "events": [
                    STOP[0],
                    {
                        "type": "tool_use",
                        "part": {
                            "tool": "read",
                            "state": {
                                "status": "error",
                                "error": REJECTED,
                            },
                        },
                    },
                    {"type": "step_finish", "part": {"reason": "tool-calls"}},
                ]
            },
            "permission refused",
            "events.jsonl:2",
        ),
        (
            {"events": [*STOP, {"type": "text", "part": {"text": "not json"}}]},
            "no verdict",
            "events.jsonl:3",
        ),
    ],
    ids=[
        "provider-error",
        "interrupted",
        "no-session",
        "tool-calls-end",
        "permission-refused",
        "no-verdict",
    ],
)
def test_opencode_failures_are_named_blocked_reasons(tmp_path, monkeypatch, state, reason, pointer):
    """Bug: a provider outage or a killed run reads as a failed subject, or gives no pointer."""
    root = _run(tmp_path, monkeypatch, state)
    assert supervise.supervise(root) == 1
    result = _result(root)
    assert result["status"] == "blocked"
    assert result["blocked_reason"] == reason
    report = (root / "report.md").read_text()
    assert report.startswith(f"Tester BLOCKED: {reason}: ")
    assert pointer in report and "Fix: " in report


def test_requested_model_that_did_not_run_is_blocked(tmp_path, monkeypatch):
    """Bug: a silent model swap passes."""
    text = {"type": "text", "part": {"text": _verdict()}}
    root = _run(tmp_path, monkeypatch, {"events": [STOP[0], text, STOP[1]]}, model="prov/model-b")
    assert supervise.supervise(root) == 1
    assert "requested prov/model-b" in (root / "report.md").read_text()


def test_provider_value_reaches_opencode_but_no_run_file(tmp_path, monkeypatch):
    """Bug: the key is dropped so OpenCode cannot authenticate, or an echoed key is persisted."""
    text = {"type": "text", "part": {"text": _verdict()}}
    state = {"events": [STOP[0], text, STOP[1]], "echo": ["FAKE_PROVIDER_KEY"]}
    state["watch"] = ["FAKE_PROVIDER_KEY"]
    root = _run(tmp_path, monkeypatch, state)
    supervise.supervise(root)
    call = next(c for c in opencode_fake.calls(tmp_path / "bin") if c["argv"][0] == "run")
    assert call["env"] == {"FAKE_PROVIDER_KEY": True}
    assert "FAKE_PROVIDER_KEY" in json.loads((root / "run.json").read_text())["provider_names"]
    for path in root.rglob("*"):
        if path.is_file() and ".git" not in path.parts:
            assert SECRET not in path.read_text(errors="replace"), path
    assert (
        opencode_tester.supervisor_env(json.loads((root / "run.json").read_text()))[
            "FAKE_PROVIDER_KEY"
        ]
        == SECRET
    )


@pytest.mark.parametrize(
    ("worker", "tester", "expected"),
    [("claude", None, "codex"), ("codex", None, "claude"), ("opencode", "opencode", "refused")],
)
def test_tester_tool_selection(tmp_path, monkeypatch, worker, tester, expected):
    """Bug: the default opposite tool changes, or OpenCode tests its own work."""
    args = argparse.Namespace(worker_tool=worker, tester_tool=tester, tester_model=None)
    if expected == "refused":
        with pytest.raises(ValueError, match="same-tool testing refused"):
            launch._tester(args)
    else:
        assert launch._tester(args)["tool"] == expected


def test_missing_provider_variable_refuses_before_admission(tmp_path, monkeypatch):
    """Bug: a missing key creates a run even though no tester can start."""
    config = tmp_path / "opencode.json"
    config.write_text('{"x":"{env:FAKE_PROVIDER_KEY}"}')
    monkeypatch.setenv("OPENCODE_CONFIG", str(config))
    monkeypatch.delenv("FAKE_PROVIDER_KEY", raising=False)
    args = argparse.Namespace(worker_tool="claude", tester_tool="opencode", tester_model=None)
    with pytest.raises(ValueError, match="provider variable FAKE_PROVIDER_KEY unset"):
        launch._tester(args)
