"""Launch and retire only a task-owned instance of the machine's installed Chrome."""

from contextlib import suppress
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import time

from slopmeister.session import browser_state as state


def binaries() -> tuple[Path, Path]:
    if sys.platform == "darwin":
        choices = [
            p / "Google Chrome.app/Contents/MacOS/Google Chrome"
            for p in (Path("/Applications"), Path.home() / "Applications")
        ]
    elif sys.platform == "linux":
        choices = [
            Path(p)
            for p in (
                "/opt/google/chrome/google-chrome",
                "/usr/bin/google-chrome-stable",
                "/usr/bin/google-chrome",
            )
        ]
    else:
        choices = []
    chrome = next((p for p in choices if p.is_file() and os.access(p, os.X_OK)), None)
    node = shutil.which("node")
    if chrome is None or node is None:
        raise ValueError("BROWSER_PREREQUISITE: installed Chrome and Node with WebSocket required")
    engine = Path(node).resolve()
    cwd = Path.cwd().resolve()
    workspace = cwd not in {Path.home().resolve(), Path(cwd.anchor)} and engine.is_relative_to(cwd)
    if workspace or engine.is_relative_to(state.TEMP_ROOT):
        raise ValueError(
            "BROWSER_PREREQUISITE: use installed Node outside the workspace and temp root"
        )
    return chrome.resolve(), engine


def process(root: Path, data: dict) -> str | None:
    pid = data.get("pid")
    if type(pid) is not int or pid <= 1:
        raise ValueError("BROWSER_CHROME_OWNER_REFUSED")
    done = subprocess.run(
        ["/bin/ps", "-p", str(pid), "-o", "lstart=", "-o", "command="],
        capture_output=True,
        text=True,
        timeout=5,
        env=state.environment(root),
    )
    if done.returncode == 1 and not done.stdout and not done.stderr:
        return None
    if done.returncode:
        raise ValueError("BROWSER_CHROME_OWNER_REFUSED")
    marker = "--user-data-dir=" + str(root / "profile")
    matches = re.search(re.escape(marker) + r"(?:\s|$)", done.stdout) is not None
    born = " ".join(done.stdout.split()[:5])
    reused = bool(data.get("born")) and born != data["born"]
    if reused and not matches:
        return None
    if reused or not matches:
        raise ValueError("BROWSER_CHROME_OWNER_REFUSED")
    return born


def browser_endpoint(root: Path) -> str:
    profile = (root / "profile").lstat()
    if (
        not stat.S_ISDIR(profile.st_mode)
        or profile.st_uid != os.getuid()
        or profile.st_mode & 0o077
    ):
        raise ValueError("BROWSER_CHROME_ENDPOINT_REFUSED")
    target = root / "profile" / "DevToolsActivePort"
    info = target.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_size > 1024:
        raise ValueError("BROWSER_CHROME_ENDPOINT_REFUSED")
    lines = target.read_text().splitlines()
    if len(lines) != 2 or not lines[0].isdigit() or not 0 < int(lines[0]) < 65536:
        raise ValueError("BROWSER_CHROME_ENDPOINT_REFUSED")
    if not re.fullmatch(r"/devtools/browser/[A-Za-z0-9-]+", lines[1]):
        raise ValueError("BROWSER_CHROME_ENDPOINT_REFUSED")
    return "ws://127.0.0.1:" + lines[0] + lines[1]


def connection(root: Path, data: dict, action: str) -> tuple[Path, str]:
    if process(root, data) is None:
        raise ValueError("BROWSER_CHROME_EXITED")
    endpoint = browser_endpoint(root)
    if endpoint != data.get("endpoint"):
        raise ValueError("BROWSER_CHROME_ENDPOINT_REFUSED")
    if action not in {"create", "close"}:
        page = data.get("page", "")
        if not isinstance(page, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", page):
            raise ValueError("BROWSER_STATE_INCOMPLETE: close the saved state")
        endpoint = endpoint.split("/devtools/")[0] + "/devtools/page/" + page
    return binaries()[1], endpoint


def allocate(root: Path, url: str, data: dict) -> None:
    chrome, node = binaries()
    feature = state.execute(
        root,
        [str(node), "-e", 'console.log(JSON.stringify({websocket:typeof WebSocket==="function"}))'],
    )
    if feature.get("websocket") is not True:
        raise ValueError("BROWSER_PREREQUISITE: Node with WebSocket support required")
    child = launch(root, data, chrome)
    ready(root, data, child)
    data["page"] = state.request(root, node, {"endpoint": data["endpoint"], "action": "create"})[
        "targetId"
    ]
    state.save(root, data)
    engine, endpoint = connection(root, data, "open")
    state.request(root, engine, {"endpoint": endpoint, "action": "open", "url": url})


def launch(root: Path, data: dict, chrome: Path) -> subprocess.Popen:
    profile = root / "profile"
    profile.mkdir(mode=0o700)
    child = subprocess.Popen(
        [
            str(chrome),
            "--user-data-dir=" + str(profile),
            "--remote-debugging-port=0",
            "--remote-debugging-address=127.0.0.1",
            "--no-first-run",
            "--no-default-browser-check",
            "--no-startup-window",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=root,
        env=state.environment(profile),
        start_new_session=True,
        umask=0o077,
    )
    data["pid"] = child.pid
    state.save(root, data)
    data["born"] = process(root, data)
    state.save(root, data)
    return child


def ready(root: Path, data: dict, child: subprocess.Popen) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if child.poll() is not None:
            raise ValueError("BROWSER_CHROME_EXITED")
        try:
            data["endpoint"] = browser_endpoint(root)
            state.save(root, data)
            return
        except FileNotFoundError:
            time.sleep(0.1)
    raise ValueError("BROWSER_CHROME_START_TIMEOUT")


def close(root: Path, data: dict) -> dict:
    if data.get("pid") and process(root, data) is not None:
        if not data.get("endpoint"):
            data["endpoint"] = browser_endpoint(root)
            state.save(root, data)
        with suppress(ValueError):
            engine, endpoint = connection(root, data, "close")
            state.request(root, engine, {"endpoint": endpoint, "action": "close"})
        deadline = time.monotonic() + 5
        while process(root, data) is not None:
            if time.monotonic() >= deadline:
                raise ValueError("BROWSER_CLOSE_UNCONFIRMED")
            time.sleep(0.1)
    if any(p.name not in {"profile", "owner.json", state.MARKER} for p in root.iterdir()):
        raise ValueError("BROWSER_STATE_REFUSED")
    profile = root / "profile"
    if profile.is_symlink():
        raise ValueError("BROWSER_STATE_REFUSED")
    if profile.exists():
        shutil.rmtree(profile)
    if state.credential_state(root):
        (root / state.MARKER).unlink()
    (root / "owner.json").unlink()
    root.rmdir()
    return {"result": "BROWSER_CLOSED"}
