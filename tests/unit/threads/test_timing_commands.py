"""Spine timing recognizes a full gate run by how a shell invokes it."""

from slopmeister.threads.timing.events import command_kind


def test_full_gate_with_options_is_still_a_full_gate():
    """Escaping bug: a gate run with --jobs or --report counted as focused, hiding repeats."""
    assert command_kind("task check -- --jobs 2 --report /tmp/gate.json") == "gate-full"
    assert (
        command_kind('cd w && S=x && "$W/bin/slopmeister" check --jobs 1 2>&1 | tail')
        == "gate-full"
    )
    assert command_kind("echo start\ntimeout 540 task check < /dev/null") == "gate-full"
    assert command_kind("for i in 1 2; do task check 2>&1 | cat > log; done") == "gate-full"
    assert command_kind('{ /usr/bin/time -p task check > "$S/gate.log" 2>&1; }') == "gate-full"
    assert command_kind("task check -- --kind tests") == "gate-focused"
    assert command_kind("bin/slopmeister check --list") == "gate-focused"
    assert command_kind("task check:lint") == "other"
