"""A tab Chrome takes away is named, is never blamed on a field and reaches the close report."""

import subprocess

import pytest

from slopmeister.session import browser_runtime as runtime
from tests.support.browser import commands

SAVED = "playwright/.playwright-cli"


def snapshot(root):
    saved = root / SAVED
    saved.parent.mkdir(mode=0o700, exist_ok=True)
    saved.mkdir(mode=0o700)
    (saved / "page.yml").write_text("revealed password")
    return saved


def test_a_connection_lost_after_an_action_still_withholds_its_snapshot(root, chrome):
    lost = ValueError("BROWSER_CONNECTION_LOST: close the state")
    chrome.answers["filled"] = [{"result": "EMPTY", "owned": [1]}, lost]
    saved = snapshot(root)
    with pytest.raises(ValueError, match="CONNECTION_LOST"):
        runtime.page(root, ["click", "e1"])
    assert commands(chrome.calls) == ["tab-list", "click", "tab-list"] and not saved.exists()


def test_a_failed_state_write_after_an_action_still_withholds_its_snapshot(
    root, chrome, monkeypatch
):
    writes = iter([None])

    def save(*_):
        if next(writes, "full") == "full":
            raise OSError(28, "No space left on device")

    monkeypatch.setattr(runtime, "save", save)
    chrome.answers["filled"] = [
        {"result": "EMPTY", "owned": [1], "address": "https://a.example/"},
        {"result": "EMPTY", "owned": [1], "address": "https://a.example/next"},
    ]
    saved = snapshot(root)
    with pytest.raises(OSError, match="No space"):
        runtime.page(root, ["click", "e1"])
    assert commands(chrome.calls) == ["tab-list", "click", "tab-list"] and not saved.exists()


def test_a_lost_connection_is_never_reported_as_a_filled_field(root, chrome):
    chrome.answers["filled"] = ValueError("BROWSER_CONNECTION_LOST: close the state")
    with pytest.raises(ValueError, match="CONNECTION_LOST") as refusal:
        runtime.page(root, ["goto", "https://example.com/"])
    assert "field" not in str(refusal.value) and commands(chrome.calls) == ["tab-list"]


def test_a_page_that_does_not_answer_is_refused_without_blaming_a_field(root, chrome):
    chrome.answers["filled"] = ValueError("BROWSER_OPERATION_FAILED: do not retry submission")
    with pytest.raises(ValueError, match="PAGE_REFUSED: the page does not answer"):
        runtime.page(root, ["snapshot"])
    assert commands(chrome.calls) == ["tab-list"]


def test_a_page_tool_with_no_current_tab_runs_nothing(root, chrome):
    chrome.tabs = "- 1: [Page](https://a.example/)\n"
    with pytest.raises(ValueError, match="PAGE_REFUSED: the page does not answer"):
        runtime.page(root, ["snapshot"])
    assert commands(chrome.calls) == ["tab-list"] and chrome.helper == []


def test_a_lost_tab_is_named_and_stops_page_commands(root, chrome):
    chrome.answers["filled"] = {"result": "PAGE_LOST"}
    with pytest.raises(ValueError, match="BROWSER_TAB_LOST") as refusal:
        runtime.page(root, ["snapshot"])
    assert "field" not in str(refusal.value) and commands(chrome.calls) == ["tab-list"]


def test_the_page_tool_render_error_on_a_lost_tab_becomes_the_named_result(root, chrome):
    chrome.replies["goto"] = (
        1,
        "### Error\nTypeError: Cannot read properties of undefined (reading 'url')\n",
    )
    chrome.answers["filled"] = [{"result": "EMPTY", "owned": [1]}, {"result": "PAGE_LOST"}]
    with pytest.raises(ValueError, match="BROWSER_TAB_LOST"):
        runtime.page(root, ["goto", "https://example.com/"])


def test_a_failed_command_shows_its_own_error_without_other_sessions_tabs(
    root, chrome, monkeypatch
):
    real = chrome.run

    def failing(argv, **options):
        if "click" not in argv:
            return real(argv, **options)
        other = "### Open tabs\n- 0: [Other plot](https://other.example/private)\n"
        return subprocess.CompletedProcess(argv, 1, "### Error\n", f"Error: failed\n{other}")

    monkeypatch.setattr(runtime.subprocess, "run", failing)
    done = runtime.page(root, ["click", "e1"])
    assert done.returncode == 1 and "Error: failed" in done.stdout
    assert "other.example" not in done.stdout
