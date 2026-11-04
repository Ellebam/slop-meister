"""Private ownership records shared by the browser entry and its Chrome connection."""

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from urllib.parse import urlsplit

PREFIX = "slopmeister-browser-"
TEMP_ROOT = Path("/tmp").resolve()
WORKSPACE = "SLOPMEISTER_SESSION_WORKSPACE"
# A program started from the checkout has no skill entry beside it.
CHECKOUT_HELPER = Path(__file__).resolve().parents[2] / "src/skills/browser-login/scripts/input.cjs"


def workspace() -> Path:
    """The launched session's workspace, so a command run from another directory still owns it."""
    value = os.environ.get(WORKSPACE, "")
    if value and Path(value).is_absolute() and Path(value).is_dir():
        return Path(value).resolve()
    return Path.cwd().resolve()


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


# Long enough for a login of several steps, each waiting for its next page.
SECONDS = 60
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
    try:
        result = subprocess.run(
            argv,
            input=json.dumps(payload) if payload is not None else None,
            capture_output=True,
            text=True,
            cwd=root,
            env=environment(root),
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
        helper = CHECKOUT_HELPER
    if not helper.is_file():
        raise ValueError("BROWSER_HELPER_UNAVAILABLE")
    return execute(root, [str(engine), str(helper)], payload)


def data_home() -> Path:
    path = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError("BROWSER_DATA_DIRECTORY_REFUSED")
    return path / "slopmeister"


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


def private_directory(path: Path) -> None:
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError("BROWSER_STATE_REFUSED")
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
        or path.resolve() != path
    ):
        raise ValueError("BROWSER_STATE_REFUSED")
