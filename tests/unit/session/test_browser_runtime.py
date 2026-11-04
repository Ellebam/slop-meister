"""Page commands stay inside their allowlist and the extension token stays out of every output."""

import json

import pytest

from slopmeister.session import browser_runtime as runtime
from tests.support.browser import CONNECT, commands


@pytest.mark.parametrize("url", ["http://example.com", "https://u:p@example.com", "file:///x"])
def test_destination_requires_https_without_embedded_credentials(url):
    with pytest.raises(ValueError, match="URL_REFUSED"):
        runtime.https_url(url)


def test_foreign_or_linked_state_is_refused(root):
    root.chmod(0o755)
    with pytest.raises(ValueError, match="STATE_REFUSED"):
        runtime.owned(str(root))
    root.chmod(0o700)
    original = root / "owner.json"
    original.rename(root / "other")
    original.symlink_to(root / "other")
    with pytest.raises(ValueError, match="STATE_REFUSED"):
        runtime.owned(str(root))


@pytest.mark.parametrize(
    ("command", "reason"),
    [
        (["cookie-list"], "COMMAND_REFUSED"),
        (["localstorage-get", "token"], "COMMAND_REFUSED"),
        (["state-save"], "COMMAND_REFUSED"),
        (["request-body", "1"], "COMMAND_REFUSED"),
        (["route", "**"], "COMMAND_REFUSED"),
        (["run-code", "1"], "COMMAND_REFUSED"),
        (["attach", "--extension=chrome"], "COMMAND_REFUSED"),
        (["detach"], "COMMAND_REFUSED"),
        (["open", "https://example.com/"], "COMMAND_REFUSED"),
        ([], "COMMAND_REFUSED"),
        (["screenshot", "--filename=/etc/passwd"], "OPTION_REFUSED"),
        (["snapshot", "--filename", "../../outside.yml"], "OPTION_REFUSED"),
        (["eval", "() => 1", "--config=/tmp/other.json"], "OPTION_REFUSED"),
        (["click", "e1", "-s=other"], "OPTION_REFUSED"),
        (["mousewheel", "0", "-500", "--filename=x"], "OPTION_REFUSED"),
        (["goto", "file:///etc/passwd"], "URL_REFUSED"),
        (["tab-new", "http://example.com/"], "URL_REFUSED"),
    ],
)
def test_page_commands_outside_the_allowlist_start_nothing(root, tool, command, reason):
    calls, _ = tool
    with pytest.raises(ValueError, match=reason):
        runtime.page(root, command)
    assert calls == []


def test_page_tool_keeps_its_files_in_the_state_and_gets_no_credentials(root, tool, monkeypatch):
    calls, _ = tool
    monkeypatch.setenv("BROWSER_LOGIN_PASSWORD", "dummy-private-value")
    monkeypatch.setenv(runtime.TOKEN, "dummy-private-value")
    runtime.page(root, ["goto", "https://example.com/"])
    argv, options = calls[0]
    assert argv == ["-s=" + runtime.SESSION, "goto", "https://example.com/"]
    assert options["cwd"] == root / "playwright"
    assert options["env"]["PWTEST_SOCKETS_DIR"] == str(root / "sockets")
    assert options["env"]["PWTEST_CLI_GLOBAL_CONFIG"] == str(root / "playwright")
    assert options["env"]["TMPDIR"] == str(root / "playwright/tmp")
    assert "dummy-private-value" not in json.dumps(options["env"])
    assert (root / "playwright").stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize("command", [["snapshot"], ["click", "e3"]])
@pytest.mark.parametrize("reply", ["FILLED", "EMPTY", "PAGE_OPERATION_FAILED"])
def test_no_page_command_runs_while_a_password_field_holds_a_value_even_before_any_fill(
    root, tool, monkeypatch, command, reply
):
    calls, _ = tool
    runtime.save(root, {**runtime.metadata(root), "credential_fields": ["#user"]})
    checks = []
    monkeypatch.setattr(
        runtime, "request", lambda _, payload: checks.append(payload) or {"result": reply}
    )
    if reply != "EMPTY":
        with pytest.raises(ValueError, match="PAGE_REFUSED"):
            runtime.page(root, command)
        assert calls == [], "the page tool saves a snapshot, so nothing may start"
    else:
        runtime.page(root, command)
        assert commands(calls) == [command[0]]
    assert checks[0] == {
        "action": "filled",
        "selectors": ["input[type=password]", 'input[autocomplete="one-time-code"]', "#user"],
    }


def test_a_password_revealed_by_an_action_withholds_its_output_and_snapshot(
    root, tool, monkeypatch
):
    calls, replies = tool
    replies["click"] = (0, "### Page\nprivate output\n")
    replies_seen = iter(["EMPTY", "FILLED"])
    monkeypatch.setattr(runtime, "request", lambda *_: {"result": next(replies_seen)})
    saved = root / "playwright/.playwright-cli"
    saved.parent.mkdir(mode=0o700, exist_ok=True)
    saved.mkdir(mode=0o700)
    (saved / "page.yml").write_text("revealed password")
    with pytest.raises(ValueError, match="PAGE_REFUSED: a credential field holds a value"):
        runtime.page(root, ["click", "e1"])
    assert commands(calls) == ["click"] and not saved.exists()


@pytest.mark.parametrize("command", ["snapshot", "tab-list", "click"])
def test_connect_address_never_reaches_page_output(root, tool, command):
    _, replies = tool
    replies[command] = (
        0,
        f"- 0: [Welcome]({CONNECT})\n- 1: (current) [Page](https://a.example/)\n",
    )
    output = runtime.page(root, [command]).stdout
    assert "dummy-private-token" not in output and "https://a.example/" in output


def test_negative_numbers_are_data_not_options(root, tool):
    calls, _ = tool
    runtime.page(root, ["mousewheel", "0", "-500"])
    assert calls[-1][0][1:] == ["mousewheel", "0", "-500"]


def test_start_connects_opens_its_own_tab_and_hides_every_token_path(started, tmp_path, capsys):
    calls, replies = started
    replies["attach"] = (0, f"### Page\n- Page URL: {CONNECT}\n")
    replies["tab-new"] = (0, f"- 0: [Welcome]({CONNECT})\n")
    done = runtime.start("https://example.com/login")
    assert commands(calls) == ["attach", "tab-new", "tab-close", "resize"]
    assert calls[0][0] == ["attach", "--extension=chrome", "--session=" + runtime.SESSION]
    assert calls[0][1]["env"][runtime.TOKEN] == "dummy-private-token"
    assert all(runtime.TOKEN not in options["env"] for _, options in calls[1:])
    assert "dummy-private-token" not in json.dumps(done) + capsys.readouterr().out
    assert done["result"] == "BROWSER_READY" and done["url"] == "https://example.com/login"
    assert json.loads((tmp_path / done["state"] / "owner.json").read_text())["worktree"] == str(
        tmp_path.resolve()
    )


def test_start_deletes_the_automatic_snapshots(started, tmp_path, monkeypatch):
    real = runtime.page_tool

    def capture(root, arguments, token=""):
        done = real(root, arguments, token)
        saved = root / "playwright/.playwright-cli"
        saved.mkdir(exist_ok=True)
        (saved / "page.yml").write_text("private page")
        return done

    monkeypatch.setattr(runtime, "page_tool", capture)
    done = runtime.start("https://example.com/")
    assert not (tmp_path / done["state"] / "playwright/.playwright-cli").exists()


@pytest.mark.parametrize("value", ["", "op://vault/item/credential"])
def test_start_without_a_resolved_token_touches_nothing(tool, monkeypatch, value):
    calls, _ = tool
    monkeypatch.setenv(runtime.TOKEN, value)
    with pytest.raises(ValueError, match="BROWSER_TOKEN_UNRESOLVED"):
        runtime.start("https://example.com/")
    assert calls == []


def test_a_missing_page_tool_leaves_no_state_behind(started, tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "PAGE_ENTRY", tmp_path / "absent.js")
    before = set(tmp_path.iterdir())
    with pytest.raises(ValueError, match="BROWSER_PREREQUISITE"):
        runtime.start("https://example.com/")
    assert set(tmp_path.iterdir()) == before


def test_a_failed_connection_names_the_blocker_and_opens_no_tab(started):
    calls, replies = started
    replies["attach"] = (1, "")
    with pytest.raises(ValueError, match="BROWSER_EXTENSION_UNAVAILABLE"):
        runtime.start("https://example.com/")
    assert commands(calls) == ["attach"]


def test_close_removes_its_tabs_and_state_and_leaves_the_browser(root, tool):
    calls, replies = tool
    replies["list"] = (0, f"- {runtime.SESSION}:\n")
    replies["tab-list"] = (
        0,
        "- 0: [One](https://a.example/)\n- 1: (current) [Two](https://b.example/)\n",
    )
    assert runtime.close(root) == {"result": "BROWSER_CLOSED"}
    assert commands(calls) == ["list", "tab-list", "tab-close", "tab-close", "detach"]
    assert not root.exists()


def test_close_after_chrome_quit_still_removes_the_state(root, tool):
    calls, replies = tool
    replies["list"] = (0, "(no browsers)\n")
    assert runtime.close(root)["result"] == "BROWSER_CLOSED"
    assert commands(calls) == ["list"] and not root.exists()


@pytest.mark.parametrize("failing", ["list", "tab-list", "tab-close", "detach"])
def test_unconfirmed_close_retains_the_state(root, tool, failing):
    _, replies = tool
    replies["list"] = (0, f"- {runtime.SESSION}:\n")
    replies["tab-list"] = (0, "- 0: [One](https://a.example/)\n")
    replies[failing] = (1, replies.get(failing, (0, ""))[1])
    with pytest.raises(ValueError, match="CLOSE_UNCONFIRMED"):
        runtime.close(root)
    assert root.exists()
