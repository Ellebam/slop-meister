"""Launch and confirm an interactive OpenCode worker from its native session store."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

from slopmeister.launch import model
from slopmeister.launch.model import BROKER_MARK, Delivery, Launch, Stop, shq
from slopmeister.opencode import native

SESSION_POLL = 60


def line(launch: Launch) -> str:
    """The provider key comes from the tab's login shell, never from this command file."""
    # The granted roots, the vault and for Slopmeister its checkout, reach OpenCode as the
    # only outside directories it may use without asking, as Claude and Codex receive them.
    granted = launch.grants[1::2]
    rules = {**native.permission(), "external_directory": {f"{g}/*": "allow" for g in granted}}
    config = json.dumps({"permission": rules}, separators=(",", ":"))
    selected = f" -m {shq(launch.model)}" if launch.model_set else ""
    wt = shq(str(launch.wt))
    kickoff = shq(str(launch.kickoff_file))
    return (
        f"cd {wt} && env OPENCODE_DISABLE_CLAUDE_CODE=1 {BROKER_MARK} "
        f"OPENCODE_CONFIG_CONTENT={shq(config)} "
        f'{shq(launch.opencode_bin)} {wt}{selected} --prompt "$(cat {kickoff})"'
    )


def pids(launch: Launch) -> list[int]:
    found = subprocess.run(["pgrep", "-x", "opencode"], capture_output=True, text=True)
    inside = []
    for pid in (int(value) for value in found.stdout.split()):
        listed = subprocess.run(
            ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"], capture_output=True, text=True
        )
        paths = [row[1:] for row in listed.stdout.splitlines() if row.startswith("n")]
        if paths == [os.path.realpath(launch.wt)]:
            inside.append(pid)
    return inside


def _store(launch: Launch) -> native.Store:
    return native.Store(launch.opencode_bin, launch.wt, os.environ)


def evidence_path(launch: Launch) -> Path:
    return launch.state_dir / f"{launch.name}.opencode.jsonl"


def _write(path: Path, found: dict, prompt: str) -> None:
    """Claude-shaped rows, so the model report and the claim check read them unchanged."""
    ids = {"sessionId": found["session"], "cwd": found["directory"]}
    rows = [{"type": "user", **ids, "message": {"role": "user", "content": prompt}}]
    rows += [{"type": "assistant", **ids, "message": {"model": name}} for name in found["models"]]
    # The rows carry the kickoff, so they get the kickoff file's own 0600 mode.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write("".join(json.dumps(row) + "\n" for row in rows))


def confirm(launch: Launch, delivery: Delivery, marker: float) -> None:
    since = int(marker * 1000)
    for _ in range(SESSION_POLL):
        try:
            _, found = native.find(_store(launch), launch.kickoff, since)
        except native.Blocked as blocked:
            last = str(blocked)
            model.pause(1)
            continue
        _write(evidence_path(launch), found, launch.kickoff)
        delivery.evidence, delivery.session = str(evidence_path(launch)), found["session"]
        return
    raise Stop(
        1,
        f"plot-session: process {delivery.pid} is live in {launch.wt} but its kickoff is not "
        f"proven after {SESSION_POLL}s: {last}\nNever relaunch over the live process, inspect "
        f"it with: cd {shq(str(launch.wt))} && opencode session list",
    )


def refresh(launch: Launch, delivery: Delivery) -> None:
    """The model appears once the worker answers, so the evidence is exported again."""
    try:
        _, found = native.find(_store(launch), launch.kickoff, 0)
    except native.Blocked:
        return
    if found["session"] == delivery.session:
        _write(Path(delivery.evidence), found, launch.kickoff)
