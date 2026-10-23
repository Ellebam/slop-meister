"""Own the optional persistent Chrome profile and serialize its startup and removal."""

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile

from slopmeister.session import browser_state as state

OWNER = "profile.json"
LOCKS = ("SingletonLock", "SingletonSocket", "SingletonCookie")


def location() -> Path:
    return state.data_home() / "browser/profile"


@contextmanager
def locked(profile: Path):
    parent = profile.parent
    if parent.resolve() != parent:
        raise ValueError("BROWSER_PROFILE_REFUSED")
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    state.private_directory(parent)
    fd = os.open(
        parent / "startup.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600
    )
    with os.fdopen(fd, "r+") as stream:
        info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
            or info.st_mode & 0o077
        ):
            raise ValueError("BROWSER_PROFILE_LOCK_REFUSED")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("BROWSER_PROFILE_BUSY: wait for the active browser job") from None
        yield


def _save(profile: Path, record: dict) -> None:
    with tempfile.NamedTemporaryFile(mode="w", dir=profile.parent, delete=False) as stream:
        json.dump(record, stream)
    os.replace(stream.name, profile.parent / OWNER)


def _owner(profile: Path) -> dict:
    if not profile.is_absolute() or profile.resolve() != profile:
        raise ValueError("BROWSER_PROFILE_REFUSED")
    try:
        record = state.private_json(profile.parent / OWNER, 16384, "BROWSER_PROFILE_OWNER_REFUSED")
    except OSError, json.JSONDecodeError, UnicodeError:
        raise ValueError("BROWSER_PROFILE_OWNER_REFUSED") from None
    info = profile.lstat()
    valid = isinstance(record, dict) and record.get("path") == str(profile)
    valid = valid and (record.get("device"), record.get("inode")) == (info.st_dev, info.st_ino)
    valid = valid and (record.get("active") is None or isinstance(record.get("active"), str))
    if (
        not valid
        or not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise ValueError("BROWSER_PROFILE_OWNER_REFUSED")
    return record


def refuse_busy(profile: Path) -> None:
    result = subprocess.run(
        ["/bin/ps", "-u", str(os.getuid()), "-o", "args="],
        capture_output=True,
        text=True,
        timeout=5,
        env=state.environment(profile.parent),
    )
    if result.returncode:
        raise ValueError("BROWSER_PROFILE_PROCESS_CHECK_FAILED")
    marker = re.escape("--user-data-dir=" + str(profile)) + r"(?:\s|$)"
    if re.search(marker, result.stdout):
        raise ValueError("BROWSER_PROFILE_BUSY: wait for the active browser job")


def bind(root: Path, data: dict) -> None:
    profile = location()
    refuse_busy(profile)
    if os.path.lexists(profile) or os.path.lexists(profile.parent / OWNER):
        record = _owner(profile)
        if record["active"] is not None:
            raise ValueError("BROWSER_PROFILE_BUSY: close the saved browser state first")
    else:
        state.private_directory(profile)
        info = profile.lstat()
        record = {"path": str(profile), "device": info.st_dev, "inode": info.st_ino}
    record["active"] = str(root)
    _save(profile, record)
    data.update(persistent=True, profile_path=str(profile))
    state.save(root, data)


def path(root: Path, data: dict) -> Path:
    if not data.get("persistent"):
        return root / "profile"
    value = data.get("profile_path")
    if not isinstance(value, str):
        raise ValueError("BROWSER_PROFILE_OWNER_REFUSED")
    profile = Path(value)
    record = _owner(profile)
    if record["active"] not in (None, str(root)):
        raise ValueError("BROWSER_PROFILE_OWNER_REFUSED")
    return profile


def release(root: Path, data: dict) -> None:
    profile = path(root, data)
    record = _owner(profile)
    record["active"] = None
    _save(profile, record)


def prepare(root: Path, data: dict) -> Path:
    profile = path(root, data)
    state.private_directory(profile)
    state.private_directory(profile / "Default")
    state.private_directory(root / "downloads")
    target = profile / "Default/Preferences"
    preferences = state.profile_preferences(target)
    state.clear_empty_window_area(preferences)
    settings = {
        "download": {"default_directory": str(root / "downloads"), "prompt_for_download": False},
        "savefile": {"default_directory": str(root / "downloads")},
        "autofill": {"profile_enabled": False, "credit_card_enabled": False},
        "session": {"restore_on_startup": 5},
    }
    for key, values in settings.items():
        if not isinstance(preferences.setdefault(key, {}), dict):
            raise ValueError("BROWSER_PROFILE_DAMAGED: preserve the profile")
        preferences[key].update(values)
    preferences["credentials_enable_service"] = False
    with tempfile.NamedTemporaryFile(mode="w", dir=target.parent, delete=False) as stream:
        json.dump(preferences, stream)
    os.replace(stream.name, target)
    return profile


def clear() -> dict:
    profile = location()
    with locked(profile):
        if not os.path.lexists(profile) and not os.path.lexists(profile.parent / OWNER):
            return {"result": "BROWSER_PROFILE_ABSENT"}
        record = _owner(profile)
        refuse_busy(profile)
        if record["active"] is not None or any(os.path.lexists(profile / name) for name in LOCKS):
            raise ValueError("BROWSER_PROFILE_BUSY: browser ownership is live or uncertain")
        shutil.rmtree(profile)
        (profile.parent / OWNER).unlink()
    return {"result": "BROWSER_PROFILE_CLEARED"}
