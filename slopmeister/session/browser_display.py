"""Detect a Linux desktop with no monitor, and run Chrome in a private X display instead."""

import os
from pathlib import Path
import shutil
from socket import AF_UNIX
from socket import socket as unix_socket
import subprocess
import sys
import time

from slopmeister.session.browser_state import SECONDS, environment, metadata, save

NO_MONITOR = (
    "BROWSER_NO_MONITOR: Chrome is closed and the desktop session has no monitor, so a Chrome "
    "started there opens no window. Start again with --private-display"
)
# Probes of the local desktop answer at once or not at all.
PROBE_SECONDS = 5
# The private display has no TCP listener, and its auth file lives in the owner-only state.
SCREEN = "-screen 0 1920x1080x24 -nolisten tcp"
# Systemd stops a display Chrome an interrupted session left behind, so it frees the profile lock.
DISPLAY_SECONDS = 1800
READY_SECONDS = 20
# Systemctl is-active answers 3 for an inactive unit and 4 for a removed one. Any other answer,
# such as 1 when the user bus is unreachable, confirms nothing.
STOPPED = (3, 4)


def probe(argv: list[str]) -> subprocess.CompletedProcess | None:
    found = shutil.which(argv[0])
    if found is None:
        return None
    env = {k: v for k, v in os.environ.items() if k in {"DISPLAY", "XAUTHORITY", "HOME"}}
    try:
        return subprocess.run(
            [found, *argv[1:]], capture_output=True, text=True, env=env, timeout=PROBE_SECONDS
        )
    except OSError, subprocess.TimeoutExpired:
        return None


def chrome_running() -> bool:
    done = probe(["pgrep", "-u", str(os.getuid()), "-x", "chrome"])
    return done is not None and done.returncode == 0


def monitorless() -> bool:
    """A closed Chrome on a Linux desktop with zero monitors, where a new Chrome hangs or traps."""
    if not sys.platform.startswith("linux") or chrome_running():
        return False
    done = probe(["xrandr", "--listmonitors"])
    return done is not None and done.returncode == 0 and done.stdout.startswith("Monitors: 0")


def check(private_display: bool) -> None:
    """Report the cause before an attach launches a Chrome that never opens a window."""
    if not private_display and monitorless():
        raise ValueError(NO_MONITOR)


def chrome_ready() -> bool:
    """Chrome answers on its profile socket, so a second Chrome start hands over to it."""
    with unix_socket(AF_UNIX) as probe_socket:
        # A full backlog would block the connect past the readiness deadline.
        probe_socket.settimeout(1)
        try:
            probe_socket.connect(str(Path.home() / ".config/google-chrome/SingletonSocket"))
        except OSError:
            return False
    return True


def start(root: Path) -> None:
    """Run Chrome in an X display only this user can reach, as a unit that close stops."""
    tools = [shutil.which(name) for name in ("systemd-run", "xvfb-run", "google-chrome-stable")]
    if None in tools:
        raise ValueError("BROWSER_PREREQUISITE: the private display needs systemd and xvfb-run")
    systemd_run, xvfb_run, chrome = tools
    (root / "display").mkdir(mode=0o700)
    # Recorded first, so close stops the unit whatever happens next.
    save(root, {**metadata(root), "display": True})
    unit = [
        systemd_run, "--user", "--collect", "--quiet", "--unit=" + root.name,
        f"--property=RuntimeMaxSec={DISPLAY_SECONDS}",
        "/usr/bin/env", "-u", "WAYLAND_DISPLAY", xvfb_run, "-a",
        "-f", str(root / "display/xauth"), "-s", SCREEN, chrome, "--ozone-platform=x11",
    ]  # fmt: skip
    try:
        started = subprocess.run(unit, capture_output=True, env=environment(root), timeout=SECONDS)
    except OSError, subprocess.TimeoutExpired:
        started = None
    ready = started is not None and not started.returncode
    deadline = time.monotonic() + READY_SECONDS
    while ready and not chrome_ready():
        time.sleep(0.25)
        ready = time.monotonic() < deadline
    if not ready:
        raise ValueError(
            f"BROWSER_DISPLAY_FAILED: Chrome did not start in the private display; "
            f"retain state {root} for cleanup"
        )


def stop(root: Path, data: dict) -> None:
    if not data.get("display"):
        return
    options = {"capture_output": True, "env": environment(root), "timeout": SECONDS}
    try:
        subprocess.run(["systemctl", "--user", "stop", root.name], **options)
        active = subprocess.run(
            ["systemctl", "--user", "is-active", "--quiet", root.name], **options
        )
    except OSError, subprocess.TimeoutExpired:
        raise ValueError("BROWSER_CLOSE_UNCONFIRMED") from None
    if active.returncode not in STOPPED:
        raise ValueError("BROWSER_CLOSE_UNCONFIRMED")
