"""A tab Chrome takes away is named, is never blamed on a field and reaches the close report."""

import json
from pathlib import Path
import subprocess

import pytest

from slopmeister.session import browser_runtime as runtime
from tests.support.browser import CONNECT, commands


def test_a_connection_lost_after_an_action_still_withholds_its_snapshot(root, tool, monkeypatch):
    calls, _ = tool
    replies = iter([{"result": "EMPTY"}, ValueError("BROWSER_CONNECTION_LOST: close the state")])

    def reply(*_):
        answer = next(replies)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(runtime, "request", reply)
    saved = root / "playwright/.playwright-cli"
    saved.parent.mkdir(mode=0o700, exist_ok=True)
    saved.mkdir(mode=0o700)
    (saved / "page.yml").write_text("revealed password")
    with pytest.raises(ValueError, match="CONNECTION_LOST"):
        runtime.page(root, ["click", "e1"])
    assert commands(calls) == ["click"] and not saved.exists()


def test_a_failed_state_write_after_an_action_still_withholds_its_snapshot(root, tool, monkeypatch):
    calls, _ = tool
    replies = iter([{"result": "EMPTY"}, {"result": "PAGE_LOST"}])
    monkeypatch.setattr(runtime, "request", lambda *_: next(replies))
    saves = iter([None])

    def save(*_):
        if next(saves, "full") == "full":
            raise OSError(28, "No space left on device")

    monkeypatch.setattr(runtime, "save", save)
    saved = root / "playwright/.playwright-cli"
    saved.parent.mkdir(mode=0o700, exist_ok=True)
    saved.mkdir(mode=0o700)
    (saved / "page.yml").write_text("revealed password")
    with pytest.raises(OSError, match="No space"):
        runtime.page(root, ["click", "e1"])
    assert commands(calls) == ["click"] and not saved.exists()


def test_a_lost_connection_is_never_reported_as_a_filled_field(root, tool, monkeypatch):
    calls, _ = tool

    def lost(*_):
        raise ValueError("BROWSER_CONNECTION_LOST: close the state and start again")

    monkeypatch.setattr(runtime, "request", lost)
    with pytest.raises(ValueError, match="CONNECTION_LOST") as refusal:
        runtime.page(root, ["goto", "https://example.com/"])
    assert "field" not in str(refusal.value) and calls == []


def test_a_page_that_does_not_answer_is_refused_without_blaming_a_field(root, tool, monkeypatch):
    calls, _ = tool

    def unanswered(*_):
        raise ValueError("BROWSER_OPERATION_FAILED: do not retry submission")

    monkeypatch.setattr(runtime, "request", unanswered)
    with pytest.raises(ValueError, match="PAGE_REFUSED: the page does not answer"):
        runtime.page(root, ["snapshot"])
    assert calls == []


def test_a_lost_tab_is_named_and_stops_page_commands(root, tool, monkeypatch):
    calls, _ = tool
    monkeypatch.setattr(runtime, "request", lambda *_: {"result": "PAGE_LOST"})
    with pytest.raises(ValueError, match="BROWSER_TAB_LOST") as refusal:
        runtime.page(root, ["snapshot"])
    assert "field" not in str(refusal.value) and calls == []
    assert runtime.metadata(root)["tab_unproven"] is True


def test_the_page_tool_render_error_on_a_lost_tab_becomes_the_named_result(root, tool, monkeypatch):
    _, replies = tool
    replies["goto"] = (
        1,
        "### Error\nTypeError: Cannot read properties of undefined (reading 'url')\n",
    )
    answers = iter([{"result": "EMPTY", "pages": 1}, {"result": "PAGE_LOST"}])
    monkeypatch.setattr(runtime, "request", lambda *_: next(answers))
    with pytest.raises(ValueError, match="BROWSER_TAB_LOST"):
        runtime.page(root, ["goto", "https://example.com/"])


def test_a_failed_command_shows_its_own_error_without_the_connect_address(root, tool, monkeypatch):
    def failing(argv, **options):
        return subprocess.CompletedProcess(argv, 1, "### Error\n", f"Error: failed at {CONNECT}\n")

    monkeypatch.setattr(runtime.subprocess, "run", failing)
    done = runtime.page(root, ["click", "e1"])
    assert done.returncode == 1 and "Error: failed at" in done.stdout
    assert "dummy-private-token" not in done.stdout


def test_a_tab_that_vanishes_beside_a_surviving_popup_is_reported_at_close(root, tool, monkeypatch):
    _, replies = tool
    replies["list"] = (0, f"- {runtime.SESSION}:\n")
    replies["tab-list"] = (0, "- 0: [Popup](https://b.example/)\n")
    answers = iter(
        [
            {"result": "EMPTY", "pages": 2, "address": "https://a.example/"},
            {"result": "EMPTY", "pages": 1, "address": "https://b.example/"},
            {"result": "EMPTY", "pages": 1, "address": "https://b.example/"},
        ]
    )
    monkeypatch.setattr(runtime, "request", lambda *_: next(answers))
    runtime.page(root, ["snapshot"])
    assert runtime.close(root)["tabs_left"].startswith("https://a.example/")


def test_closing_a_popup_on_purpose_leaves_nothing_to_report(root, tool, monkeypatch):
    _, replies = tool
    replies["list"] = (0, f"- {runtime.SESSION}:\n")
    replies["tab-list"] = (0, "- 0: [Page](https://a.example/)\n")
    answers = iter(
        [
            {"result": "EMPTY", "pages": 2, "address": "https://a.example/"},
            {"result": "EMPTY", "pages": 1, "address": "https://a.example/"},
        ]
    )
    monkeypatch.setattr(runtime, "request", lambda *_: next(answers))
    runtime.page(root, ["tab-close", "1"])
    assert runtime.close(root) == {"result": "BROWSER_CLOSED"}


def test_every_page_tool_run_blocks_the_frames_that_end_the_debugger_session(root, tool):
    calls, _ = tool
    runtime.page(root, ["snapshot"])
    work = root / "playwright"
    config = json.loads((work / ".playwright/cli.config.json").read_text())
    block = (work / "frame-block.js").read_text()
    assert config["browser"]["initScript"] == [str(work / "frame-block.js")]
    assert config["console"] == {"level": "none"}, "page console capture must stay off"
    assert "disabledFeatures" in block and "com-1password-" in block


def test_start_reports_where_a_redirect_landed(started, monkeypatch):
    address = {"result": "EMPTY", "pages": 1, "address": "https://id.example/sign-in"}
    monkeypatch.setattr(runtime, "request", lambda *_: address)
    assert runtime.start("https://example.com/login")["url"] == "https://id.example/sign-in"


def test_start_does_not_report_ready_on_a_blank_tab(started, monkeypatch, tmp_path):
    calls, _ = started
    monkeypatch.setattr(runtime, "request", lambda *_: {"result": "PAGE_LOST"})
    with pytest.raises(ValueError, match="BROWSER_PAGE_NOT_REACHED") as refusal:
        runtime.start("https://example.com/login")
    assert commands(calls) == ["attach", "tab-new", "tab-close", "resize"]
    state_path = str(refusal.value).split("retain state ")[1].split()[0]
    saved = runtime.metadata(Path(state_path))
    assert saved["tab_unproven"] is True and saved["address"] == "https://example.com/login"


def test_a_failed_start_names_the_page_tool_error_and_keeps_the_token_out(started):
    calls, replies = started
    replies["tab-new"] = (1, f"### Error\nError: Target page closed at {CONNECT}\n")
    with pytest.raises(ValueError, match="BROWSER_START_FAILED: Error: Target page") as refusal:
        runtime.start("https://example.com/login")
    assert "dummy-private-token" not in str(refusal.value)
    assert commands(calls) == ["attach", "tab-new"]
    state_path = str(refusal.value).split("retain state ")[1].split()[0]
    assert runtime.metadata(Path(state_path))["tab_unproven"] is True


def test_close_cannot_prove_a_tab_gone_once_the_session_vanished(root, tool):
    _, replies = tool
    replies["list"] = (0, "(no browsers)\n")
    runtime.save(root, {**runtime.metadata(root), "address": "https://a.example/login"})
    assert runtime.close(root)["tabs_left"].startswith("https://a.example/login")
    assert not root.exists()


def test_close_reports_a_tab_it_knows_it_lost(root, tool):
    _, replies = tool
    replies["list"] = (0, f"- {runtime.SESSION}:\n")
    replies["tab-list"] = (0, "- 0: [](about:blank)\n")
    runtime.save(root, {**runtime.metadata(root), "tab_unproven": True})
    done = runtime.close(root)
    assert done["result"] == "BROWSER_CLOSED" and "may still be open" in done["tabs_left"]


def test_a_lost_connection_is_named(root):
    with pytest.raises(ValueError, match="CONNECTION_LOST"):
        runtime.socket(root)


def test_close_counts_tabs_itself_because_a_tab_can_vanish_after_the_last_guard(root, tool):
    _, replies = tool
    replies["list"] = (0, f"- {runtime.SESSION}:\n")
    replies["tab-list"] = (
        0,
        "- 0: (current) [](about:blank)\n- 1: [Popup](https://b.example/)\n",
    )
    runtime.save(root, {**runtime.metadata(root), "pages": 2, "address": "https://a.example/login"})
    assert runtime.close(root)["tabs_left"].startswith("https://a.example/login")
