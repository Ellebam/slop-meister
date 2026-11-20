"""One Chrome per profile opens with the first state, stays for its peers and ends with the last."""

import errno
import fcntl
import json
import os
from pathlib import Path

import pytest

from slopmeister.session import browser_display as display
from slopmeister.session import browser_runtime as runtime
from slopmeister.session import browser_state as state
from tests.support.browser import commands

URL = "https://example.com/login"
PEER = "/elsewhere/playwright"


def states(tmp_path):
    return sorted(tmp_path.glob(state.PREFIX + "*"))


def test_start_opens_the_profile_chrome_and_an_own_tab_in_it(chrome, profiles, tmp_path):
    done = runtime.start(URL, "test")
    assert commands(chrome.calls) == [
        "list", "open", "attach", "tab-new", "tab-list", "resize", "tab-list"
    ]  # fmt: skip
    keeper, options = chrome.calls[1]
    assert keeper == [
        "-s=" + runtime.KEEPER, "open", "--persistent", f"--profile={profiles / 'test'}",
        "--browser=chrome", "--headed", "about:blank",
    ]  # fmt: skip
    assert options["cwd"] == state.RUNTIME / "test/keeper"
    assert chrome.calls[2][0] == ["attach", runtime.KEEPER, "--session=" + runtime.SESSION]
    assert chrome.calls[3][0] == ["-s=" + runtime.SESSION, "tab-new", URL]
    assert chrome.helper[0] == {"action": "own", "index": 1}
    saved = json.loads((Path(done["state"]) / "owner.json").read_text())
    assert saved["own"] == "T1" and saved["profile"] == "test" and "tab_unproven" not in saved
    assert saved["worktree"] == str(tmp_path.resolve())
    assert done == {
        "result": "BROWSER_READY",
        "state": done["state"],
        "profile": "test",
        "url": "https://a.example/",
    }


def test_a_second_state_shares_the_running_chrome(chrome):
    runtime.start(URL, "test")
    chrome.calls.clear()
    runtime.start(URL, "test")
    assert "open" not in commands(chrome.calls) and len(chrome.attached) == 2


@pytest.mark.parametrize("name", ["", "../escape", "a/b", "Upper", "-dash", "x" * 33, "a.b"])
def test_a_profile_name_that_could_leave_the_profile_folder_starts_nothing(chrome, name, profiles):
    with pytest.raises(ValueError, match="BROWSER_PROFILE_REFUSED"):
        runtime.start(URL, name)
    assert chrome.calls == [] and not profiles.exists()


def test_a_missing_page_tool_leaves_no_state_behind(chrome, monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, "PAGE_ENTRY", tmp_path / "absent.js")
    with pytest.raises(ValueError, match="BROWSER_PREREQUISITE"):
        runtime.start(URL, "test")
    assert states(tmp_path) == [] and chrome.calls == []


def snapshots_after_every_run(chrome, monkeypatch):
    """The page tool saves a page file after every command, as the real one does."""
    real = chrome.run

    def run(argv, **options):
        done = real(argv, **options)
        if str(options.get("cwd", "")).endswith("playwright"):
            saved = Path(options["cwd"]) / ".playwright-cli"
            saved.mkdir(exist_ok=True)
            (saved / "page.yml").write_text("another session's page")
        return done

    monkeypatch.setattr(runtime.subprocess, "run", run)


def test_a_failed_attach_removes_the_snapshots_and_closes_the_state(chrome, monkeypatch, tmp_path):
    snapshots_after_every_run(chrome, monkeypatch)
    chrome.replies["attach"] = (1, "### Error\nError: no browser named keep\n")
    with pytest.raises(
        ValueError, match="BROWSER_START_FAILED: Error: no browser .*state is closed"
    ):
        runtime.start(URL, "test")
    assert states(tmp_path) == [] and not chrome.keeper


def test_an_unreachable_address_names_chromes_network_error(chrome):
    chrome.replies["tab-new"] = (
        1,
        "### Error\nnet::ERR_NAME_NOT_RESOLVED at https://a.invalid/?login_hint=x\nCall log:\n",
    )
    with pytest.raises(ValueError) as refusal:
        runtime.start(URL, "test")
    assert str(refusal.value) == (
        "BROWSER_START_FAILED: net::ERR_NAME_NOT_RESOLVED at https://a.invalid/?hidden; "
        "the state is closed"
    )


def test_a_failed_start_that_cannot_close_keeps_what_close_needs_and_no_snapshot(
    chrome, monkeypatch, tmp_path
):
    snapshots_after_every_run(chrome, monkeypatch)
    chrome.replies["tab-new"] = (1, "### Error\nError: Target page closed\n")
    chrome.replies["detach"] = (1, "")
    with pytest.raises(ValueError, match="BROWSER_START_FAILED: .*retain state") as refusal:
        runtime.start(URL, "test")
    root = Path(str(refusal.value).split("retain state ")[1].split()[0])
    assert not (root / runtime.SNAPSHOTS).exists()
    saved = runtime.metadata(root)
    assert saved["profile"] == "test" and saved["tab_unproven"] is True


def test_a_disk_error_in_start_closes_the_state_and_removes_its_snapshots(
    chrome, monkeypatch, tmp_path
):
    snapshots_after_every_run(chrome, monkeypatch)

    def full(_reply):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(runtime, "current_tab", full)
    with pytest.raises(ValueError, match="No space left on device.*state is closed"):
        runtime.start(URL, "test")
    assert states(tmp_path) == [] and not chrome.keeper


def test_a_new_profile_is_seeded_only_under_the_profile_lock(chrome, monkeypatch):
    held = []
    seed = state.profile

    def probe(name):
        descriptor = os.open(state.runtime(name) / "lock", os.O_RDWR)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            held.append(False)
        except BlockingIOError:
            held.append(True)
        finally:
            os.close(descriptor)
        return seed(name)

    monkeypatch.setattr(state, "profile", probe)
    runtime.start(URL, "test")
    assert held == [True], "two first starts would copy into one profile at once"


def test_a_failed_start_leaves_a_peers_chrome_open(chrome):
    chrome.keeper = True
    chrome.attached.add(PEER)
    chrome.replies["tab-new"] = (1, "### Error\nError: Target page closed\n")
    with pytest.raises(ValueError, match="state is closed"):
        runtime.start(URL, "test")
    assert chrome.keeper and chrome.attached == {PEER} and chrome.units == []


def test_start_does_not_report_ready_on_a_blank_tab(chrome, tmp_path):
    chrome.answers["filled"] = {"result": "PAGE_LOST"}
    with pytest.raises(ValueError, match="BROWSER_PAGE_NOT_REACHED: BROWSER_TAB_LOST"):
        runtime.start(URL, "test")
    assert states(tmp_path) == [] and not chrome.keeper


def test_a_desktop_with_no_monitor_refuses_start_before_chrome_launches(
    chrome, monkeypatch, tmp_path
):
    monkeypatch.setattr(display, "monitorless", lambda: True)
    with pytest.raises(ValueError, match="BROWSER_NO_MONITOR: .*--private-display"):
        runtime.start(URL, "test")
    assert "open" not in commands(chrome.calls) and states(tmp_path) == []


def test_the_last_close_ends_chrome_and_an_earlier_one_keeps_it(chrome):
    first = Path(runtime.start(URL, "test")["state"])
    second = Path(runtime.start(URL, "test")["state"])
    chrome.calls.clear()
    assert runtime.close(first) == {"result": "BROWSER_CLOSED"}
    assert commands(chrome.calls) == ["list", "detach", "list"]
    assert chrome.keeper and not first.exists()
    assert runtime.close(second) == {"result": "BROWSER_CLOSED"}
    assert not chrome.keeper and not second.exists()
    assert [p for p in chrome.helper if p["action"] == "close"] == [{"action": "close"}] * 2


def test_close_still_closes_the_own_tab_when_the_session_is_gone(chrome, root):
    chrome.keeper = True
    chrome.attached.add(PEER)
    assert runtime.close(root) == {"result": "BROWSER_CLOSED"}
    assert chrome.helper == [{"action": "close"}] and "detach" not in commands(chrome.calls)


def test_close_reports_an_own_tab_it_could_not_close_while_chrome_stays(chrome, root):
    chrome.keeper = True
    chrome.attached.add(PEER)
    chrome.answers["close"] = ValueError("BROWSER_CONNECTION_LOST")
    runtime.save(root, {**runtime.metadata(root), "address": "https://a.example/login"})
    done = runtime.close(root)
    assert done["tabs_left"].startswith("https://a.example/login may still be open")


def test_close_after_chrome_quit_still_removes_the_state(chrome, root):
    assert runtime.close(root) == {"result": "BROWSER_CLOSED"}
    assert not root.exists()


@pytest.mark.parametrize("failing", ["list", "detach", "close"])
def test_unconfirmed_close_retains_the_state(chrome, failing):
    root = Path(runtime.start(URL, "test")["state"])
    chrome.replies[failing] = (1, "")
    with pytest.raises(ValueError, match="CLOSE_UNCONFIRMED"):
        runtime.close(root)
    assert runtime.metadata(root)["profile"] == "test"


@pytest.mark.parametrize(
    ("platform", "monitors", "expected"),
    [
        ("linux", (0, "Monitors: 0\n"), True),
        ("linux", (0, "Monitors: 1\n 0: +*XWAYLAND0 1920/0x1080/0+0+0  XWAYLAND0\n"), False),
        ("linux", (1, "Can't open display\n"), False),
        ("linux", None, False),
        ("darwin", (0, "Monitors: 0\n"), False),
    ],
)
def test_only_a_desktop_with_zero_monitors_counts_as_monitorless(
    monkeypatch, platform, monitors, expected
):
    monkeypatch.setattr(display.sys, "platform", platform)
    monkeypatch.setattr(
        display.shutil, "which", lambda name: None if monitors is None else f"/usr/bin/{name}"
    )
    reply = monitors or (0, "")
    monkeypatch.setattr(
        display.subprocess,
        "run",
        lambda argv, **_: display.subprocess.CompletedProcess(argv, reply[0], reply[1], ""),
    )
    assert display.monitorless() is expected


@pytest.fixture
def screen(chrome, monkeypatch, tmp_path):
    """A display unit that reports its number at once, with no real X server."""
    sockets = tmp_path / "x11"
    sockets.mkdir()
    (sockets / "X7").touch()
    monkeypatch.setattr(display, "X_SOCKETS", sockets)
    monkeypatch.setattr(display.shutil, "which", lambda name: f"/usr/bin/{name}")
    real = chrome.run

    def run(argv, **options):
        if str(argv[0]).endswith("systemd-run"):
            Path(argv[-1]).write_text(":7\n")
        return real(argv, **options)

    monkeypatch.setattr(runtime.subprocess, "run", run)
    monkeypatch.setattr(display, "monitorless", lambda: True)
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    return chrome


def test_private_display_runs_the_profile_chrome_in_an_owner_only_x_display_without_tcp(screen):
    runtime.start(URL, "test", private_display=True)
    folder = state.RUNTIME / "test/display"
    unit, _ = screen.units[0]
    assert unit[:5] == [
        "/usr/bin/systemd-run", "--user", "--collect", "--quiet", "--unit=slopmeister-browser-test"
    ]  # fmt: skip
    assert "--property=RuntimeMaxSec=1800" in unit
    assert unit[unit.index("/usr/bin/env") : unit.index("/bin/sh")] == [
        "/usr/bin/env", "-u", "WAYLAND_DISPLAY", "/usr/bin/xvfb-run", "-a",
        "-f", str(folder / "xauth"), "-s", "-screen 0 1920x1080x24 -nolisten tcp",
    ]  # fmt: skip
    assert folder.stat().st_mode & 0o777 == 0o700
    env = screen.calls[1][1]["env"]
    assert env["DISPLAY"] == ":7" and env["XAUTHORITY"] == str(folder / "xauth")
    assert "WAYLAND_DISPLAY" not in env


def test_a_display_that_never_reports_is_stopped(screen, monkeypatch, tmp_path):
    monkeypatch.setattr(display, "X_SOCKETS", tmp_path / "absent")
    monkeypatch.setattr(display, "READY_SECONDS", 0)
    with pytest.raises(ValueError, match="BROWSER_DISPLAY_FAILED"):
        runtime.start(URL, "test", private_display=True)
    assert [argv[2] for argv, _ in screen.units[1:]] == ["stop", "is-active"]
    assert "open" not in commands(screen.calls) and states(tmp_path) == []


@pytest.mark.parametrize(("active", "closed"), [(3, True), (4, True), (0, False), (1, False)])
def test_the_last_close_stops_the_display_and_keeps_the_state_until_it_is_gone(
    screen, active, closed
):
    root = Path(runtime.start(URL, "test", private_display=True)["state"])
    screen.unit_codes["is-active"] = active
    if closed:
        assert runtime.close(root)["result"] == "BROWSER_CLOSED"
    else:
        with pytest.raises(ValueError, match="CLOSE_UNCONFIRMED"):
            runtime.close(root)
    assert [argv[2:4] for argv, _ in screen.units[1:]] == [
        ["stop", "slopmeister-browser-test"],
        ["is-active", "--quiet"],
    ]
    assert root.exists() is not closed


def test_the_display_stops_even_when_chrome_does_not_close(screen):
    root = Path(runtime.start(URL, "test", private_display=True)["state"])
    screen.replies["close"] = (1, "")
    with pytest.raises(ValueError, match="the profile's Chrome did not close"):
        runtime.close(root)
    assert [argv[2] for argv, _ in screen.units[1:]] == ["stop", "is-active"]
