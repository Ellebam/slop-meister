"""Detect a Linux desktop with no monitor, and give a profile's Chrome a private X display."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from slopmeister.session.browser_state import SECONDS, environment

NO_MONITOR = (
    "BROWSER_NO_MONITOR: the desktop session has no monitor, so a Chrome started there opens no "
    "window. Start again with --private-display"
)
# Probes of the local desktop answer at once or not at all.
PROBE_SECONDS = 5
# The private display has no TCP listener, and its auth file lives in the owner-only state.
SCREEN = "-screen 0 1920x1080x24 -nolisten tcp"
# Systemd stops a display an interrupted session left behind, which ends its Chrome and frees the
# profile lock.
DISPLAY_SECONDS = 1800
READY_SECONDS = 20
# Systemctl is-active answers 3 for an inactive unit and 4 for a removed one. Any other answer,
# such as 1 when the user bus is unreachable, confirms nothing.
STOPPED = (3, 4)
X_SOCKETS = Path("/tmp/.X11-unix")


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


def monitorless() -> bool:
    """A Linux desktop with zero monitors, where a new Chrome hangs or traps."""
    if not sys.platform.startswith("linux"):
        return False
    done = probe(["xrandr", "--listmonitors"])
    return done is not None and done.returncode == 0 and done.stdout.startswith("Monitors: 0")


def check(private_display: bool) -> None:
    """Report the cause before the page tool launches a Chrome that never opens a window."""
    if not private_display and monitorless():
        raise ValueError(NO_MONITOR)


def unit(runtime: Path) -> str:
    return f"slopmeister-browser-{runtime.name}"


def start(runtime: Path) -> dict[str, str]:
    """An X display only this user can reach, as a unit that the last close stops."""
    tools = [shutil.which(name) for name in ("systemd-run", "xvfb-run")]
    if None in tools:
        raise ValueError("BROWSER_PREREQUISITE: the private display needs systemd and xvfb-run")
    systemd_run, xvfb_run = tools
    folder = runtime / "display"
    folder.mkdir(mode=0o700)
    number = folder / "number"
    command = [
        systemd_run, "--user", "--collect", "--quiet", "--unit=" + unit(runtime),
        f"--property=RuntimeMaxSec={DISPLAY_SECONDS}",
        "/usr/bin/env", "-u", "WAYLAND_DISPLAY", xvfb_run, "-a",
        "-f", str(folder / "xauth"), "-s", SCREEN,
        "/bin/sh", "-c", 'echo "$DISPLAY" > "$0" && exec sleep infinity', str(number),
    ]  # fmt: skip
    try:
        started = subprocess.run(
            command, capture_output=True, env=environment(runtime), timeout=SECONDS
        )
    except OSError, subprocess.TimeoutExpired:
        started = None
    deadline = time.monotonic() + READY_SECONDS
    while started is not None and not started.returncode and time.monotonic() < deadline:
        value = number.read_text().strip() if number.is_file() else ""
        if value.startswith(":") and (X_SOCKETS / f"X{value[1:]}").exists():
            return {"DISPLAY": value, "XAUTHORITY": str(folder / "xauth")}
        time.sleep(0.25)
    stop(runtime)
    raise ValueError("BROWSER_DISPLAY_FAILED: the private display did not start")


def stop(runtime: Path) -> None:
    """Stop the profile's display, which ends a Chrome still drawing in it."""
    if not (runtime / "display").exists():
        return
    options = {"capture_output": True, "env": environment(runtime), "timeout": SECONDS}
    try:
        subprocess.run(["systemctl", "--user", "stop", unit(runtime)], **options)
        active = subprocess.run(
            ["systemctl", "--user", "is-active", "--quiet", unit(runtime)], **options
        )
    except OSError, subprocess.TimeoutExpired:
        raise ValueError("BROWSER_CLOSE_UNCONFIRMED") from None
    if active.returncode not in STOPPED:
        raise ValueError("BROWSER_CLOSE_UNCONFIRMED")
    shutil.rmtree(runtime / "display")
