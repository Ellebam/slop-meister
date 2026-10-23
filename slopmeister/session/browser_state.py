"""Private ownership records shared by the browser entry and its two browser routes."""

from contextlib import suppress
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from urllib.parse import urlsplit
from uuid import UUID

PREFIX = "slopmeister-browser-"
TEMP_ROOT = Path("/tmp").resolve()
MARKER = "credentials-used"
MAX_PREFERENCES_BYTES = 16 * 1024 * 1024


def identifier(value: str) -> str:
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("BROWSER_ID_REFUSED")
    return value


def save(root: Path, metadata: dict) -> None:
    target = root / "owner.json"
    target.write_text(json.dumps(metadata))
    target.chmod(0o600)


def metadata(root: Path) -> dict:
    try:
        data = private_json(root / "owner.json", 16384, "BROWSER_STATE_REFUSED")
    except OSError, ValueError:
        raise ValueError("BROWSER_STATE_REFUSED") from None
    if not isinstance(data, dict) or not isinstance(data.get("worktree"), str):
        raise ValueError("BROWSER_STATE_REFUSED")
    persistent = data.get("persistent", False)
    fields = data.get("credential_fields", [])
    if (
        type(persistent) is not bool
        or (persistent and data.get("browser") != "chrome")
        or not isinstance(fields, list)
        or not all(isinstance(value, str) for value in fields)
    ):
        raise ValueError("BROWSER_STATE_REFUSED")
    browser = data.get("browser", "orca")
    if browser not in {"orca", "chrome"}:
        raise ValueError("BROWSER_STATE_REFUSED")
    if browser == "orca":
        for name in ("profile", "page"):
            if data.get(name):
                identifier(data[name])
    if not Path(data["worktree"]).is_absolute():
        raise ValueError("BROWSER_STATE_REFUSED")
    return data


def owned(value: str) -> Path:
    root = Path(value)
    info = root.lstat()
    if (
        root.is_symlink()
        or root.parent != TEMP_ROOT
        or root.resolve() != root
        or not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o700
        or not root.name.startswith(PREFIX)
    ):
        raise ValueError("BROWSER_STATE_REFUSED")
    metadata(root)
    return root


def https_url(value: str) -> tuple[str, str]:
    url = urlsplit(value)
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.fragment
        or any(ord(c) < 33 for c in value)
    ):
        raise ValueError("BROWSER_URL_REFUSED: use the exact HTTPS login URL")
    return f"https://{url.netloc}", url.path or "/"


def credential_state(root: Path, create: bool = False) -> bool:
    marker = root / MARKER
    if create:
        with suppress(FileExistsError):
            descriptor = os.open(
                marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
            os.close(descriptor)
    try:
        info = marker.lstat()
    except FileNotFoundError:
        return False
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_nlink != 1
        or info.st_size
        or info.st_mode & 0o077
    ):
        raise ValueError("BROWSER_STATE_REFUSED")
    return True


SECONDS = 30
ENVIRONMENT = {
    "HOME",
    "USER",
    "LOGNAME",
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "DBUS_SESSION_BUS_ADDRESS",
    "XAUTHORITY",
    "XDG_RUNTIME_DIR",
}


def environment(root: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in ENVIRONMENT}
    return {
        **env,
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "LANG": "en_US.UTF-8",
        "TMPDIR": str(root),
    }


def execute(root: Path, argv: list[str], payload: dict | None = None) -> dict:
    env = environment(root)
    if payload is not None:
        env["ELECTRON_RUN_AS_NODE"] = "1"
    try:
        result = subprocess.run(
            argv,
            input=json.dumps(payload) if payload is not None else None,
            capture_output=True,
            text=True,
            cwd=root,
            env=env,
            timeout=SECONDS,
            umask=0o077,
        )
        data = json.loads(result.stdout)
    except OSError, ValueError, subprocess.TimeoutExpired:
        raise ValueError("BROWSER_OPERATION_FAILED: do not retry submission") from None
    if result.returncode or not isinstance(data, dict):
        raise ValueError("BROWSER_OPERATION_FAILED: do not retry submission")
    return data


def request(root: Path, engine: Path, payload: dict) -> dict:
    helper = Path(sys.argv[0]).resolve().with_name("input.cjs")
    if not helper.is_file():
        raise ValueError("BROWSER_HELPER_UNAVAILABLE")
    return execute(root, [str(engine), str(helper)], payload)


def workspace() -> Path:
    value = os.environ.get("SLOPMEISTER_SESSION_WORKSPACE", "")
    return (
        Path(value).resolve()
        if value and Path(value).is_absolute() and Path(value).is_dir()
        else Path.cwd().resolve()
    )


def data_home() -> Path:
    path = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError("BROWSER_DATA_DIRECTORY_REFUSED")
    return path / "slopmeister"


def private_directory(path: Path) -> None:
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError("BROWSER_PROFILE_REFUSED")
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
        or path.resolve() != path
    ):
        raise ValueError("BROWSER_PROFILE_REFUSED")


def private_json(path: Path, limit: int, reason: str):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
            or info.st_mode & 0o077
            or info.st_size > limit
        ):
            raise ValueError(reason)
        body = stream.read(limit + 1)
    if len(body) > limit:
        raise ValueError(reason)
    try:
        return json.loads(body)
    except RecursionError:
        raise ValueError(reason) from None


def profile_preferences(path: Path) -> dict:
    try:
        data = private_json(path, MAX_PREFERENCES_BYTES, "BROWSER_PROFILE_PREFERENCES_REFUSED")
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError, UnicodeError:
        raise ValueError("BROWSER_PROFILE_DAMAGED: preserve the profile") from None
    if not isinstance(data, dict):
        raise ValueError("BROWSER_PROFILE_DAMAGED: preserve the profile")
    return data


def clear_empty_window_area(preferences: dict) -> None:
    browser = preferences.get("browser")
    if not isinstance(browser, dict):
        return
    placement = browser.get("window_placement")
    if not isinstance(placement, dict):
        return
    area = [placement.get("work_area_" + key) for key in ("left", "top", "right", "bottom")]
    # A disconnected desktop can save an empty monitor area that Chrome cannot restore.
    if all(type(value) is int for value in area) and (area[2] <= area[0] or area[3] <= area[1]):
        del browser["window_placement"]
