"""Page commands cannot export authentication or leave listeners active during credential input."""

import argparse
from pathlib import Path
import subprocess

import pytest

from slopmeister.session import browser_login as browser
from slopmeister.session import browser_page as page
from slopmeister.session import browser_runtime as runtime
from slopmeister.session import browser_state as state


@pytest.fixture
def root(tmp_path):
    state.save(
        tmp_path,
        {
            "browser": "chrome",
            "worktree": str(tmp_path),
            "endpoint": "ws://127.0.0.1:1234/devtools/browser/owned",
        },
    )
    return tmp_path


@pytest.mark.parametrize(
    "command",
    [
        "run-code",
        "eval",
        "upload",
        "drop",
        "cookie-list",
        "state-save",
        "network",
        "console",
        "unknown",
    ],
)
def test_non_page_capabilities_never_reach_the_tool(root, monkeypatch, command):
    monkeypatch.setattr(page, "tool", lambda *_: pytest.fail("refused command reached the tool"))
    with pytest.raises(ValueError, match="COMMAND_REFUSED"):
        page.page(root, [command])


@pytest.mark.parametrize(
    "arguments",
    [
        ["snapshot", "--filename=/tmp/out"],
        ["screenshot", "--filename", "/tmp/out"],
        ["snapshot", "--session=other"],
        ["snapshot", "-s", "other"],
        ["snapshot", "--", "--filename=/tmp/out"],
        ["snapshot", "--json"],
        ["click", "e1", "--depth=2"],
        ["snapshot", "--depth", "--filename=/tmp/out"],
    ],
)
def test_output_session_and_misplaced_options_are_refused(root, arguments):
    with pytest.raises(ValueError, match="OPTION_REFUSED"):
        page.page(root, arguments)


@pytest.mark.parametrize(
    "arguments",
    [
        ["mousewheel", "0", "-30"],
        ["snapshot", "--depth=3"],
        ["find", "--regex", "a.*b"],
        ["click", "e1", "--modifiers", "Control"],
    ],
)
def test_allowed_page_arguments_remain_available(arguments):
    page.validate(arguments)


@pytest.mark.parametrize("used", [False, True])
def test_every_page_is_checked_even_before_first_credential_step(root, monkeypatch, used):
    if used:
        state.credential_state(root, create=True)
    monkeypatch.setattr(
        page.chrome, "connection", lambda *_: (Path("/node"), state.metadata(root)["endpoint"])
    )
    checked = []

    def inspect(_root, _engine, payload):
        if payload["action"] == "pages":
            return {"pages": ["first", "second"], "frames": False}
        checked.append(payload["endpoint"].rsplit("/", 1)[-1])
        return {"result": "FILLED" if checked[-1] == "second" else "EMPTY"}

    monkeypatch.setattr(state, "request", inspect)
    monkeypatch.setattr(
        page, "tool", lambda *_: pytest.fail("credential-bearing page was captured")
    )
    with pytest.raises(ValueError, match="populated credential fields"):
        page.page(root, ["snapshot"])
    assert checked == ["first", "second"]


@pytest.mark.parametrize("pending", [False, True])
def test_unconfirmed_detachment_delivers_no_credential(root, monkeypatch, pending):
    data = state.metadata(root)
    data["page_pending"] = pending
    data["page_owner"] = {"pid": 321, "born": "recorded"}
    state.save(root, data)
    monkeypatch.setenv("BROWSER_LOGIN_PASSWORD", "synthetic-secret")
    monkeypatch.setattr(page, "process", lambda *_: "recorded")
    monkeypatch.setattr(
        page, "tool", lambda *_: subprocess.CompletedProcess([], 0, '{"status":"detached"}')
    )
    ticks = iter([0, 10])
    monkeypatch.setattr(page.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(
        runtime, "request", lambda *_: pytest.fail("credential input reached the page")
    )
    args = argparse.Namespace(
        field=[["#password", "BROWSER_LOGIN_PASSWORD"]],
        url="https://example.com/",
        submit="#submit",
    )
    with pytest.raises(ValueError, match="(OWNER_UNCERTAIN|DETACH_UNCONFIRMED)"):
        browser.fill(root, args)
    assert not state.credential_state(root)
    assert "synthetic-secret" not in (root / "owner.json").read_text()


def test_verified_helper_exit_allows_input_and_keeps_only_selectors(root, monkeypatch):
    data = state.metadata(root)
    data["page_owner"] = {"pid": 321, "born": "recorded"}
    state.save(root, data)
    observations = iter(["recorded", None])
    monkeypatch.setattr(page, "process", lambda *_: next(observations))
    monkeypatch.setattr(
        page, "tool", lambda *_: subprocess.CompletedProcess([], 0, '{"status":"detached"}')
    )
    monkeypatch.setenv("BROWSER_LOGIN_PASSWORD", "synthetic-secret")
    calls = []
    monkeypatch.setattr(
        runtime,
        "request",
        lambda *args: calls.append(args) or {"result": "BROWSER_LOGIN_SUBMITTED"},
    )
    args = argparse.Namespace(
        field=[["#password", "BROWSER_LOGIN_PASSWORD"]],
        url="https://example.com/",
        submit="#submit",
    )
    assert browser.fill(root, args)["result"] == "BROWSER_LOGIN_SUBMITTED"
    assert len(calls) == 1 and state.credential_state(root)
    assert "page_owner" not in state.metadata(root)
    assert state.metadata(root)["credential_fields"] == ["#password"]
    assert "synthetic-secret" not in (root / "owner.json").read_text()


@pytest.mark.parametrize("link", ["symlink", "hardlink"])
def test_page_config_cannot_overwrite_an_unrelated_file(tmp_path, link):
    import os

    target = tmp_path / "keep"
    target.write_text("untouched")
    config = tmp_path / "config.json"
    config.symlink_to(target) if link == "symlink" else os.link(target, config)
    with pytest.raises((OSError, ValueError)):
        page._configuration(config)
    assert target.read_text() == "untouched"
