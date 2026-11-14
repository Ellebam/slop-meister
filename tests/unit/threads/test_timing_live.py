"""Live consumers get repeat counts and estimates only from usable session history."""

from datetime import UTC, datetime
import json
import os
from pathlib import Path
import uuid

import pytest

from slopmeister.errors import SlopmeisterError
from slopmeister.quality import identifiers
from slopmeister.session import launch_identity
from slopmeister.threads.timing import live
from slopmeister.threads.timing import records as native_records

BASE = 1_800_000_000
NOW = BASE + 1000
MANAGER = (
    "- Manager and your sole recovery owner: `sample-wave`, host Mac, `run:run_abc123`. More text."
)


def stamp(offset):
    return datetime.fromtimestamp(BASE + offset, UTC).isoformat()


def log(home, workspace, *, tool="codex", closed=False, manager=MANAGER):
    session_id = str(uuid.uuid4())
    kickoff = "Mode: spine\n" + manager
    if tool == "codex":
        root = home / ".codex/sessions/2027/01/01"
        rows = [
            {
                "type": "session_meta",
                "payload": {
                    "id": session_id,
                    "cwd": str(workspace),
                    "originator": "codex-tui",
                },
            }
        ]
        rows += [event(0, "UserMessage", content=[{"text": kickoff}])]
        rows += [event(100, "CommandExecution", command=["sh", "-c", review("plan")])]
        if not closed:
            rows += [event(150, "CommandExecution", command=["sh", "-c", review("plan")])]
        rows += [event(200, "FileChange", changes={"/work/code.py": {"diff": "x"}})]
        if closed:
            rows += [event(400, "CommandExecution", command=["sh", "-c", review("diff")])]
            rows += [
                event(
                    600, "AgentMessage", content=[{"text": "**Result** ready\n**Your move** test"}]
                )
            ]
            rows += [
                {"timestamp": stamp(600), "type": "event_msg", "payload": {"type": "task_complete"}}
            ]
        else:
            rows += [
                {"timestamp": stamp(900), "type": "event_msg", "payload": {"type": "token_count"}}
            ]
    else:
        root = home / ".claude/projects/sample"
        rows = [
            {
                "sessionId": session_id,
                "cwd": str(workspace),
                "type": "user",
                "timestamp": stamp(0),
                "message": {"content": kickoff},
            }
        ]
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{session_id}.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    os.utime(path, (NOW, NOW))
    return session_id, path


def review(mode):
    return f"bin/slopmeister review review --mode {mode} --cwd ."


def event(offset, kind, **values):
    return {
        "timestamp": stamp(offset),
        "type": "event_msg",
        "payload": {
            "type": "item_completed",
            "item": {"type": kind, **values},
        },
    }


@pytest.fixture
def setup_live(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(live.paths, "ROOT", tmp_path / "repository")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / ".codex"))
    monkeypatch.setenv("CODEX_THREAD_ID", str(uuid.uuid4()))
    monkeypatch.setattr(live.time, "time", lambda: NOW)
    patterns = tmp_path / "private-patterns"
    patterns.write_text("privateco\n")
    patterns.chmod(0o600)
    monkeypatch.setenv(identifiers.PATTERN_VARIABLE, str(patterns))
    plots = tmp_path / "plots/sample"
    plots.mkdir(parents=True)
    (plots / "plot.toml").write_text("")
    monkeypatch.setenv("PLOT_DECLARATIONS", str(plots.parent))
    workspace = tmp_path / "sample-1-task"
    workspace.mkdir()
    session_id, path = log(tmp_path, workspace)
    launch_identity.write(workspace, (workspace.name, "codex", session_id))
    entry = {"handle": "term_one", "agentIdentity": "codex", "worktreePath": str(workspace)}
    monkeypatch.setattr(live, "inventory", lambda: [entry])
    return tmp_path, workspace, path


def test_live_repeats_and_median_same_plot_handoff(setup_live):
    home, _, _ = setup_live
    log(home, home / "sample-2-history", closed=True)
    for task, finish in ((3, 700), (4, 900)):
        _, path = log(home, home / f"sample-{task}-history", closed=True)
        path.write_text(path.read_text().replace(stamp(600), stamp(finish)))
        os.utime(path, (NOW, NOW))
    log(home, home / "other-1-history", closed=True)
    (measured,) = live.rows("Linux")
    assert measured["state"] == "known"
    assert measured["stage"] == "implement"
    assert measured["plot"] == "sample"
    assert measured["extra_rounds"] == 1
    assert measured["manager"] == "run_abc123"
    assert measured["manager_host"] == "Mac"
    assert measured["estimate_sessions"] == 3
    assert measured["expected_finish_at"] == BASE + 700
    assert measured["total_seconds"] == 1000
    assert measured["step_seconds"] == 800


def test_no_history_and_missing_native_data_stay_unknown(setup_live):
    _, _, path = setup_live
    (measured,) = live.rows("Linux")
    assert measured["expected_finish_at"] is None
    assert measured["estimate_sessions"] == 0
    path.unlink()
    (measured,) = live.rows("Linux")
    assert measured["state"] == "unknown"
    assert measured["extra_rounds"] is None
    assert measured["estimate_sessions"] is None


def test_privacy_patterns_missing_or_matching_withhold_labels(setup_live, monkeypatch):
    home, _, _ = setup_live
    (measured,) = live.rows("privateco")
    assert measured["host"] is None
    monkeypatch.setenv(identifiers.PATTERN_VARIABLE, str(home / "absent"))
    (measured,) = live.rows("Linux")
    assert measured["name"] is None
    assert measured["host"] is None
    assert measured["plot"] is None
    assert measured["manager_host"] is None
    assert measured["session"]


def test_claude_directory_session_without_manager_keeps_progress(setup_live, monkeypatch):
    home, workspace, _ = setup_live
    session_id, path = log(home, workspace, tool="claude", manager="Dispatcher: run:run_other")
    launch_identity.write(workspace, (workspace.name, "claude", session_id))
    monkeypatch.setattr(
        live,
        "inventory",
        lambda: [
            {
                "agentIdentity": "claude",
                "worktreePath": str(workspace),
                "handle": "term_two",
            }
        ],
    )
    (measured,) = live.rows("Linux")
    assert measured["state"] == "known"
    assert measured["stage"] == "frame"
    assert measured["manager"] is None
    path.write_text(path.read_text().replace(session_id, str(uuid.uuid4())))
    (measured,) = live.rows("Linux")
    assert measured["state"] == "unknown"
    assert measured["stage"] is None


@pytest.mark.parametrize("damage", ["missing", "mismatch", "symlink", "malformed"])
def test_unreadable_or_untrusted_native_record_never_removes_session(setup_live, damage):
    home, _, path = setup_live
    if damage == "missing":
        path.unlink()
    elif damage == "mismatch":
        path.write_text(path.read_text().replace("sample-1-task", "sample-99-other"))
    elif damage == "symlink":
        target = home / "secret-record"
        path.rename(target)
        path.symlink_to(target)
    else:
        path.write_text(path.read_text() + "PRIVATE-BROKEN-RECORD\n")
    (measured,) = live.rows("Linux")
    assert measured["state"] == "unknown"
    assert measured["stage"] is None
    assert "PRIVATE" not in json.dumps(measured)


def test_partial_final_record_keeps_last_observed_step(setup_live):
    _, _, path = setup_live
    with path.open("a") as stream:
        stream.write('{"type":"event_msg",')
    (measured,) = live.rows("Linux")
    assert measured["stage"] == "implement"
    assert measured["last_activity_at"] == BASE + 900


def test_non_spine_session_is_present_with_unknown_step(setup_live):
    _, _, path = setup_live
    path.write_text(path.read_text().replace("Mode: spine", "Mode: freeform"))
    (measured,) = live.rows("Linux")
    assert measured["state"] == "unknown"
    assert measured["stage"] is None
    assert measured["expected_finish_at"] is None


def test_pending_review_is_visible_before_command_completion(setup_live):
    _, _, path = setup_live
    records = [json.loads(line) for line in path.read_text().splitlines()]
    records = records[:2]
    records += [
        {
            "timestamp": stamp(100),
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "name": "exec",
                "call_id": "call_one",
                "input": "text(await tools.exec_command({cmd:"
                + json.dumps(review("plan"))
                + "}));",
            },
        }
    ]
    path.write_text("".join(json.dumps(record) + "\n" for record in records))
    (measured,) = live.rows("Linux")
    assert measured["stage"] == "plan-review"
    assert measured["step_started_at"] == BASE + 100
    assert measured["extra_rounds"] == 0


def test_ambiguous_manager_is_unknown_and_dispatcher_is_not_a_manager(setup_live):
    _, _, path = setup_live
    replacement = MANAGER + "\n" + MANAGER.replace("run_abc123", "run_other")
    path.write_text(
        path.read_text().replace(json.dumps(MANAGER)[1:-1], json.dumps(replacement)[1:-1])
    )
    (measured,) = live.rows("Linux")
    assert measured["manager"] is None


def test_reading_history_does_not_count_live_tasks_as_estimates(setup_live, monkeypatch):
    home, workspace, _ = setup_live
    session_id, path = log(home, workspace, closed=True)
    launch_identity.write(workspace, (workspace.name, "codex", session_id))
    (measured,) = live.rows("Linux")
    assert measured["stage"] == "accept"
    assert measured["expected_finish_at"] is None
    assert measured["estimate_sessions"] == 0


def test_redispatch_keeps_earlier_workspace_time(setup_live):
    home, workspace, current = setup_live
    _, old = log(home, workspace)
    records = [json.loads(line) for line in old.read_text().splitlines()]
    for record in records:
        if "timestamp" in record:
            parsed = datetime.fromisoformat(record["timestamp"]).timestamp() - 1000
            record["timestamp"] = datetime.fromtimestamp(parsed, UTC).isoformat()
    old.write_text("".join(json.dumps(record) + "\n" for record in records))
    os.utime(old, (NOW, NOW))
    current.write_text(current.read_text().replace("Mode: spine", "Mode: spine\\n## Resume"))
    (measured,) = live.rows("Linux")
    assert measured["started_at"] == BASE - 1000
    assert measured["total_seconds"] == 2000


def test_history_budget_failure_is_unknown_instead_of_empty(setup_live, monkeypatch):
    monkeypatch.setattr(live.history, "HISTORY_SECONDS", -1)
    (measured,) = live.rows("Linux")
    assert measured["state"] == "unknown"
    assert measured["stage"] == "implement"
    assert measured["estimate_sessions"] is None
    assert measured["expected_finish_at"] is None


def test_inventory_fails_closed_on_partial_response(tmp_path, monkeypatch):
    monkeypatch.setattr(live.shutil, "which", lambda _: "orca")
    monkeypatch.setattr(
        live,
        "invoke",
        lambda run: json.dumps(
            {
                "ok": True,
                "result": {"truncated": True, "terminals": []},
            }
        ).encode(),
    )
    with pytest.raises(SlopmeisterError, match="inventory incomplete"):
        live.inventory()


def test_oversized_native_record_is_unknown(setup_live, monkeypatch):
    _, _, path = setup_live
    monkeypatch.setattr(native_records, "MAX_LINE_BYTES", 1024)
    record = {
        "type": "event_msg",
        "timestamp": stamp(950),
        "payload": {
            "type": "token_count",
            "private_payload": "x" * 1024,
        },
    }
    path.write_text(path.read_text() + json.dumps(record) + "\n")
    (measured,) = live.rows("Linux")
    assert measured["state"] == "unknown"
    assert measured["stage"] is None


def test_history_uses_exact_plot_and_counts_redispatch_once(setup_live):
    home, _, _ = setup_live
    extra = home / "plots/sample-extra"
    extra.mkdir()
    (extra / "plot.toml").write_text("")
    log(home, home / "sample-extra-2-history", closed=True)
    log(home, home / "sample-3-history", closed=True)
    log(home, home / "sample-3-history", closed=True)
    (measured,) = live.rows("Linux")
    assert measured["estimate_sessions"] == 1
    assert measured["expected_finish_at"] == BASE + 600


def test_unreadable_live_task_is_excluded_from_training(setup_live, monkeypatch):
    home, workspace, _ = setup_live
    other = home / "sample-2-running"
    other.mkdir()
    log(home, other, closed=True)
    monkeypatch.setattr(
        live,
        "inventory",
        lambda: [
            {"agentIdentity": "codex", "worktreePath": str(workspace), "handle": "term_one"},
            {"agentIdentity": "codex", "worktreePath": str(other), "handle": "term_two"},
        ],
    )
    rows = live.rows("Linux")
    assert len(rows) == 2
    measured = next(row for row in rows if row["state"] == "known")
    assert measured["estimate_sessions"] == 0
