"""A profile folder is owner-only and starts with the operator's settings but no account data."""

import json
import os

import pytest

from slopmeister.session import browser_state as state

PREFERENCES = {
    "extensions": {"settings": {"abc": {"state": 1}}},
    "bookmark_bar": {"show_on_all_tabs": True},
    "intl": {"selected_languages": "de-CH,en"},
    "account_info": [{"email": "someone@example.com"}],
    "signin": {"allowed": True},
    "google": {"services": {"signin": "x"}},
    "sync": {"has_setup_completed": True},
    "gaia_cookie": {"hash": "x"},
}


@pytest.fixture
def operator(profiles, monkeypatch, tmp_path):
    """An operator Chrome profile with settings, extensions and data that must stay behind."""
    source = tmp_path / "operator/Default"
    (source / "Extensions/abc/1.0").mkdir(parents=True)
    (source / "Extensions/abc/1.0/manifest.json").write_text("{}")
    (source / "Local Extension Settings/abc").mkdir(parents=True)
    (source / "Local Extension Settings/abc/000003.log").write_text("vault session")
    for name in ("Cookies", "Login Data", "Web Data", "History"):
        (source / name).write_text("private")
    (source / "Bookmarks").write_text('{"roots": {}}')
    for name in state.SEED_PREFERENCES:
        (source / name).write_text(json.dumps(PREFERENCES))
    monkeypatch.setattr(state.sys, "platform", "linux")
    monkeypatch.setattr(state, "OPERATOR_PROFILE", {"linux": source})
    return source


def test_a_new_profile_takes_settings_extensions_and_bookmarks_but_no_account_data(operator):
    folder = state.profile("work")
    copied = folder / "Default"
    found = sorted(p.relative_to(copied).as_posix() for p in copied.rglob("*"))
    assert found == [
        "Bookmarks", "Extensions", "Extensions/abc", "Extensions/abc/1.0",
        "Extensions/abc/1.0/manifest.json", "Preferences", "Secure Preferences",
    ]  # fmt: skip
    for name in state.SEED_PREFERENCES:
        assert set(json.loads((copied / name).read_text())) == {
            "extensions",
            "bookmark_bar",
            "intl",
        }
    for path in (state.PROFILES, folder, copied):
        assert path.stat().st_mode & 0o777 == 0o700


def test_an_existing_profile_keeps_its_own_settings(operator):
    folder = state.profile("work")
    (folder / "Default/Preferences").write_text('{"changed": true}')
    state.profile("work")
    assert json.loads((folder / "Default/Preferences").read_text()) == {"changed": True}


def test_a_host_without_an_operator_profile_starts_empty(profiles):
    assert list((state.profile("work") / "Default").iterdir()) == []


@pytest.mark.parametrize("change", ["group", "link", "file"])
def test_a_profile_another_user_could_reach_or_swap_is_refused(profiles, tmp_path, change):
    state.private(profiles)
    target = profiles / "work"
    if change == "group":
        target.mkdir(mode=0o750)
        target.chmod(0o750)
    elif change == "link":
        (tmp_path / "elsewhere").mkdir(mode=0o700)
        target.symlink_to(tmp_path / "elsewhere")
    else:
        target.write_text("")
    with pytest.raises(ValueError, match="BROWSER_PROFILE_REFUSED"):
        state.profile("work")
    assert not (tmp_path / "elsewhere/Default").exists()


def test_a_shared_parent_folder_is_refused(profiles):
    profiles.mkdir(mode=0o755)
    profiles.chmod(0o755)
    with pytest.raises(ValueError, match="BROWSER_PROFILE_REFUSED"):
        state.profile("work")


@pytest.mark.parametrize("code", [0, 1])
def test_a_mac_keeps_every_profile_out_of_time_machine(profiles, monkeypatch, code):
    seen = []
    monkeypatch.setattr(state.sys, "platform", "darwin")
    monkeypatch.setattr(
        state.subprocess,
        "run",
        lambda argv, **_: seen.append(argv) or state.subprocess.CompletedProcess(argv, code),
    )
    if code:
        with pytest.raises(ValueError, match="Time Machine exclusion failed"):
            state.profile("work")
        assert not (profiles / "work").exists()
    else:
        state.profile("work")
    assert seen == [["tmutil", "addexclusion", str(profiles)]]


def test_each_profile_has_its_own_owner_only_runtime_folder(profiles):
    first, second = state.runtime("one"), state.runtime("two")
    assert first != second and first.parent == second.parent == state.RUNTIME
    for folder in (state.RUNTIME, first, *(first / p for p in ("sockets", "daemon", "registry"))):
        assert folder.stat().st_mode & 0o777 == 0o700 and folder.stat().st_uid == os.getuid()
