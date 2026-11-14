"""Real record shapes and growing history cannot hide valid running sessions."""

import json
import os

import pytest

from slopmeister.session import launch_identity
from slopmeister.threads.timing import cli, live
from tests.unit.threads.test_timing_live import BASE, NOW, log, stamp
from tests.unit.threads.test_timing_live import setup_live as setup_live


@pytest.mark.parametrize(
    "call",
    [
        {
            "type": "custom_tool_call",
            "name": "exec",
            "input": 'text(await tools.exec_command({cmd:"echo \\$HOME"}));',
        },
        {"type": "function_call", "name": "exec_command", "arguments": "{"},
        {"type": "function_call", "name": "exec_command", "arguments": "[]"},
    ],
)
def test_unparsable_call_keeps_live_and_historical_timing(setup_live, call):
    home, _, path = setup_live
    record = {"timestamp": stamp(950), "type": "response_item", "payload": call}
    path.write_text(path.read_text() + json.dumps(record) + "\n")
    os.utime(path, (NOW, NOW))
    (measured,) = live.rows("Linux")
    assert measured["state"] == "known"
    assert measured["stage"] == "implement"
    sessions = cli.scan(home, BASE, home / "old-tester-runs")
    assert len(sessions) == 1
    assert sessions[0].mode == "spine"


def test_old_and_other_plot_records_do_not_consume_candidate_cap(setup_live, monkeypatch):
    home, _, _ = setup_live
    log(home, home / "sample-2-finished", closed=True)
    for index in range(5):
        _, path = log(home, home / f"other-{index}-old", closed=True)
        os.utime(path, (NOW - 90 * 86400, NOW - 90 * 86400))
        log(home, home / f"other-{index}-recent", closed=True)
    monkeypatch.setattr(live.history, "MAX_FILES", 3)
    (measured,) = live.rows("Linux")
    assert measured["state"] == "known"
    assert measured["estimate_sessions"] == 1


def test_handoff_stays_known_without_history_budget(setup_live, monkeypatch):
    home, workspace, _ = setup_live
    session_id, _ = log(home, workspace, closed=True)
    launch_identity.write(workspace, (workspace.name, "codex", session_id))
    monkeypatch.setattr(live.history, "HISTORY_SECONDS", -1)
    (measured,) = live.rows("Linux")
    assert measured["state"] == "known"
    assert measured["stage"] == "accept"
    assert measured["estimate_sessions"] == 0


@pytest.mark.parametrize("kind", ["guardian", "freeform"])
def test_non_worker_metadata_skips_the_payload(setup_live, monkeypatch, kind):
    home, _, _ = setup_live
    _, path = log(home, home / "sample-2-guardian", closed=True)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if kind == "guardian":
        rows[0]["payload"]["thread_source"] = "guardian_review"
    else:
        rows[1]["payload"]["item"]["content"] = [{"text": "Mode: freeform"}]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    os.utime(path, (NOW, NOW))
    read = live.codex.read

    def read_worker(source, **kwargs):
        assert source != str(path), "Non-worker payload was read"
        return read(source, **kwargs)

    monkeypatch.setattr(live.codex, "read", read_worker)
    (measured,) = live.rows("Linux")
    assert measured["stage"] == "implement"


@pytest.mark.parametrize("starts", [False, True])
def test_passive_native_payload_keeps_time_without_decoding_duplicate_output(
    setup_live, monkeypatch, starts
):
    _, _, path = setup_live
    record = {
        "timestamp": stamp(990),
        "ordinal": 123,
        "type": "response_item",
        "payload": {
            "type": "custom_tool_call_output",
            "output": "PRIVATE-LARGE-OUTPUT",
        },
    }
    path.write_text(path.read_text() + json.dumps(record) + "\n")
    decode = json.loads

    def decode_action(raw, **kwargs):
        assert "PRIVATE-LARGE-OUTPUT" not in str(raw), "Unused output was decoded"
        return decode(raw, **kwargs)

    monkeypatch.setattr(json, "loads", decode_action)
    session, _ = live.codex.read(str(path), strict=True, starts=starts)
    assert max(session.activity) == BASE + 990


def test_historical_records_do_not_classify_live_call_starts(setup_live):
    home, _, path = setup_live
    record = {
        "timestamp": stamp(950),
        "type": "response_item",
        "payload": {
            "type": "function_call",
            "name": "exec_command",
            "arguments": json.dumps({"cmd": "bin/slopmeister review review --mode diff --cwd ."}),
        },
    }
    path.write_text(path.read_text() + json.dumps(record) + "\n")
    os.utime(path, (NOW, NOW))
    (measured,) = live.rows("Linux")
    assert measured["stage"] == "diff-review"
    (session,) = cli.scan(home, BASE, home / "old-tester-runs")
    assert session.command_starts == []
