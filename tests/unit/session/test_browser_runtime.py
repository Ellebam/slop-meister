"""Page commands stay inside their allowlist and inside this session's own tab of the profile."""

import json

import pytest

from slopmeister.session import browser_runtime as runtime
from slopmeister.session import browser_state as state
from tests.support.browser import commands

SAVED = "playwright/.playwright-cli"
OTHER = "- 0: [Other plot](https://other.example/private)\n"


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
        (["attach", "keep"], "COMMAND_REFUSED"),
        (["detach"], "COMMAND_REFUSED"),
        (["open", "https://example.com/"], "COMMAND_REFUSED"),
        (["tab-new", "https://example.com/"], "COMMAND_REFUSED"),
        (["close"], "COMMAND_REFUSED"),
        ([], "COMMAND_REFUSED"),
        (["screenshot", "--filename=/etc/passwd"], "OPTION_REFUSED"),
        (["snapshot", "--filename", "../../outside.yml"], "OPTION_REFUSED"),
        (["eval", "() => 1", "--config=/tmp/other.json"], "OPTION_REFUSED"),
        (["click", "e1", "-s=keep"], "OPTION_REFUSED"),
        (["mousewheel", "0", "-500", "--filename=x"], "OPTION_REFUSED"),
        (["tab-list", "--json"], "OPTION_REFUSED"),
        (["goto", "file:///etc/passwd"], "URL_REFUSED"),
    ],
)
def test_page_commands_outside_the_allowlist_start_nothing(root, chrome, command, reason):
    with pytest.raises(ValueError, match=reason):
        runtime.page(root, command)
    assert chrome.calls == [] and chrome.helper == []


def test_page_tool_keeps_its_files_in_the_state_and_its_lists_in_the_profile(
    root, chrome, monkeypatch
):
    monkeypatch.setenv("BROWSER_LOGIN_PASSWORD", "dummy-private-value")
    runtime.page(root, ["goto", "https://example.com/"])
    argv, options = chrome.calls[1]
    assert argv == ["-s=" + runtime.SESSION, "goto", "https://example.com/"]
    profile = state.RUNTIME / "test"
    assert options["cwd"] == root / "playwright"
    assert options["env"]["PWTEST_SOCKETS_DIR"] == str(profile / "sockets")
    assert options["env"]["PWTEST_DAEMON_SESSION_DIR"] == str(profile / "daemon")
    assert options["env"]["PWTEST_SERVER_REGISTRY"] == str(profile / "registry")
    assert options["env"]["PWTEST_CLI_GLOBAL_CONFIG"] == str(root / "playwright")
    assert options["env"]["TMPDIR"] == str(root / "playwright/tmp")
    assert "dummy-private-value" not in json.dumps(options["env"])
    for folder in (root / "playwright", profile, state.RUNTIME):
        assert folder.stat().st_mode & 0o777 == 0o700
    config = json.loads((root / "playwright/.playwright/cli.config.json").read_text())
    assert config == {"console": {"level": "none"}}, "page console capture must stay off"


@pytest.mark.parametrize("command", [["snapshot"], ["click", "e3"]])
@pytest.mark.parametrize("reply", ["FILLED", "PAGE_OPERATION_FAILED"])
def test_no_page_command_runs_while_a_password_field_holds_a_value_even_before_any_fill(
    root, chrome, command, reply
):
    runtime.save(root, {**runtime.metadata(root), "credential_fields": ["#user"]})
    chrome.answers["filled"] = {"result": reply}
    with pytest.raises(ValueError, match="PAGE_REFUSED"):
        runtime.page(root, command)
    assert commands(chrome.calls) == ["tab-list"], "the page tool saves a snapshot"
    assert chrome.helper == [
        {
            "action": "filled",
            "selectors": ["input[type=password]", 'input[autocomplete="one-time-code"]', "#user"],
            "current": 1,
        }
    ]


def test_a_password_revealed_by_an_action_withholds_its_output_and_snapshot(root, chrome):
    chrome.replies["click"] = (0, "### Page\nprivate output\n")
    chrome.answers["filled"] = [{"result": "EMPTY", "owned": [1]}, {"result": "FILLED"}]
    saved = root / SAVED
    saved.parent.mkdir(mode=0o700, exist_ok=True)
    saved.mkdir(mode=0o700)
    (saved / "page.yml").write_text("revealed password")
    with pytest.raises(ValueError, match="PAGE_REFUSED: a credential field holds a value"):
        runtime.page(root, ["click", "e1"])
    assert commands(chrome.calls) == ["tab-list", "click", "tab-list"] and not saved.exists()


def test_a_current_tab_of_another_session_runs_nothing(root, chrome):
    chrome.tabs = OTHER.replace("- 0:", "- 0: (current)") + "- 1: [Page](https://a.example/)\n"
    chrome.answers["filled"] = {"result": "FOREIGN"}
    with pytest.raises(ValueError, match="not this session's own page"):
        runtime.page(root, ["press", "Enter"])
    assert commands(chrome.calls) == ["tab-list"] and chrome.helper[0]["current"] == 0


def test_an_action_that_lands_on_another_sessions_tab_withholds_its_output(root, chrome):
    chrome.replies["click"] = (0, "### Page\nanother plot's page\n")
    chrome.answers["filled"] = [{"result": "EMPTY", "owned": [1]}, {"result": "FOREIGN"}]
    saved = root / SAVED
    saved.parent.mkdir(mode=0o700, exist_ok=True)
    saved.mkdir(mode=0o700)
    (saved / "page.yml").write_text("another plot's page")
    with pytest.raises(ValueError, match="may have reached another session's page"):
        runtime.page(root, ["click", "e1"])
    assert not saved.exists()


def test_every_reply_drops_the_open_tabs_of_other_sessions(root, chrome):
    chrome.replies["snapshot"] = (
        0,
        f"### Open tabs\n{OTHER}{chrome.tabs}### Page\n- Page Title: Mine\n",
    )
    output = runtime.page(root, ["snapshot"]).stdout
    assert "other.example" not in output and "Other plot" not in output
    assert "Page Title: Mine" in output


def test_the_tab_list_shows_only_own_tabs(root, chrome):
    chrome.tabs = (
        f"{OTHER}- 1: (current) [Mine](https://a.example/)\n- 2: [Popup](https://c.example/)\n"
    )
    chrome.answers["filled"] = {"result": "EMPTY", "main": 1, "owned": [1, 2]}
    output = runtime.page(root, ["tab-list"]).stdout
    assert "other.example" not in output and "Other plot" not in output
    assert "[Mine](https://a.example/)" in output and "[Popup](https://c.example/)" in output


def test_the_tab_list_finds_the_way_back_from_another_sessions_current_tab(root, chrome):
    chrome.tabs = f"{OTHER.replace('- 0:', '- 0: (current)')}- 1: [Mine](https://a.example/)\n"
    chrome.answers["filled"] = {"result": "EMPTY", "main": 1, "owned": [1]}
    output = runtime.page(root, ["tab-list"]).stdout
    assert "[Mine](https://a.example/)" in output and "other.example" not in output
    assert [p["current"] for p in chrome.helper] == [None, None]


def test_tab_select_reaches_only_an_own_tab(root, chrome):
    chrome.tabs = (
        f"{OTHER}- 1: (current) [Mine](https://a.example/)\n- 2: [Popup](https://c.example/)\n"
    )
    chrome.answers["filled"] = {"result": "EMPTY", "main": 1, "owned": [1, 2]}
    with pytest.raises(ValueError, match="select one of this session's own tabs"):
        runtime.page(root, ["tab-select", "0"])
    assert commands(chrome.calls) == ["tab-list"]
    assert chrome.helper[0]["current"] is None, "a peer's current tab must not block a return"
    runtime.page(root, ["tab-select", "2"])
    assert chrome.calls[-2][0] == ["-s=" + runtime.SESSION, "tab-select", "2"]


@pytest.mark.parametrize("index", ["0", "1"])
def test_tab_close_refuses_the_main_tab_and_other_sessions_tabs(root, chrome, index):
    chrome.tabs = (
        f"{OTHER}- 1: (current) [Mine](https://a.example/)\n- 2: [Popup](https://c.example/)\n"
    )
    chrome.answers["filled"] = {"result": "EMPTY", "main": 1, "owned": [1, 2]}
    with pytest.raises(ValueError, match="close one of this session's own popups"):
        runtime.page(root, ["tab-close", index])
    assert commands(chrome.calls) == ["tab-list"]


def test_tab_close_closes_an_own_popup_by_its_target_and_returns_to_the_own_tab(root, chrome):
    chrome.tabs = "- 1: [Mine](https://a.example/)\n- 2: (current) [Popup](https://c.example/)\n"
    chrome.answers["filled"] = {"result": "EMPTY", "main": 1, "owned": [1, 2]}
    runtime.page(root, ["tab-close"])
    assert chrome.helper[1] == {"action": "close", "index": 2}
    assert "tab-close" not in commands(chrome.calls), "a shifted index could close a peer's tab"
    assert chrome.calls[-2][0] == ["-s=" + runtime.SESSION, "tab-select", "1"]


def test_negative_numbers_are_data_not_options(root, chrome):
    runtime.page(root, ["mousewheel", "0", "-500"])
    assert chrome.calls[1][0][1:] == ["mousewheel", "0", "-500"]


def test_every_helper_request_names_the_own_tab(root, monkeypatch, profiles):
    sockets = state.runtime("test") / "sockets/browser"
    sockets.mkdir()
    (sockets / "a.sock").touch()
    sent = []
    monkeypatch.setattr(runtime, "node", lambda: "node")
    monkeypatch.setattr(runtime, "protocol_request", lambda _r, _n, p: sent.append(p) or {})
    runtime.request(root, {"action": "fill", "steps": []})
    assert sent[0]["own"] == "T1" and sent[0]["socket"] == str(sockets / "a.sock")


def test_a_lost_connection_is_named(root, profiles):
    with pytest.raises(ValueError, match="CONNECTION_LOST"):
        runtime.socket(root)


@pytest.mark.parametrize("failing", [False, True])
def test_page_output_hides_the_query_and_fragment_of_every_address(root, chrome, failing):
    authorize = "https://id.example/authorize?state=s1&login_hint=a%40b.example&code_challenge=c1"
    chrome.replies["eval"] = (
        int(failing),
        f'"{authorize}"\n- 0: [Back](https://app.example/cb#code=c2&id_token=t1)\n'
        "- 2: [Plain](https://a.example/path)\n"
        "- /url: /reset?login_hint=r1\n- /url: reset?code=r2\n- /url: #token=r3\n"
        '- 3: [Reset](/reset?code=r4)\n"https://a.example/cb?a)b&code=r5"\n',
    )
    output = runtime.page(root, ["eval", "() => location.href"]).stdout
    for value in ("s1", "a%40b", "c1", "c2", "t1", "r1", "r2", "r3", "r4", "r5"):
        assert value not in output
    assert '"https://id.example/authorize?hidden"' in output
    assert "(https://app.example/cb?hidden)" in output and "(https://a.example/path)" in output
    assert "/url: /reset?hidden" in output and "[Reset](/reset?hidden)" in output
