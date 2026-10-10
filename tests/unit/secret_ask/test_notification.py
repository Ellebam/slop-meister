"""The approval surface must show the agent's exact request and retain its identity."""

import pytest

from slopmeister.secret_ask.home_assistant import notification

ROW = {
    "id": "abc",
    "approve": "private-approve",
    "deny": "private-deny",
    "env": {"DEMO": "op://Example/Demo/password", "KEY": "op://Example/SSH/key?ssh-format=openssh"},
    "argv": ["/usr/bin/true", "--flag", "two words"],
    "cwd": "/home/agent/repo",
    "reason": "Operator proof",
    "host": "test-host",
    "session": "test-session",
}


def test_body_tap_and_buttons_bind_to_the_same_request():
    """Bug: notification body taps lose the decision or open a newer request."""
    body = notification(ROW)
    assert body["data"]["url"] == "/secret-ask?request=abc"
    assert body["data"]["tag"] == "secret-ask-abc"
    assert [a["action"] for a in body["data"]["actions"]] == ["private-approve", "private-deny"]
    assert body["title"] == "Secret approval: test-session"
    for text in (
        "/usr/bin/true --flag 'two words'",
        "DEMO=op://Example/Demo/password",
        "KEY=op://Example/SSH/key?ssh-format=openssh",
        "Operator proof",
        "test-host",
        "test-session",
        "/home/agent/repo",
    ):
        assert text in body["message"]


def test_missing_reason_is_named_not_blank():
    """Bug: an empty reason line reads as a truncated notification."""
    assert "no reason given" in notification({**ROW, "reason": ""})["message"]


def test_request_too_large_for_push_is_refused_instead_of_truncated():
    """Bug: the operator approves a command whose omitted tail changes its effect."""
    with pytest.raises(ValueError):
        notification({**ROW, "argv": ["x" * 4000]})
