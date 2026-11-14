"""Page commands stay inside their allowlist and the extension token stays out of every output."""

import json

import pytest

from slopmeister.session import browser_display as display
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


def test_a_desktop_with_no_monitor_refuses_start_before_chrome_launches(
    started, tmp_path, monkeypatch
):
    calls, _ = started
    monkeypatch.setattr(display, "monitorless", lambda: True)
    before = set(tmp_path.iterdir())
    with pytest.raises(ValueError, match="BROWSER_NO_MONITOR: .*--private-display"):
        runtime.start("https://example.com/")
    assert calls == [] and set(tmp_path.iterdir()) == before


@pytest.mark.parametrize(
    ("platform", "chrome", "monitors", "expected"),
    [
        ("linux", 1, (0, "Monitors: 0\n"), True),
        ("linux", 0, (0, "Monitors: 0\n"), False),
        ("linux", 1, (0, "Monitors: 1\n 0: +*XWAYLAND0 1920/0x1080/0+0+0  XWAYLAND0\n"), False),
        ("linux", 1, (1, "Can't open display\n"), False),
        ("linux", 1, None, False),
        ("darwin", 1, (0, "Monitors: 0\n"), False),
    ],
)
def test_only_a_closed_chrome_on_a_desktop_with_zero_monitors_counts_as_monitorless(
    monkeypatch, platform, chrome, monitors, expected
):
    monkeypatch.setattr(display.sys, "platform", platform)
    monkeypatch.setattr(
        display.shutil,
        "which",
        lambda name: None if name == "xrandr" and monitors is None else f"/usr/bin/{name}",
    )

    def run(argv, **options):
        assert "env" in options and runtime.TOKEN not in options["env"]
        code, output = (chrome, "") if argv[0].endswith("pgrep") else monitors
        return display.subprocess.CompletedProcess(argv, code, output, "")

    monkeypatch.setenv(runtime.TOKEN, "dummy-private-token")
    monkeypatch.setattr(display.subprocess, "run", run)
    assert display.monitorless() is expected


@pytest.fixture
def units(started, monkeypatch):
    """Record systemd calls beside the page tool calls, in one order, and run neither."""
    calls, _ = started
    page_tool = runtime.subprocess.run
    replies = {"stop": 0, "is-active": 3}
    monkeypatch.setattr(runtime.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(display, "chrome_ready", lambda: True)

    def run(argv, **options):
        if str(argv[0]).endswith("node"):
            return page_tool(argv, **options)
        calls.append((argv, options))
        verb = next(a for a in argv[1:] if not a.startswith("-"))
        return runtime.subprocess.CompletedProcess(argv, replies.get(verb, 0), "", "")

    monkeypatch.setattr(runtime.subprocess, "run", run)
    return calls, replies


def test_private_display_runs_chrome_in_an_owner_only_x_display_without_tcp(
    units, tmp_path, monkeypatch
):
    calls, _ = units
    monkeypatch.setattr(display, "monitorless", lambda: True)
    done = runtime.start("https://example.com/", private_display=True)
    state = tmp_path / done["state"]
    unit, options = calls[0]
    assert unit[:5] == [
        "/usr/bin/systemd-run",
        "--user",
        "--collect",
        "--quiet",
        "--unit=" + state.name,
    ]
    assert "--property=RuntimeMaxSec=1800" in unit
    assert unit[unit.index("/usr/bin/env") :] == [
        "/usr/bin/env", "-u", "WAYLAND_DISPLAY", "/usr/bin/xvfb-run", "-a",
        "-f", str(state / "display/xauth"), "-s", "-screen 0 1920x1080x24 -nolisten tcp",
        "/usr/bin/google-chrome-stable", "--ozone-platform=x11",
    ]  # fmt: skip
    assert runtime.TOKEN not in options["env"]
    assert (state / "display").stat().st_mode & 0o777 == 0o700
    assert commands(calls[1:]) == ["attach", "tab-new", "tab-close", "resize"]
    assert json.loads((state / "owner.json").read_text())["display"] is True


def test_attach_waits_for_the_display_chrome_and_never_launches_another(units, monkeypatch):
    calls, _ = units
    monkeypatch.setattr(display, "chrome_ready", lambda: False)
    monkeypatch.setattr(display, "READY_SECONDS", 0)
    with pytest.raises(ValueError, match="BROWSER_DISPLAY_FAILED: .*retain state"):
        runtime.start("https://example.com/", private_display=True)
    assert [argv[0] for argv, _ in calls] == ["/usr/bin/systemd-run"]


@pytest.mark.parametrize(("active", "closed"), [(3, True), (4, True), (0, False), (1, False)])
def test_close_stops_the_display_chrome_and_keeps_the_state_until_it_is_gone(
    root, units, active, closed
):
    calls, replies = units
    runtime.save(root, {**runtime.metadata(root), "display": True})
    replies["is-active"] = active
    if closed:
        assert runtime.close(root)["result"] == "BROWSER_CLOSED"
    else:
        with pytest.raises(ValueError, match="CLOSE_UNCONFIRMED"):
            runtime.close(root)
    assert [argv[2:] for argv, _ in calls[1:]] == [
        ["stop", root.name],
        ["is-active", "--quiet", root.name],
    ]
    assert root.exists() is not closed


def test_close_stops_the_display_chrome_even_when_detach_fails(root, units, tool):
    calls, replies = units
    _, pages = tool
    runtime.save(root, {**runtime.metadata(root), "display": True})
    pages["list"] = (0, f"- {runtime.SESSION}:\n")
    pages["detach"] = (1, "")
    with pytest.raises(ValueError, match="CLOSE_UNCONFIRMED"):
        runtime.close(root)
    assert [argv[2] for argv, _ in calls[-2:]] == ["stop", "is-active"]
    assert root.exists()


@pytest.mark.parametrize("failing", [False, True])
def test_page_output_hides_the_query_and_fragment_of_every_address(root, tool, failing):
    _, replies = tool
    authorize = "https://id.example/authorize?state=s1&login_hint=a%40b.example&code_challenge=c1"
    replies["eval"] = (
        int(failing),
        f'"{authorize}"\n- 0: [Back](https://app.example/cb#code=c2&id_token=t1)\n'
        f"- 1: [Welcome]({CONNECT})\n- 2: [Plain](https://a.example/path)\n"
        "- /url: /reset?login_hint=r1\n- /url: reset?code=r2\n- /url: #token=r3\n"
        '- 3: [Reset](/reset?code=r4)\n"https://a.example/cb?a)b&code=r5"\n',
    )
    output = runtime.page(root, ["eval", "() => location.href"]).stdout
    leaks = ("s1", "a%40b", "c1", "c2", "t1", "r1", "r2", "r3", "r4", "r5")
    for value in (*leaks, "dummy-private-token"):
        assert value not in output
    assert '"https://id.example/authorize?hidden"' in output
    assert "(https://app.example/cb?hidden)" in output and "(https://a.example/path)" in output
    assert "/url: /reset?hidden" in output and "[Reset](/reset?hidden)" in output
