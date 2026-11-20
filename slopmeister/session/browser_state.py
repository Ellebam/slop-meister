"""Private ownership records, profile folders and their runtime folders for the browser entry."""

from collections.abc import Iterator
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
from urllib.parse import urlsplit

PREFIX = "slopmeister-browser-"
TEMP_ROOT = Path("/tmp").resolve()
# A profile holds login cookies, so it lives in the user's state folder, never in Git or the vault.
PROFILES = Path.home() / ".local/state/slopmeister/browsers"
# A plain name keeps every profile folder directly inside PROFILES, so no name can traverse.
PROFILE_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
# Sockets have a short path limit, so each profile's sockets, lock and display live here.
RUNTIME = TEMP_ROOT / f"sm-browser-{os.getuid()}"
OPERATOR_PROFILE = {
    "linux": Path.home() / ".config/google-chrome/Default",
    "darwin": Path.home() / "Library/Application Support/Google/Chrome/Default",
}
# A new profile takes the operator's extensions, bookmarks and settings. Account, sign-in, sync and
# Google keys stay behind, and so do cookies, passwords and the stored data of extensions.
SEED_KEYS = frozenset(
    {"extensions", "protection", "browser", "bookmark_bar", "default_search_provider",
     "default_search_provider_data", "intl", "spellcheck"}
)  # fmt: skip
SEED_PREFERENCES = ("Preferences", "Secure Preferences")
# A page address can carry an account name or a flow value in its query or fragment, and no page
# command needs them. A query can hold any punctuation, so a run ends only at a space, quote or
# angle bracket. Each run is cut once, so the scan stays linear.
ADDRESS_RUN = re.compile(r"[^\s\"'<>]+")
ADDRESS_TAIL = re.compile(r"[?#]")
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


def private(folder: Path) -> Path:
    """An owner-only folder, created when missing and refused when another user could swap it."""
    refused = ValueError(f"BROWSER_PROFILE_REFUSED: {folder} must be an owner-only folder")
    try:
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    except FileExistsError:
        raise refused from None
    info = folder.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise refused
    return folder


def profile_name(value: str) -> str:
    if not PROFILE_NAME.fullmatch(value):
        raise ValueError("BROWSER_PROFILE_REFUSED: use lowercase letters, digits and dashes")
    return value


def profile(name: str) -> Path:
    """The named profile folder. A new one starts as a filtered copy of the operator's profile."""
    folder = PROFILES / profile_name(name)
    fresh = not folder.exists() and not folder.is_symlink()
    private(PROFILES)
    if sys.platform == "darwin":
        # Time Machine copies the home folder off this Mac, and the profiles hold login cookies.
        excluded = subprocess.run(["tmutil", "addexclusion", str(PROFILES)], capture_output=True)
        if excluded.returncode:
            raise ValueError("BROWSER_PROFILE_REFUSED: Time Machine exclusion failed")
    private(folder)
    if fresh:
        seed(OPERATOR_PROFILE.get(sys.platform, Path("/nonexistent")), folder / "Default")
    return folder


def seed(source: Path, target: Path) -> None:
    target.mkdir(mode=0o700)
    if not source.is_dir():
        return
    if (source / "Bookmarks").is_file():
        shutil.copyfile(source / "Bookmarks", target / "Bookmarks")
    if (source / "Extensions").is_dir():
        shutil.copytree(source / "Extensions", target / "Extensions", symlinks=True)
    for name in SEED_PREFERENCES:
        try:
            data = json.loads((source / name).read_text())
        except OSError, ValueError:
            continue
        if isinstance(data, dict):
            kept = {key: value for key, value in data.items() if key in SEED_KEYS}
            (target / name).write_text(json.dumps(kept))


def runtime(name: str) -> Path:
    """The profile's owner-only runtime folder for its sockets, registries, lock and display."""
    folder = private(private(RUNTIME) / profile_name(name))
    for part in ("sockets", "daemon", "registry", "keeper"):
        private(folder / part)
    return folder


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


def node() -> Path:
    found = shutil.which("node")
    if found is None:
        raise ValueError("BROWSER_PREREQUISITE: Node required")
    engine = Path(found).resolve()
    cwd = workspace()
    inside = cwd not in {Path.home().resolve(), Path(cwd.anchor)} and engine.is_relative_to(cwd)
    if inside or engine.is_relative_to(TEMP_ROOT):
        raise ValueError(
            "BROWSER_PREREQUISITE: use installed Node outside the workspace and temp root"
        )
    return engine


def cut(run: re.Match) -> str:
    # A snapshot shows a link's own address, which can be relative to the page. Any tail that
    # holds a parameter is cut, and so is any tail of an absolute or root-relative address.
    token = run.group()
    tail = ADDRESS_TAIL.search(token)
    if tail is not None and "=" not in token[tail.start() :]:
        start = 0 if token.startswith("/") else token.find("://")
        tail = ADDRESS_TAIL.search(token, start) if start >= 0 else None
    if tail is None:
        return token
    # The brackets that close a Markdown link stay, so the line keeps its shape.
    closing = token[len(token.rstrip(")]")) :]
    return token[: tail.start()] + "?hidden" + closing


def hide(text: str) -> str:
    return ADDRESS_RUN.sub(cut, text)


@contextmanager
def locked(runtime: Path) -> Iterator[None]:
    """One start or close of a profile at a time, so a keeper is never closed under a new state."""
    descriptor = os.open(runtime / "lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def configuration(config: Path, data: dict) -> None:
    fd = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    with os.fdopen(fd, "w") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
            raise ValueError("BROWSER_PAGE_CONFIG_REFUSED")
        stream.truncate(0)
        stream.write(json.dumps(data))
