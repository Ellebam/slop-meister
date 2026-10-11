"""Spine timing books session time to stages and waits without carrying log text."""

from datetime import UTC, datetime
import json
from pathlib import Path

from slopmeister.threads.timing.cli import main, scan
from slopmeister.threads.timing.events import command_kind
from slopmeister.threads.timing.report import row, table

BASE = 1_780_000_000.0
CWD = "/work/slopmeister/.worktrees/slopmeister-1-sample"
KICKOFF = "slopmeister-1-sample\n\nMode: spine\n\n## Outcome\n"
REVIEW = "bin/slopmeister review review --direction claude-to-codex --mode plan --cwd ."
REPORT = "**Result** stopped here\n**Your move** decide"
STATE = ".local/state"


def stamp(seconds: float) -> str:
    return datetime.fromtimestamp(BASE + seconds, UTC).isoformat().replace("+00:00", "Z")


def said(at: float, text: str, cwd: str = CWD) -> dict:
    message = {"content": text}
    return {"type": "user", "timestamp": stamp(at), "cwd": cwd, "origin": {"kind": "human"}} | {
        "message": message
    }


def used(at: float, until: float, tool: dict, task: str = "") -> list[dict]:
    """A tool call and its result. With a task it runs in the background and returns at `until`."""
    call = {"type": "tool_use", "id": f"call-{at}", **tool}
    result = {"type": "tool_result", "tool_use_id": f"call-{at}"}
    returned = stamp(at + 1 if task else until)
    records = [
        {
            "type": "assistant",
            "timestamp": stamp(at),
            "message": {"id": f"m{at}", "content": [call]},
        },
        {"type": "user", "timestamp": returned, "message": {"content": [result]}}
        | {"toolUseResult": {"backgroundTaskId": task} if task else {}},
    ]
    if task:
        note = f"<task-notification><task-id>{task}</task-id></task-notification>"
        origin = {"kind": "task-notification"}
        records.append(said(until, note) | {"origin": origin})
    return records


def ran(at: float, until: float, command: str, task: str = "") -> list[dict]:
    return used(at, until, {"name": "Bash", "input": {"command": command}}, task)


def edited(at: float, path: str) -> list[dict]:
    return used(at, at + 1, {"name": "Edit", "input": {"file_path": path, "new_string": "x"}})


def ended(at: float, seconds: float, text: str = "") -> list[dict]:
    answer = {"id": f"a{at}", "content": [{"type": "text", "text": text}]}
    return [
        {"type": "assistant", "timestamp": stamp(at), "message": answer},
        {"type": "system", "subtype": "turn_duration", "timestamp": stamp(at)}
        | {"durationMs": seconds * 1000},
    ]


def claude_log(home: Path, name: str, records: list[dict]) -> None:
    path = home / ".claude/projects/sample" / f"{name}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record) + "\n" for record in records))


def codex_log(home: Path, meta: dict, records: list[tuple[float, dict]]) -> None:
    lines = [{"type": "session_meta", "payload": {"originator": "codex-tui", "cwd": CWD, **meta}}]
    lines += [
        {"timestamp": stamp(at), "type": "event_msg", "payload": body} for at, body in records
    ]
    path = home / ".codex/sessions/2026/10/06" / f"rollout-{meta['id']}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))


def item(kind: str, **fields: object) -> dict:
    return {"type": "item_completed", "item": {"type": kind, **fields}}


def saved_run(home: Path, at: float, worker: str, status: str, state: str = STATE) -> None:
    root = home / state / "slopmeister/spine-tests" / f"run-{worker}-{at}"
    root.mkdir(parents=True)
    run = {"cwd": CWD, "worker_tool": worker, "started_at": BASE + at}
    (root / "run.json").write_text(json.dumps(run))
    done = run | {"status": status, "completed_at": BASE + at + 60}
    (root / "result.json").write_text(json.dumps(done))


def rows(home: Path) -> list[dict]:
    sessions = scan(home, BASE, home / STATE / "slopmeister/spine-tests")
    return sorted((row(session, "host") for session in sessions), key=lambda r: r["start"])


def spent(measured: dict, category: str) -> int:
    return sum(stage.get(category, 0) for stage in measured["stages"].values())


def test_batch_read_of_procedures_does_not_move_the_stage(tmp_path):
    """Escaping bug: a worker read its procedures in one command and was booked to the last one."""
    names = ("execute-plan", "implement", "local-qa", "test-guide")
    batch = "cat " + " ".join(f".claude/skills/{name}/SKILL.md" for name in names)
    records = [said(0, KICKOFF), *ended(60, 60), said(120, "go"), *ran(130, 131, batch)]
    records += [*ran(140, 200, REVIEW), *edited(260, "/work/src/a.py"), *ended(300, 180)]
    claude_log(tmp_path, "one", records)
    entered = rows(tmp_path)[0]["entered"]
    assert sorted(entered, key=entered.get) == ["frame", "answer", "plan-review", "implement"]
    assert entered["implement"] == BASE + 260


def test_output_carries_no_message_or_command_text(tmp_path):
    """Escaping bug: customer text from a session log reached the published rows."""
    records = [said(0, KICKOFF + "CUSTOMER-TEXT"), *ran(10, 20, "pytest customer-command")]
    records += [*edited(30, "/work/customer-file.py"), *ended(60, 60, "CUSTOMER-ANSWER")]
    claude_log(tmp_path, "one", records)
    text = [{"type": "text", "text": KICKOFF + "CUSTOMER-TEXT"}]
    events = [(0, item("UserMessage", content=text))]
    events += [(20, item("CommandExecution", command=["zsh", "-lc", "pytest customer-command"]))]
    events += [(30, item("FileChange", changes={"/work/customer-file.py": {"diff": "x"}}))]
    events += [(60, item("AgentMessage", content=[{"text": "CUSTOMER-ANSWER"}]))]
    codex_log(tmp_path, {"id": "w1"}, [*events, (61, {"type": "task_complete"})])
    measured = rows(tmp_path)
    assert {r["tool"] for r in measured} == {"claude", "codex"}
    assert all(r["counts"]["source_files"] == 1 for r in measured)
    assert "customer" not in json.dumps(measured).lower()


def test_idle_before_an_operator_message_is_operator_wait_and_before_a_task_return_is_process_wait(
    tmp_path,
):
    """Escaping bug: a night spent waiting for the operator was booked as worker time."""
    records = [said(0, KICKOFF), *ended(100, 100), said(1000, "go")]
    records += [*ran(1010, 1400, "long-job", task="b1")[:2], *ended(1100, 100)]
    records += [ran(1010, 1400, "long-job", task="b1")[2], *ended(1450, 50)]
    claude_log(tmp_path, "one", records)
    measured = rows(tmp_path)[0]
    assert spent(measured, "wait_operator") == 900
    assert spent(measured, "wait_process") == 300
    assert spent(measured, "model") + spent(measured, "tool") == 250


def test_codex_approval_reviews_are_counted_from_the_guardian_thread(tmp_path):
    """Escaping bug: approval reviews were missed because they live in a separate log file."""
    kickoff = item("UserMessage", content=[{"type": "text", "text": KICKOFF}])
    worker = [(0, kickoff), (100, {"type": "task_complete", "duration_ms": 100_000})]
    codex_log(tmp_path, {"id": "w1"}, worker)
    review = [(44, {"type": "task_complete", "duration_ms": 4_000})]
    guardian = {"id": "g1", "parent_thread_id": "w1", "thread_source": "guardian_review"}
    codex_log(tmp_path, guardian, review)
    measured = rows(tmp_path)
    assert len(measured) == 1
    assert measured[0]["counts"]["approvals"] == 1
    assert spent(measured[0], "approval") == 4


def test_table_numbers_sessions_of_unnamed_repositories(tmp_path):
    """Escaping bug: a field session name was published in the issue's table."""
    other = "/work/acme/.worktrees/acme-77-secret"
    claude_log(tmp_path, "one", [said(0, KICKOFF), *ended(60, 60)])
    claude_log(tmp_path, "two", [said(0, KICKOFF, other), *ended(60, 60)])
    printed = table(rows(tmp_path), {"slopmeister"})
    assert "slopmeister-1-sample" in printed
    assert "acme" not in printed
    assert "other-1" in printed


def test_resumed_session_starts_in_resume_not_frame(tmp_path):
    """Escaping bug: a redispatched session was booked as a second frame and a second answer."""
    claude_log(tmp_path, "one", [said(0, KICKOFF + "\n## Resume\n"), *ended(60, 60)])
    measured = rows(tmp_path)[0]
    assert measured["resumed"]
    assert list(measured["entered"]) == ["resume"]


def test_saved_tester_run_marks_the_tester_stage_without_a_logged_launch(tmp_path):
    """Escaping bug: a tester launched from a script left its session without a tester stage."""
    claude_log(tmp_path, "one", [said(0, KICKOFF), *ran(10, 900, "bash run-tester.sh")])
    saved_run(tmp_path, 100, "claude", "fail")
    measured = rows(tmp_path)[0]
    assert measured["tester_runs"] == ["fail"]
    assert measured["entered"]["tester"] == BASE + 100


def test_saved_tester_run_is_counted_in_one_session_of_a_shared_worktree(tmp_path):
    """Escaping bug: a redispatched task counted one tester run in every session of its worktree."""
    claude_log(tmp_path, "early", [said(0, KICKOFF), *ended(2000, 2000)])
    claude_log(tmp_path, "late", [said(1000, KICKOFF), *ended(3000, 2000)])
    saved_run(tmp_path, 1500, "claude", "pass")
    saved_run(tmp_path, 1600, "codex", "fail")
    early, late = rows(tmp_path)
    assert early["tester_runs"] == []
    assert late["tester_runs"] == ["pass"]


def test_a_mention_of_the_gate_is_not_a_gate_run(tmp_path):
    """Escaping bug: notes and commit messages that name `task check` counted as gate runs."""
    assert command_kind("cat >> notes.md <<'EOF'\n- `task check` passes.\nEOF") == "other"
    assert command_kind('pgrep -f "^task check" && echo running') == "other"
    assert command_kind('git commit -m "Run task check once"') == "commit"
    claude_log(tmp_path, "one", [said(0, KICKOFF), *ran(10, 12, "task check"), *ended(60, 60)])
    assert rows(tmp_path)[0]["counts"]["full_gates"] == 0


def test_a_halt_before_the_diff_review_is_not_the_handoff(tmp_path):
    """Escaping bug: a failed-tester halt was booked as the handoff and hid the diff review."""
    records = [said(0, KICKOFF), *ended(60, 60), said(120, "go"), *ran(130, 190, REVIEW)]
    records += [*edited(200, "/work/src/a.py"), *ended(400, 280, REPORT), said(500, "continue")]
    records += [*ran(510, 570, REVIEW.replace("plan", "diff")), *ended(600, 100, REPORT)]
    claude_log(tmp_path, "one", records)
    saved_run(tmp_path, 300, "claude", "fail")
    measured = rows(tmp_path)[0]
    assert sorted(measured["entered"], key=measured["entered"].get)[-3:] == [
        "tester", "diff-review", "accept",
    ]  # fmt: skip
    assert measured["entered"]["accept"] == BASE + 600
    assert measured["counts"]["halts"] == 1


def test_text_written_through_a_heredoc_is_not_a_command(tmp_path):
    """Escaping bug: a notes file with a bare `task check` line turned a test run into a gate."""
    command = "cat > notes.md <<'EOF'\ntask check passes on this branch\nEOF\npytest -q tests/unit"
    assert command_kind(command) == "test-run"
    claude_log(tmp_path, "one", [said(0, KICKOFF), *ran(10, 90, command), *ended(100, 100)])
    assert rows(tmp_path)[0]["counts"]["full_gates"] == 0


def test_tester_runs_are_read_where_the_launcher_saves_them(tmp_path, monkeypatch, capsys):
    """Escaping bug: with XDG_STATE_HOME set, the launcher saved runs that the timing never read."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "elsewhere"))
    claude_log(tmp_path, "one", [said(0, KICKOFF), *ended(900, 900)])
    saved_run(tmp_path, 100, "claude", "fail", "elsewhere")
    assert main(["--since", "2026-01-01T00:00:00Z"]) == 0
    assert json.loads(capsys.readouterr().out)["tester_runs"] == ["fail"]
