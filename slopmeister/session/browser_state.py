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


def identifier(value: str) -> str:
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("BROWSER_ID_REFUSED")
    return value


def save(root: Path, metadata: dict) -> None:
    target = root / "owner.json"
    target.write_text(json.dumps(metadata))
    target.chmod(0o600)


def metadata(root: Path) -> dict:
    target = root / "owner.json"
    info = target.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_nlink != 1
        or info.st_mode & 0o077
        or info.st_size > 16384
    ):
        raise ValueError("BROWSER_STATE_REFUSED")
    data = json.loads(target.read_text())
    if not isinstance(data, dict) or not isinstance(data.get("worktree"), str):
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
