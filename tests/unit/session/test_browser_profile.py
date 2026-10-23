"""Persistent authentication is opt-in and remains bound to the dedicated owned profile."""

import pytest

from slopmeister.session import browser_login as browser
from slopmeister.session import browser_runtime as runtime


def test_persistence_requires_an_explicit_chrome_flag():
    ordinary = browser.arguments(["start", "https://example.com/", "--browser", "chrome"])
    assert ordinary.persistent is False
    selected = browser.arguments(
        ["start", "https://example.com/", "--browser", "chrome", "--persistent"]
    )
    assert selected.persistent is True


def test_persistence_on_orca_refuses_before_creating_state(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "TEMP_ROOT", tmp_path)

    def forbidden():
        pytest.fail("Orca was inspected before refusing persistence")

    monkeypatch.setattr(runtime, "binaries", forbidden)
    with pytest.raises(ValueError, match="PERSISTENCE_REQUIRES_CHROME"):
        runtime.start("https://example.com/", "orca", persistent=True)
    assert not list(tmp_path.iterdir())


@pytest.fixture
def persistent(tmp_path, monkeypatch):
    from pathlib import Path
    import subprocess

    from slopmeister.session import browser_chrome as chrome
    from slopmeister.session import browser_profile as profiles
    from slopmeister.session import browser_state as state

    temporary = tmp_path / "states"
    temporary.mkdir()
    monkeypatch.setattr(runtime, "TEMP_ROOT", temporary)
    monkeypatch.setattr(state, "TEMP_ROOT", temporary)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("SLOPMEISTER_SESSION_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(
        profiles.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "", "")
    )

    def allocate(root, url, data):
        profiles.prepare(root, data)
        data["page"] = "owned-page"
        state.save(root, data)

    monkeypatch.setattr(chrome, "allocate", allocate)
    created = runtime.start("https://example.com/", "chrome", persistent=True)
    return Path(created["state"]), profiles.location(), profiles, state


def test_close_preserves_authentication_until_explicit_profile_clear(persistent):
    root, profile, profiles, state = persistent
    cookie = profile / "synthetic-cookie"
    cookie.write_text("retained authentication fixture")
    assert profile.stat().st_mode & 0o777 == 0o700
    assert state.metadata(root)["profile_path"] == str(profile)
    assert runtime.close(root) == {"result": "BROWSER_CLOSED"}
    assert not root.exists() and cookie.read_text() == "retained authentication fixture"
    assert profiles.clear() == {"result": "BROWSER_PROFILE_CLEARED"}
    assert not profile.exists()


def test_active_or_uncertain_profile_cannot_be_cleared(persistent):
    root, profile, profiles, _ = persistent
    with pytest.raises(ValueError, match="PROFILE_BUSY"):
        profiles.clear()
    assert profile.is_dir()
    runtime.close(root)
    (profile / "SingletonLock").symlink_to("uncertain-owner")
    with pytest.raises(ValueError, match="ownership is live or uncertain"):
        profiles.clear()
    assert (profile / "SingletonLock").is_symlink()


@pytest.mark.parametrize("damage", ["state-path", "owner-inode", "permissions"])
def test_changed_profile_ownership_refuses_cleanup(persistent, damage):
    import json

    root, profile, profiles, state = persistent
    outside = root.parent / "ordinary-profile"
    outside.mkdir()
    (outside / "keep").write_text("unrelated")
    if damage == "state-path":
        state.save(root, {**state.metadata(root), "profile_path": str(outside)})
    elif damage == "owner-inode":
        target = profile.parent / profiles.OWNER
        record = json.loads(target.read_text())
        target.write_text(json.dumps({**record, "inode": record["inode"] + 1}))
    else:
        profile.chmod(0o755)
    with pytest.raises(ValueError, match="PROFILE_.*REFUSED"):
        runtime.close(root)
    assert root.is_dir() and profile.is_dir() and (outside / "keep").read_text() == "unrelated"


def test_existing_unowned_profile_is_never_adopted(persistent):
    root, profile, profiles, _ = persistent
    runtime.close(root)
    (profile.parent / profiles.OWNER).unlink()
    sentinel = profile / "operator-content"
    sentinel.write_text("keep")
    with pytest.raises(ValueError, match="PROFILE_OWNER_REFUSED"):
        runtime.start("https://example.com/", "chrome", persistent=True)
    assert sentinel.read_text() == "keep"


def test_malformed_preferences_keep_profile_and_recoverable_state(persistent):
    root, profile, _, _ = persistent
    runtime.close(root)
    preferences = profile / "Default/Preferences"
    preferences.write_text("{")
    with pytest.raises(ValueError, match="PROFILE_DAMAGED"):
        runtime.start("https://example.com/", "chrome", persistent=True)
    assert preferences.read_text() == "{"
    retained = next(root.parent.glob("slopmeister-browser-*"))
    runtime.close(retained)
    assert preferences.read_text() == "{"


def test_public_xdg_choice_does_not_redirect_an_existing_state(persistent, monkeypatch):
    root, profile, _, _ = persistent
    monkeypatch.setenv("XDG_DATA_HOME", str(root.parent / "different-data"))
    assert runtime.close(root) == {"result": "BROWSER_CLOSED"}
    assert profile.is_dir()


@pytest.mark.parametrize("busy", [False, True])
def test_lost_state_can_recover_only_after_browser_exit(persistent, monkeypatch, busy):
    from pathlib import Path
    import shutil
    import subprocess

    root, profile, profiles, _ = persistent
    cookie = profile / "synthetic-cookie"
    cookie.write_text("retained authentication fixture")
    shutil.rmtree(root)
    processes = f"chrome --user-data-dir={profile}\n" if busy else ""
    monkeypatch.setattr(
        profiles.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, processes, ""),
    )
    if busy:
        with pytest.raises(ValueError, match="PROFILE_BUSY"):
            runtime.start("https://example.com/", "chrome", persistent=True)
    else:
        created = runtime.start("https://example.com/", "chrome", persistent=True)
        assert runtime.close(Path(created["state"])) == {"result": "BROWSER_CLOSED"}
    assert cookie.read_text() == "retained authentication fixture"
    if not busy:
        assert profiles.clear() == {"result": "BROWSER_PROFILE_CLEARED"}
