"""Closing a predecessor signals only what its workspace owns, or stops with its closure state."""

import pytest

from slopmeister.launch import closure
from slopmeister.launch.model import ROOT, Launch, Stop
from tests.unit.launch.closure_helpers import box_launch, make_box

CLAUDE, CODEX = ("claude", ".", False), ("codex", ".", False)
CLOSED, ABSENT = "plot-session: predecessor closed", "no predecessor, recovering existing workspace"
TERM, POLLED = ["term", "close"], 20 * ["sleep"]
ROWS = {
    "absent": (([], False, ""), ABSENT, []),
    "named": (([("claude", ".", True)], True, ""), CLOSED, TERM),
    "manual": (([CLAUDE], True, ""), CLOSED, TERM),
    "sibling": (([("claude", "../wt-other", False)], True, ""), ABSENT, []),
    "subdir": (([("claude", "sub", False)], True, ""), CLOSED, TERM),
    "ambiguous": (([CLAUDE, CLAUDE], True, ""), "(PIDs 4000, 4001)", []),
    "named-beside-manual": (
        ([("claude", ".", True), CLAUDE], True, ""),
        "(PIDs 4000, 4001)",
        [],
    ),
    "inspect-error": (([CLAUDE], True, "ps"), "cannot complete ps inspection", []),
    "cwd-failure": (([CLAUDE], True, "lsof"), "cannot determine identity or cwd", []),
    "orca-down": (([CLAUDE], True, "orca-down"), "Orca is unreachable", []),
    "no-handle-orca-down": (([CLAUDE], False, "orca-down"), CLOSED, ["term"]),
    "stale-pid": (([CLAUDE], True, "identity"), "PID identity changed", []),
    "timeout": (
        ([CLAUDE], True, "ignore-term"),
        "captured PID 4000 did not stop",
        ["term", *POLLED],
    ),
    "codex-standalone": (([CODEX], True, ""), CLOSED, TERM),
    "terminal-error": (([CLAUDE], True, "close"), "old-terminal did not close", TERM),
    "already-closed": (([CLAUDE], False, ""), CLOSED, ["term"]),
}


@pytest.mark.parametrize("case", ROWS.values(), ids=ROWS.keys())
def test_closure_decisions(tmp_path, monkeypatch, capsys, case):
    """Bug: closure signals a stranger, trusts a failed inspection, or hides a partial closure."""
    row, outcome, events = case
    box = make_box(tmp_path, monkeypatch, row)
    try:
        closure.close(box_launch(box))
        said = capsys.readouterr().out
    except Stop as stop:
        said = stop.text
        attempted = "was attempted and may be incomplete" if events else "was not attempted"
        assert f"no replacement started; predecessor closure {attempted}" in said
        assert "retry the same name with --redispatch" in said
    assert outcome in said
    assert box.events == events
    assert "other" in box.terminals


def test_descendants_are_recorded_then_stopped_deepest_first(tmp_path, monkeypatch):
    """Bug: closing the client left its child or grandchild alive after reparenting."""
    box = make_box(tmp_path, monkeypatch, ([CLAUDE], False, ""))
    box.alive[4001] = ("python", str(box.wt), False)
    box.alive[4002] = ("sleep", str(box.wt), False)
    box.parents.update({4001: 4000, 4002: 4001})
    closure.close(box_launch(box))
    assert box.signals == [4002, 4001, 4000]


def test_unsignallable_descendant_refuses_before_any_signal(tmp_path, monkeypatch):
    """Bug: a foreign-uid descendant crashed closure after siblings had been killed."""
    box = make_box(tmp_path, monkeypatch, ([CLAUDE], False, ""))
    box.alive[4001] = ("python", str(box.wt), False)
    box.parents[4001] = 4000
    box.unsignallable.add(4001)
    with pytest.raises(Stop, match="PID 4001 cannot be signalled"):
        closure.close(box_launch(box))
    assert box.signals == [] and set(box.alive) == {4000, 4001}


def test_recorded_child_is_stopped_after_parent_exits_and_reparents_it(tmp_path, monkeypatch):
    """Bug: a child escaped when its parent vanished after the descendant snapshot."""
    box = make_box(tmp_path, monkeypatch, ([CLAUDE], False, "reparent"))
    box.alive[4001] = ("python", str(box.wt), False)
    box.parents[4001] = 4000
    closure.close(box_launch(box))
    assert box.signals == [4001] and box.alive == {}


def test_permission_loss_after_preflight_is_a_controlled_partial_closure(tmp_path, monkeypatch):
    """Bug: signal permission loss escaped as a traceback after closure had begun."""
    box = make_box(tmp_path, monkeypatch, ([CLAUDE], False, "late-permission"))
    with pytest.raises(Stop, match="became unsignallable.*attempted and may be incomplete"):
        closure.close(box_launch(box))
    assert box.signals == [] and 4000 in box.alive


def test_terminate_waits_for_descendant_in_uninterruptible_wait(tmp_path, monkeypatch):
    """Bug: cleanup reported success while a SIGTERM-ignoring child in state U remained alive."""
    box = make_box(tmp_path, monkeypatch, ([CLAUDE], False, "uninterruptible-after-term"))
    launch = box_launch(box)
    owned = closure.Owned(4000, 0, "Mon Sep  7 10:00:00 2026 agent")
    with pytest.raises(Stop, match="PID 4000 did not stop"):
        closure._terminate(closure.Closure(launch), owned)
    assert box.signals == [4000] and 4000 in box.alive


def test_descendant_exits_during_identity_check(tmp_path, monkeypatch):
    """Bug: a child exiting during closure needlessly blocked redispatch after it was gone."""
    box = make_box(tmp_path, monkeypatch, ([CLAUDE], False, ""))
    observed = iter(["changed", None])
    monkeypatch.setattr(closure, "_signature", lambda _closure, _pid: next(observed))
    closure._terminate(
        closure.Closure(box_launch(box)),
        closure.Owned(4001, 1, "Mon Sep  7 10:00:00 2026 child"),
    )
    assert box.signals == []


def test_changed_descendant_still_present_refuses_signal(tmp_path, monkeypatch):
    """Bug: an identity retry could signal a PID now owned by another process."""
    box = make_box(tmp_path, monkeypatch, ([CLAUDE], False, ""))
    monkeypatch.setattr(closure, "_signature", lambda _closure, _pid: "changed")
    with pytest.raises(Stop, match="identity changed before termination"):
        closure._terminate(
            closure.Closure(box_launch(box)),
            closure.Owned(4001, 1, "Mon Sep  7 10:00:00 2026 child"),
        )
    assert box.signals == []


def test_handle_in_another_workspace_is_left_alone(tmp_path, monkeypatch):
    """Bug: a recorded handle now serving another workspace was closed with the predecessor."""
    box = make_box(tmp_path, monkeypatch, ([CLAUDE], True, ""))
    box.terminals["old-terminal"] = str(tmp_path / "elsewhere")
    closure.close(box_launch(box))
    assert box.events == ["term"] and "old-terminal" in box.terminals
    assert not (tmp_path / "state/example-client-old.orca").exists()


def test_unreachable_orca_keeps_the_handle_and_signals_nothing(tmp_path, monkeypatch):
    """Bug: the replacement overwrote the only record of a tab Orca could not check."""
    box = make_box(tmp_path, monkeypatch, ([CLAUDE], True, "orca-down"))
    with pytest.raises(Stop, match="predecessor closure was not attempted"):
        closure.close(box_launch(box))
    assert (
        box.signals == []
        and (tmp_path / "state/example-client-old.orca").read_text() == "old-terminal\n"
    )


def test_directory_session_handle_belongs_to_the_slopmeister_checkout(tmp_path, monkeypatch):
    """Bug: a directory session's tab, opened in the Slopmeister checkout, was never closed."""
    box = make_box(tmp_path, monkeypatch, ([CLAUDE], True, ""))
    box.terminals["old-terminal"] = str(ROOT)
    closure.close(Launch("example-client", "example-client-old", "", claude_wt=box.wt, wt=box.wt))
    assert box.events == ["term", "close"] and "old-terminal" not in box.terminals


def test_tab_without_a_live_predecessor_is_left_open(tmp_path, monkeypatch):
    """Bug: a crashed session's tab, reused as a shell, was closed by the next redispatch."""
    box = make_box(tmp_path, monkeypatch, ([], True, ""))
    closure.close(box_launch(box))
    assert box.events == [] and "old-terminal" in box.terminals
    assert not (tmp_path / "state/example-client-old.orca").exists()
