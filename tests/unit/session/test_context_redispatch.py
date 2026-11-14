"""Context recovery must refuse unsafe observations before a launcher is considered."""

import copy
import json

import pytest

from slopmeister.session import context_redispatch as context

SESSION = "00000000-0000-4000-8000-000000000001"
WORKSPACE = "/scratch/example-worker"
ROUTE = "run:run_example"


def readings():
    meter = dict(
        schema=1,
        available=True,
        complete=True,
        live=True,
        malformed=0,
        sessions=[
            {
                "client": "codex",
                "sessionId": SESSION,
                "workspace": "example-worker",
                "model": "example-model",
                "context": {"current": 100, "peak": 300, "window": 1000},
                "compactions": {"count": 3},
            }
        ],
    )
    status = {
        "ok": True,
        "result": {
            "truncated": False,
            "worktrees": [
                {
                    "path": WORKSPACE,
                    "agents": [{"agentType": "codex", "state": "done", "agentWait": None}],
                }
            ],
        },
    }
    return meter, status


def verify(meter=None, status=None, **changes):
    original_meter, original_status = readings()
    args = dict(
        workspace=WORKSPACE,
        tool="codex",
        session_id=SESSION,
        dispatcher=ROUTE,
        owner=ROUTE,
        receiver=ROUTE,
        handoff=True,
        questions_clear=True,
        windows_clear=True,
    )
    args.update(changes)
    return context.verify(
        original_meter if meter is None else meter,
        original_status if status is None else status,
        context.Request(**args),
    )


def test_three_compactions_request_once_after_safe_handoff():
    assert context.worker_action(2, False, True, True) == "continue"
    assert context.worker_action(3, False, True, True) == "request"
    assert context.worker_action(4, True, True, True) == "already-requested"
    assert context.worker_action(None, False, True, True) == "unknown"
    assert context.worker_action(3, False, False, True) == "protected"
    assert context.worker_action(3, False, True, False) == "protected"


def test_a_manager_requests_with_open_questions_but_never_in_an_open_window():
    """Bug: a manager always holds an open operator question, so it never requests recovery and
    runs out of context, or the exception also releases a worker or an open window."""
    assert context.worker_action(3, False, False, True, manager=True) == "request"
    assert context.worker_action(3, False, False, False, manager=True) == "protected"
    assert context.worker_action(3, False, True, False, manager=True) == "protected"
    assert context.worker_action(2, False, False, True, manager=True) == "continue"
    assert verify(manager=True, questions_clear=False) == "redispatch"
    assert verify(manager=True, questions_clear=False, windows_clear=False) == "window-not-clear"
    assert verify(manager=True, questions_clear=False, handoff=False) == "handoff-not-verified"


def test_the_manager_mark_is_read_from_delivered_instructions_only(tmp_path):
    """Bug: a linked or missing instruction file marks a worker as a manager."""
    assert not context.manager(tmp_path)
    (tmp_path / "AGENTS.md").write_text("Rules.\n" + context.MANAGER_MARK + " Monitor.\n")
    assert context.manager(tmp_path)
    worker, linked = tmp_path / "worker", tmp_path / "linked"
    worker.mkdir()
    linked.mkdir()
    (worker / "CLAUDE.md").write_text("Rules for a session dispatched as a manager.\n")
    (linked / "CLAUDE.md").symlink_to(tmp_path / "AGENTS.md")
    assert not context.manager(worker) and not context.manager(linked)


def test_only_the_dispatcher_flag_lets_a_manager_request_pass_verification(monkeypatch, capsys):
    """Bug: the flag never reaches the check, or verification skips the question check without
    the dispatcher naming the sender a manager."""
    monkeypatch.setattr(context, "observe", lambda host: readings())
    argv = ["verify", "--workspace", WORKSPACE, "--tool", "codex", "--session-id", SESSION]
    argv += ["--windows-clear", "--handoff-checked"]
    for name in ("dispatcher-run", "owner-run", "self-run"):
        argv += [f"--{name}", ROUTE]
    assert context.main([*argv, "--manager"]) == 0
    assert json.loads(capsys.readouterr().out) == {"action": "redispatch"}
    assert context.main(argv) == 1
    assert json.loads(capsys.readouterr().out) == {"action": "question-not-clear"}


def test_only_the_recovery_owner_can_launch_its_current_session():
    assert verify() == "redispatch"
    assert verify(owner="run:run_manager") == "forward"
    assert verify(owner="run:run_manager", receiver="run:run_manager") == "redispatch"
    assert verify(receiver="run:run_stranger") == "wrong-recovery-owner"
    assert verify(session_id="00000000-0000-4000-8000-000000000002") == "unknown-session"


def test_empty_duplicate_workspace_registration_is_not_a_second_agent():
    meter, status = readings()
    status["result"]["worktrees"].append({"path": WORKSPACE, "agents": []})
    assert verify(meter, status) == "redispatch"
    status["result"]["worktrees"].append(copy.deepcopy(status["result"]["worktrees"][0]))
    assert verify(meter, status) == "unknown-agent"


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"handoff": False}, "handoff-not-verified"),
        ({"questions_clear": False}, "question-not-clear"),
        ({"windows_clear": False}, "window-not-clear"),
        ({"dispatcher": ""}, "unknown-route"),
    ],
)
def test_unverified_saved_state_never_becomes_recovery_authority(change, reason):
    assert verify(**change) == reason


@pytest.mark.parametrize("bad", [None, True, -1, "3", 3.5])
def test_unknown_compaction_count_is_not_a_candidate(bad):
    meter, status = readings()
    meter["sessions"][0]["compactions"]["count"] = bad
    assert verify(meter, status) == "unknown-figures"


@pytest.mark.parametrize(
    "mutation,reason",
    [
        (lambda m, s: m.update(available=False), "unavailable-meter"),
        (lambda m, s: m.update(live=False), "unavailable-meter"),
        (lambda m, s: m.update(complete=False), "unavailable-meter"),
        (lambda m, s: m.update(malformed=1), "unavailable-meter"),
        (lambda m, s: m["sessions"][0]["context"].update(current=None), "unknown-figures"),
        (lambda m, s: m["sessions"].append(copy.deepcopy(m["sessions"][0])), "unknown-session"),
        (lambda m, s: s.update(ok=False), "unavailable-host"),
        (lambda m, s: s["result"].update(truncated=True), "unavailable-host"),
        (
            lambda m, s: s["result"]["worktrees"][0]["agents"][0].update(state="working"),
            "turn-not-ended",
        ),
        (lambda m, s: s["result"]["worktrees"][0]["agents"][0].pop("agentWait"), "wait-not-clear"),
        (
            lambda m, s: s["result"]["worktrees"][0]["agents"][0].update(agentWait={}),
            "wait-not-clear",
        ),
    ],
)
def test_real_observation_refusal_boundaries(mutation, reason):
    meter, status = readings()
    mutation(meter, status)
    assert verify(meter, status) == reason


@pytest.mark.parametrize("tool", ["claude", "codex"])
def test_native_metadata_counts_only_this_main_session(tmp_path, tool):
    identity = dict(tool=tool, session_id=SESSION, workspace=WORKSPACE)
    if tool == "codex":
        records = [
            {"type": "session_meta", "payload": {"id": SESSION, "cwd": WORKSPACE}},
            *[{"type": "compacted", "payload": {}} for _ in range(3)],
        ]
    else:
        records = [
            {
                "sessionId": SESSION,
                "cwd": WORKSPACE,
                "type": "system",
                "subtype": "compact_boundary",
            }
            for _ in range(3)
        ]
        records.append({"isSidechain": True, "type": "system", "subtype": "compact_boundary"})
    path = tmp_path / "session.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    assert context.compactions(path, identity) == 3
    path.write_text(path.read_text() + "{unfinished")
    with pytest.raises(ValueError, match="unknown native record"):
        context.compactions(path, identity)


def test_native_identity_and_symlink_cannot_select_another_log(tmp_path):
    path = tmp_path / "session.jsonl"
    path.write_text(
        json.dumps({"type": "session_meta", "payload": {"id": SESSION, "cwd": "/other"}})
    )
    identity = dict(tool="codex", session_id=SESSION, workspace=WORKSPACE)
    with pytest.raises(ValueError, match="native identity mismatch"):
        context.compactions(path, identity)
    link = tmp_path / "link.jsonl"
    link.symlink_to(path)
    with pytest.raises(OSError):
        context.compactions(link, identity)


@pytest.mark.parametrize("tool", ["claude", "codex"])
def test_large_native_logs_keep_large_compaction_records(tmp_path, tool):
    """Real sessions exceed 64 MiB before recovery, including multi-MiB records."""
    identity = dict(tool=tool, session_id=SESSION, workspace=WORKSPACE)
    if tool == "codex":
        header = {"type": "session_meta", "payload": {"id": SESSION, "cwd": WORKSPACE}}
        compact = {"type": "compacted", "payload": {}}
    else:
        header = dict(sessionId=SESSION, cwd=WORKSPACE, type="user")
        compact = dict(sessionId=SESSION, cwd=WORKSPACE, type="system", subtype="compact_boundary")
    padding = "x" * (5 * 1024 * 1024)
    output = json.dumps({"type": "tool-output", "content": padding}) + "\n"
    path = tmp_path / "large.jsonl"
    with path.open("w") as stream:
        stream.write(json.dumps(header) + "\n")
        for _ in range(14):
            stream.write(output)
        stream.write(json.dumps({**compact, "content": padding}) + "\n")
        for _ in range(2):
            stream.write(json.dumps(compact) + "\n")
    assert path.stat().st_size > 64 * 1024 * 1024
    assert context.compactions(path, identity) == 3


def test_native_read_budget_and_record_limit_refuse_with_a_safe_cause(tmp_path, monkeypatch):
    path = tmp_path / "session.jsonl"
    identity = dict(tool="codex", session_id=SESSION, workspace=WORKSPACE)
    path.write_text(
        json.dumps({"type": "session_meta", "payload": {"id": SESSION, "cwd": WORKSPACE}})
    )
    clock = iter((0, context.TIMEOUT + 1))
    with monkeypatch.context() as patch:
        patch.setattr(context.time, "monotonic", lambda: next(clock))
        with pytest.raises(ValueError, match="native log read timed out"):
            context.compactions(path, identity)
    path.write_text(json.dumps({"type": "compacted", "payload": {"message": "x" * 1024}}))
    monkeypatch.setattr(context, "MAX_LINE_BYTES", 256)
    with pytest.raises(ValueError, match="native record exceeds size limit"):
        context.compactions(path, identity)


def test_context_failure_reports_only_static_causes(tmp_path, monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise context.ObservationError("native log read timed out")

    monkeypatch.setattr(context, "inspect", fail)
    assert context.main(["inspect", "--workspace", str(tmp_path)]) == 1
    assert json.loads(capsys.readouterr().out) == {
        "action": "unknown",
        "reason": "native log read timed out",
    }

    def external_failure(*args, **kwargs):
        raise ValueError("private external data must not appear")

    monkeypatch.setattr(context, "inspect", external_failure)
    assert context.main(["inspect", "--workspace", str(tmp_path)]) == 1
    assert json.loads(capsys.readouterr().out) == {
        "action": "unknown",
        "reason": "context observation unavailable",
    }
