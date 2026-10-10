"""Resolution runs as the service account with its own environment and names only variables."""

from pathlib import Path

import pytest

from slopmeister.secret_ask.resolve import resolve

pytestmark = pytest.mark.xdist_group("secret-ask-processes")


def fake_op(tmp_path: Path, body: str) -> Path:
    op = tmp_path / "op"
    op.write_text("#!/bin/sh\n" + body)
    op.chmod(0o700)
    return op


def test_values_come_from_the_service_account_without_the_agent_environment(tmp_path, monkeypatch):
    """Bug: the broker token or the daemon's own environment leaks into the op call."""
    monkeypatch.setenv("AGENT_ONLY", "present")
    op = fake_op(
        tmp_path,
        'test "$1" = read && test "$2" = --no-newline || exit 9\n'
        'test "$OP_SERVICE_ACCOUNT_TOKEN" = synthetic-token || exit 8\n'
        'test -z "$AGENT_ONLY" || exit 7\n'
        'test "$HOME" = /var/empty || exit 6\n'
        'printf "value-of-%s" "$3"\n',
    )
    values, failed = resolve(
        {"A": "op://V/I/a", "B": "op://V/I/b?ssh-format=openssh"}, (op, "synthetic-token", tmp_path)
    )
    assert failed == ""
    assert values == {"A": "value-of-op://V/I/a", "B": "value-of-op://V/I/b?ssh-format=openssh"}


def test_one_failing_reference_fails_the_request_with_its_name_only(tmp_path):
    """Bug: a partial set of values is delivered, or a failure message carries a value."""
    op = fake_op(
        tmp_path, 'case "$3" in *bad*) echo "secret-looking-output" >&2; exit 1;; esac\nprintf ok\n'
    )
    values, failed = resolve({"GOOD": "op://V/I/good", "BAD": "op://V/I/bad"}, (op, "t", tmp_path))
    assert (values, failed) == ({}, "BAD")


def test_missing_op_binary_fails_without_raising(tmp_path):
    """Bug: an unavailable CLI crashes the resolver thread and leaves the request approved."""
    assert resolve({"A": "op://V/I/a"}, (tmp_path / "absent", "t", tmp_path)) == ({}, "A")
