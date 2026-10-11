"""Direct read selectors keep the existing fixed operation boundary."""

import json

import pytest

from slopmeister.session.service_actions import arguments


def test_direct_read_selector_reaches_the_fixed_parser(monkeypatch):
    """Bug: a direct selected read silently uses no selector."""
    monkeypatch.delenv("SLOPMEISTER_SERVICE_ACTION_INPUT", raising=False)

    selected = arguments.operation(
        {"action": "jira-read", "origin": "https://jira.invalid"},
        ["--find", "--text", "alpha beta"],
    )

    assert selected["mode"] == "find" and selected["text"] == "alpha beta"


def test_direct_read_selector_does_not_evaluate_shell_text(monkeypatch, tmp_path):
    """Bug: a reviewed selector executes shell substitution or Task templates."""
    marker = tmp_path / "should-not-exist"
    literal = "$(touch " + str(marker) + ")"
    monkeypatch.delenv("SLOPMEISTER_SERVICE_ACTION_INPUT", raising=False)
    monkeypatch.setenv("RV340_SECRET", "s3cr3t-demo")

    selected = arguments.operation(
        {"action": "jira-read", "origin": "https://jira.invalid"},
        ["--find", "--text", literal],
    )
    templated = arguments.operation(
        {"action": "jira-read", "origin": "https://jira.invalid"},
        ["--find", "--text", '{{env "RV340_SECRET"}}'],
    )

    assert selected["text"] == literal and not marker.exists()
    assert templated["text"] == '{{env "RV340_SECRET"}}'


def test_direct_read_refuses_competing_input_channels(monkeypatch):
    """Bug: an ambient JSON selector silently replaces reviewed argv."""
    monkeypatch.setenv("SLOPMEISTER_SERVICE_ACTION_INPUT", json.dumps(["--issue", "TEST-8"]))

    with pytest.raises(ValueError, match="ARGUMENTS_NOT_SUPPORTED"):
        arguments.operation(
            {"action": "jira-read", "origin": "https://jira.invalid"},
            ["--issue", "TEST-7"],
        )


def test_direct_read_refuses_control_characters(monkeypatch):
    """Bug: a direct selector accepts a control character in provider input."""
    monkeypatch.delenv("SLOPMEISTER_SERVICE_ACTION_INPUT", raising=False)

    with pytest.raises(ValueError, match="ARGUMENTS_NOT_SUPPORTED"):
        arguments._arguments("jira-read", ["--find", "--text", "line\nline"])


def test_write_sandbox_keeps_structured_multiline_input(monkeypatch):
    """Bug: read-only direct parsing corrupts the existing disabled-write sandbox input."""
    body = "line one\nline two"
    monkeypatch.setenv("SLOPMEISTER_SERVICE_ACTION_INPUT", json.dumps(["--body", body]))

    assert arguments._arguments("jira-write") == ["--body", body]


@pytest.mark.parametrize("action", ["jira-write", "confluence-write"])
def test_direct_write_preserves_existing_multiline_payload_limit(monkeypatch, action):
    """Bug: delivery either refuses writes or shrinks their existing 32768-character bodies."""
    monkeypatch.delenv("SLOPMEISTER_SERVICE_ACTION_INPUT", raising=False)
    body = "line\n\t" + "x" * (32768 - 6)
    args = ["--body", body]
    assert arguments._arguments(action, args) == args
    with pytest.raises(ValueError, match="ARGUMENTS_NOT_SUPPORTED"):
        arguments._arguments(action, ["--body", body + "x"])


@pytest.mark.parametrize("action", ["jira-write", "confluence-write"])
def test_direct_write_refuses_an_ambient_replacement_payload(monkeypatch, action):
    """Bug: an environment payload replaces the exact write arguments the operator approved."""
    monkeypatch.setenv("SLOPMEISTER_SERVICE_ACTION_INPUT", json.dumps(["--permissions", "OTHER"]))

    with pytest.raises(ValueError, match="ARGUMENTS_NOT_SUPPORTED"):
        arguments._arguments(action, ["--permissions", "TEST"])
