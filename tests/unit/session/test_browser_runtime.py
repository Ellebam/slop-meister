"""Visible task-owned Orca profiles have bounded, resumable cleanup and private state."""

import json
from pathlib import Path

import pytest

from slopmeister.session import browser_login as browser
from slopmeister.session import browser_runtime as runtime
from slopmeister.session import browser_state as state

PROFILE = "11111111-1111-4111-8111-111111111111"
PAGE = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "TEMP_ROOT", tmp_path)
    monkeypatch.setattr(state, "TEMP_ROOT", tmp_path)
    path = tmp_path / "slopmeister-browser-test"
    path.mkdir(mode=0o700)
    runtime.save(path, {"profile": PROFILE, "page": PAGE, "worktree": str(tmp_path)})
    return path


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


def test_linux_uses_the_runtime_bundled_with_orca(monkeypatch):
    installed = {"/opt/Orca/resources/bin/orca-ide", "/opt/Orca/orca-ide"}
    monkeypatch.setattr(runtime.sys, "platform", "linux")
    monkeypatch.setattr(runtime.shutil, "which", lambda _: "/opt/Orca/resources/bin/orca-ide")
    monkeypatch.setattr(Path, "resolve", lambda path: path)
    monkeypatch.setattr(Path, "is_file", lambda path: str(path) in installed)
    monkeypatch.setattr(runtime.os, "access", lambda path, _: str(path) in installed)
    assert tuple(map(str, runtime.binaries())) == (
        "/opt/Orca/resources/bin/orca-ide",
        "/opt/Orca/orca-ide",
    )


def test_close_targets_only_saved_tab_and_profile(root, monkeypatch):
    calls = []

    def cli(_root, command):
        calls.append(command)
        return {"closed": True, "deleted": True, "tabs": []}

    monkeypatch.setattr(runtime, "cli", cli)
    assert runtime.close(root) == {"result": "BROWSER_CLOSED"}
    assert calls[1][:4] == ["tab", "close", "--page", PAGE]
    assert calls[2] == ["tab", "profile", "delete", "--profile", PROFILE]
    assert not root.exists()


def test_failed_profile_cleanup_retains_resumable_state(root, monkeypatch):
    def cli(_root, command):
        return {"closed": True} if command[1] == "close" else {"deleted": False, "tabs": []}

    monkeypatch.setattr(runtime, "cli", cli)
    with pytest.raises(ValueError, match="CLOSE_UNCONFIRMED"):
        runtime.close(root)
    assert "page" not in runtime.metadata(root)
    assert runtime.metadata(root)["profile"] == PROFILE


def test_close_preserves_unexpected_files(root, monkeypatch):
    retained = root / "unrelated.txt"
    retained.write_text("keep")
    runtime.credential_state(root, create=True)
    monkeypatch.setattr(runtime, "cli", lambda *_: {"closed": True, "deleted": True, "tabs": []})
    with pytest.raises(ValueError, match="BROWSER_STATE_REFUSED"):
        runtime.close(root)
    assert retained.read_text() == "keep"
    assert (root / "owner.json").is_file()
    assert runtime.credential_state(root)
    assert runtime.owned(str(root)) == root
    retained.unlink()
    assert runtime.close(root) == {"result": "BROWSER_CLOSED"}
    assert not root.exists()


@pytest.mark.parametrize("command", [["press", "Enter"], ["type", "text"], ["state", "save"]])
def test_native_keyboard_and_persistence_commands_are_refused(root, command):
    with pytest.raises(ValueError, match="COMMAND_REFUSED"):
        browser.run(root, command)


def test_snapshot_is_refused_after_credentials(root):
    runtime.credential_state(root, create=True)
    with pytest.raises(ValueError, match="SNAPSHOT_REFUSED"):
        browser.run(root, ["snapshot"])


def test_marker_symlink_cannot_touch_its_target(root):
    target = root / "keep"
    target.write_text("unchanged")
    (root / runtime.MARKER).symlink_to(target)
    with pytest.raises(ValueError, match="STATE_REFUSED"):
        runtime.credential_state(root, create=True)
    assert target.read_text() == "unchanged"


def test_owned_state_cannot_supply_command_options(root):
    data = json.loads((root / "owner.json").read_text())
    data["page"] = "--all"
    runtime.save(root, data)
    with pytest.raises(ValueError):
        runtime.owned(str(root))


def test_read_failure_is_distinct_from_submission_failure(root, monkeypatch):
    def failed(*_):
        raise ValueError("BROWSER_OPERATION_FAILED: do not retry submission")

    monkeypatch.setattr(runtime, "request", failed)
    with pytest.raises(ValueError, match="BROWSER_READ_FAILED"):
        browser.run(root, ["eval", "invalid expression"])
    with pytest.raises(ValueError, match="BROWSER_OPERATION_FAILED"):
        runtime.request(root, {"action": "fill", "step": {}})


@pytest.mark.parametrize("route", ["orca", "chrome"])
def test_snapshot_failure_is_reported_as_a_read_failure(root, monkeypatch, route):
    data = runtime.metadata(root)
    runtime.save(root, {**data, "browser": route})

    def failed(*_):
        raise ValueError("BROWSER_OPERATION_FAILED: do not retry submission")

    monkeypatch.setattr(runtime, "cli", failed)
    monkeypatch.setattr(runtime, "request", failed)
    with pytest.raises(ValueError, match="BROWSER_READ_FAILED"):
        browser.run(root, ["snapshot"])


def test_navigation_timeout_retains_tab_for_cleanup(root, monkeypatch):
    def cli(_root, command):
        if command[:3] == ["tab", "profile", "create"]:
            return {"profile": {"id": PROFILE}}
        if command[:2] == ["tab", "create"] and command[3] == "about:blank":
            return {"browserPageId": PAGE}
        raise ValueError("navigation timed out")

    monkeypatch.setattr(runtime, "cli", cli)
    data = {"worktree": str(root.parent)}
    runtime.save(root, data)
    with pytest.raises(ValueError, match="navigation timed out"):
        runtime.allocate(root, "https://example.com/login", data)
    assert runtime.metadata(root)["page"] == PAGE


def test_lost_creation_reply_closes_only_tabs_in_owned_profile(root, monkeypatch):
    data = runtime.metadata(root)
    del data["page"]
    runtime.save(root, data)
    calls = []
    alive = True

    def cli(_root, command):
        nonlocal alive
        calls.append(command)
        if command[:2] == ["tab", "list"]:
            assert command[2:4] == ["--worktree", "path:" + data["worktree"]]
            return {
                "tabs": ([{"profileId": PROFILE, "browserPageId": PAGE}] if alive else [])
                + [{"profileId": "other", "browserPageId": "not-ours"}]
            }
        if command[:2] == ["tab", "close"]:
            assert command[3] == PAGE
            alive = False
            return {"closed": True}
        assert not alive, "profile deletion must not orphan its tab"
        return {"deleted": True}

    monkeypatch.setattr(runtime, "cli", cli)
    assert runtime.close(root) == {"result": "BROWSER_CLOSED"}
    assert not alive
