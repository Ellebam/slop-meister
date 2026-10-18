"""The installed Chrome fallback stays independent and owns only its task profile."""

import json
from pathlib import Path
import subprocess

import pytest

from slopmeister.session import browser_chrome as chrome
from slopmeister.session import browser_login as browser
from slopmeister.session import browser_runtime as runtime
from slopmeister.session import browser_state as state


def test_chrome_is_an_explicit_start_choice():
    args = browser.arguments(["start", "https://example.com/", "--browser", "chrome"])
    assert args.browser == "chrome"
    assert browser.arguments(["start", "https://example.com/"]).browser == "orca"


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "TEMP_ROOT", tmp_path)
    monkeypatch.setattr(runtime, "TEMP_ROOT", tmp_path)
    root = tmp_path / "slopmeister-browser-test"
    root.mkdir(mode=0o700)
    (root / "profile").mkdir(mode=0o700)
    (root / "profile/DevToolsActivePort").write_text("12345\n/devtools/browser/owned-browser")
    state.save(
        root,
        {
            "browser": "chrome",
            "worktree": str(tmp_path),
            "pid": 321,
            "born": "Thu Oct 15 12:00:00 2026",
            "page": "OPAQUE_TARGET_1",
            "endpoint": "ws://127.0.0.1:12345/devtools/browser/owned-browser",
        },
    )
    return root


def test_chrome_navigation_inspection_and_input_do_not_call_orca(root, monkeypatch):
    def forbidden(*_):
        raise AssertionError("Orca must not be used by Chrome")

    monkeypatch.setattr(runtime, "binaries", forbidden)
    monkeypatch.setattr(runtime, "cli", forbidden)
    monkeypatch.setattr(chrome, "process", lambda *_: "owned")
    monkeypatch.setattr(
        chrome, "binaries", lambda: (Path("/installed/chrome"), Path("/installed/node"))
    )
    calls = []
    monkeypatch.setattr(
        runtime, "protocol_request", lambda *args: calls.append(args) or {"ok": True}
    )
    runtime.page_command(root, "open", "https://example.com/")
    runtime.page_command(root, "snapshot")
    runtime.request(root, {"action": "fill", "step": {}})
    assert [call[2]["action"] for call in calls] == ["open", "snapshot", "fill"]
    assert all(call[1] == Path("/installed/node") for call in calls)
    assert all(
        call[2]["endpoint"] == "ws://127.0.0.1:12345/devtools/page/OPAQUE_TARGET_1"
        for call in calls
    )


@pytest.mark.parametrize(
    "contents",
    [
        "0\n/devtools/browser/owned",
        "99999\n/devtools/browser/owned",
        "12345\n//remote.example/",
        "12345\n/devtools/browser/../page",
    ],
)
def test_endpoint_file_cannot_select_another_host_or_path(root, contents):
    (root / "profile/DevToolsActivePort").write_text(contents)
    with pytest.raises(ValueError, match="ENDPOINT_REFUSED"):
        chrome.browser_endpoint(root)


def test_symlinked_profile_is_not_followed(root):
    profile = root / "profile"
    profile.rename(root / "other")
    profile.symlink_to(root / "other", target_is_directory=True)
    with pytest.raises(ValueError, match="ENDPOINT_REFUSED"):
        chrome.browser_endpoint(root)


@pytest.mark.parametrize("fault", ["reused", "foreign", "inspection-denied"])
def test_process_identity_must_match_before_any_connection(root, monkeypatch, fault):
    data = state.metadata(root)
    birth = "Fri Oct 16 12:00:00 2026" if fault == "reused" else data["born"]
    directory = "/foreign/profile" if fault == "foreign" else str(root / "profile")
    result = subprocess.CompletedProcess([], 0, f"{birth} Chrome --user-data-dir={directory}", "")
    if fault == "inspection-denied":
        result = subprocess.CompletedProcess([], 1, "", "denied")
    monkeypatch.setattr(chrome.subprocess, "run", lambda *_, **__: result)
    with pytest.raises(ValueError, match="OWNER_REFUSED"):
        chrome.connection(root, data, "eval")
    assert (root / "owner.json").exists()


def test_changed_endpoint_is_not_rediscovered(root, monkeypatch):
    monkeypatch.setattr(chrome, "process", lambda *_: "owned")
    (root / "profile/DevToolsActivePort").write_text("12346\n/devtools/browser/replacement")
    with pytest.raises(ValueError, match="ENDPOINT_REFUSED"):
        chrome.connection(root, state.metadata(root), "eval")


def test_live_browser_must_exit_before_profile_deletion(root, monkeypatch):
    monkeypatch.setattr(chrome, "process", lambda *_: "owned")
    monkeypatch.setattr(chrome, "connection", lambda *_: (Path("/node"), "ws://127.0.0.1:1/"))
    monkeypatch.setattr(state, "request", lambda *_: {"result": "BROWSER_CLOSED"})
    ticks = iter([0, 10])
    monkeypatch.setattr(chrome.time, "monotonic", lambda: next(ticks))
    with pytest.raises(ValueError, match="CLOSE_UNCONFIRMED"):
        chrome.close(root, state.metadata(root))
    assert (root / "profile").is_dir() and (root / "owner.json").is_file()


def test_close_preserves_unexpected_files_and_recovery_state(root, monkeypatch):
    (root / "keep").write_text("unrelated")
    monkeypatch.setattr(chrome, "process", lambda *_: None)
    with pytest.raises(ValueError, match="STATE_REFUSED"):
        chrome.close(root, state.metadata(root))
    assert (root / "keep").read_text() == "unrelated"
    assert (root / "owner.json").is_file()


def test_close_removes_only_exited_owned_profile(root, monkeypatch):
    unrelated = root.parent / "unrelated-profile"
    unrelated.mkdir()
    (unrelated / "keep").write_text("keep")
    monkeypatch.setattr(chrome, "process", lambda *_: None)
    assert chrome.close(root, state.metadata(root)) == {"result": "BROWSER_CLOSED"}
    assert not root.exists() and (unrelated / "keep").read_text() == "keep"


def test_reused_pid_refuses_connection_but_allows_owned_profile_cleanup(root, monkeypatch):
    data = state.metadata(root)
    result = subprocess.CompletedProcess([], 0, "Fri Oct 16 12:00:00 2026 unrelated-process", "")
    monkeypatch.setattr(chrome.subprocess, "run", lambda *_, **__: result)

    def forbidden(*_):
        raise AssertionError("A reused PID must receive no browser command")

    monkeypatch.setattr(state, "request", forbidden)
    with pytest.raises(ValueError, match="BROWSER_CHROME_EXITED"):
        chrome.connection(root, data, "eval")
    assert chrome.close(root, data) == {"result": "BROWSER_CLOSED"}
    assert not root.exists()


def test_restarted_process_using_same_profile_still_blocks_cleanup(root, monkeypatch):
    result = subprocess.CompletedProcess(
        [], 0, f"Fri Oct 16 12:00:00 2026 Chrome --user-data-dir={root / 'profile'}", ""
    )
    monkeypatch.setattr(chrome.subprocess, "run", lambda *_, **__: result)
    with pytest.raises(ValueError, match="BROWSER_CHROME_OWNER_REFUSED"):
        chrome.close(root, state.metadata(root))
    assert (root / "profile").is_dir() and (root / "owner.json").is_file()


def test_launch_failure_retains_pid_and_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "TEMP_ROOT", tmp_path)
    monkeypatch.setattr(chrome, "binaries", lambda: (Path("/chrome"), Path("/node")))
    monkeypatch.setattr(state, "execute", lambda *_: {"websocket": True})

    class Child:
        pid = 321

    monkeypatch.setattr(chrome.subprocess, "Popen", lambda *_, **__: Child())
    monkeypatch.setattr(chrome, "process", lambda *_: "Thu Oct 15 12:00:00 2026")

    def timeout(*_):
        raise ValueError("BROWSER_CHROME_START_TIMEOUT")

    monkeypatch.setattr(chrome, "ready", timeout)
    with pytest.raises(ValueError, match="BROWSER_START_FAILED: retain state"):
        runtime.start("https://example.com/", "chrome")
    root = next(tmp_path.glob("slopmeister-browser-*"))
    assert json.loads((root / "owner.json").read_text())["pid"] == 321
    assert (root / "profile").is_dir()


def test_chrome_process_does_not_inherit_credentials_or_runtime_overrides(tmp_path, monkeypatch):
    for name in (
        "BROWSER_LOGIN_PASSWORD",
        "NODE_OPTIONS",
        "HTTPS_PROXY",
        "OP_SERVICE_ACCOUNT_TOKEN",
    ):
        monkeypatch.setenv(name, "dummy-private-value")
    data = {"browser": "chrome", "worktree": str(tmp_path)}

    class Child:
        pid = 321

    def spawn(argv, **options):
        assert "dummy-private-value" not in json.dumps(argv) + json.dumps(options["env"])
        assert options["stdout"] == options["stderr"] == subprocess.DEVNULL
        assert "--user-data-dir=" + str(tmp_path / "profile") in argv
        assert "--no-startup-window" in argv
        assert options["env"]["TMPDIR"] == str(tmp_path / "profile")
        return Child()

    monkeypatch.setattr(chrome.subprocess, "Popen", spawn)
    monkeypatch.setattr(chrome, "process", lambda *_: "Thu Oct 15 12:00:00 2026")
    chrome.launch(tmp_path, data, Path("/installed/chrome"))
    assert state.metadata(tmp_path)["pid"] == 321


def test_repository_node_shim_is_not_an_installed_runtime(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fake = tmp_path / "node"
    fake.write_text("not an installed runtime")
    monkeypatch.setattr(chrome.shutil, "which", lambda _: str(fake))
    monkeypatch.setattr(chrome.sys, "platform", "darwin")
    monkeypatch.setattr(Path, "is_file", lambda _: True)
    monkeypatch.setattr(chrome.os, "access", lambda *_: True)
    with pytest.raises(ValueError, match="BROWSER_PREREQUISITE"):
        chrome.binaries()


def test_home_directory_can_use_its_installed_node(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.chdir(home)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(state, "TEMP_ROOT", tmp_path / "temporary")
    installed = home / ".local/bin/node"
    monkeypatch.setattr(chrome.shutil, "which", lambda _: str(installed))
    monkeypatch.setattr(chrome.sys, "platform", "darwin")
    monkeypatch.setattr(Path, "is_file", lambda _: True)
    monkeypatch.setattr(chrome.os, "access", lambda *_: True)
    assert chrome.binaries()[1] == installed
