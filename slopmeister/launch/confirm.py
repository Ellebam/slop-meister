"""Confirm delivery from the process, its directory and the kickoff in the session record."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

from slopmeister.launch import model
from slopmeister.launch.model import NC, RED, Delivery, Launch, Stop
from slopmeister.opencode import launch as opencode

PROCESS_POLL = 20
REGISTRATION_POLL = 15
TRANSCRIPT_POLL = 60
ROLLOUT_POLL = 120


def _lines(*messages: str) -> Stop:
    first, *rest = messages
    return Stop(1, "\n".join([f"{RED}plot-session: {first}{NC}", *rest]))


def fallback(launch: Launch, message: str) -> Stop:
    """No runnable line, a terminal that is only slow to start would run the session twice."""
    return _lines(
        message,
        f"Look at {launch.name}'s terminal before anything else, it may still be starting. Then "
        "retry the same name with --redispatch, or have the workstation skill diagnose the launch.",
    )


def inspect(message: str, hint: str) -> Stop:
    """For states where a session may already be live, relaunch advice would double it."""
    return _lines(message, f"A session may already be live, inspect before anything else: {hint}")


def undelivered(launch: Launch, record: str, seconds: int) -> Stop:
    lines = [
        "kickoff undelivered, no user message equal to the kickoff appeared in "
        f"{record} within {seconds}s",
        "The process is live in its directory. A folder trust prompt means the launcher's "
        "pre-trust entry did not take, so look at the tab first. Never relaunch over the live "
        f"process. The kickoff is at {launch.kickoff_file}",
    ]
    if launch.tool == "codex":
        lines.append("For Codex, also check the tab for a repository hooks consent prompt.")
    return _lines(*lines)


def _pgrep(pattern: str) -> list[int]:
    found = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
    return [int(pid) for pid in found.stdout.split()]


def _pids(launch: Launch) -> list[int]:
    """Pids only, command lines carry whole kickoffs; a standalone Codex is new and carries -C."""
    if launch.tool == "claude":
        return _pgrep(f"remote-control={launch.name}($| )")
    if launch.tool == "opencode":
        return opencode.pids(launch)
    found = []
    for pid in _pgrep("codex --no-daemon"):
        if pid in launch.codex_baseline:
            continue
        args = subprocess.run(["ps", "-o", "args=", "-p", str(pid)], capture_output=True, text=True)
        text = args.stdout.rstrip("\n")
        if f"-C {launch.wt} " in text or text.endswith(f"-C {launch.wt}"):
            found.append(pid)
    return found


def _hint(launch: Launch) -> str:
    if launch.tool == "claude":
        return f"pgrep -f 'remote-control={launch.name}'"
    if launch.tool == "opencode":
        return "pgrep -lx opencode"
    return "pgrep -f 'codex --no-daemon'"


def _one_pid(launch: Launch) -> int:
    polls = PROCESS_POLL
    for _ in range(polls):
        pids = _pids(launch)
        if len(pids) > 1:
            message = f"more than one new {launch.tool} process sits in {launch.wt}"
            raise inspect(message + ", refusing to confirm either", _hint(launch))
        if pids:
            return pids[0]
        model.pause(1)
    message = f"no {launch.tool} process for {launch.name} appeared within {polls}s"
    raise fallback(launch, message + ", the launch did not take")


def process(launch: Launch) -> Delivery:
    """lsof fails when the process exits meanwhile, and that race gets its own diagnosis."""
    pid = _one_pid(launch)
    listed = subprocess.run(
        ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"], capture_output=True, text=True
    )
    cwd = "".join(
        line[1:] + "\n" for line in listed.stdout.splitlines() if line.startswith("n")
    ).rstrip("\n")
    if cwd != os.path.realpath(launch.wt):
        if subprocess.run(["ps", "-p", str(pid)], capture_output=True).returncode:
            raise fallback(
                launch,
                f"process {pid} exited during confirmation, the launch did not survive startup",
            )
        message = f"process {pid} is alive but its cwd is '{cwd}', not the prepared directory"
        raise inspect(message, _hint(launch))
    return Delivery(pid)


def _registered(launch: Launch, pid: int) -> bool:
    env = dict(os.environ)
    if launch.claude_root:
        env["CLAUDE_CONFIG_DIR"] = str(launch.claude_root)
    else:
        env.pop("CLAUDE_CONFIG_DIR", None)
    listed = subprocess.run(
        [launch.claude_bin, "agents", "--json"],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )
    try:
        return any(agent.get("pid") == pid for agent in json.loads(listed.stdout))
    except ValueError, AttributeError, TypeError:
        return False


def _text(content: object, kind: str) -> str | None:
    if isinstance(content, str) and kind == "text":
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == kind
        )
    return None


def _records(path: Path):
    try:
        lines = path.read_text(encoding="utf-8", errors="surrogateescape").splitlines()
    except OSError:
        return
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            yield record


def _claude_record(path: Path, kickoff: str) -> bool:
    return any(
        record.get("type") == "user"
        and _text((record.get("message") or {}).get("content"), "text") == kickoff
        for record in _records(path)
    )


def claude(launch: Launch, delivery: Delivery) -> None:
    for _ in range(REGISTRATION_POLL):
        if _registered(launch, delivery.pid):
            break
        model.pause(2)
    else:
        raise Stop(
            1,
            f"{RED}plot-session: process {delivery.pid} is live in its directory but not yet "
            f"registered in 'claude agents' after ~45s.{NC}\nRegistration lag is possible. If the "
            "tab shows a folder trust prompt, the launcher's pre-trust entry did not take, so "
            "inspect it there. Never relaunch over the live process.",
        )
    for _ in range(TRANSCRIPT_POLL):
        found = (
            next(launch.claude_projects.rglob(f"{launch.session_id}.jsonl"), None)
            if launch.claude_projects.is_dir()
            else None
        )
        if found and _claude_record(found, launch.kickoff):
            delivery.evidence, delivery.session = str(found), launch.session_id
            return
        model.pause(1)
    record = f"the transcript {launch.claude_projects}/*/{launch.session_id}.jsonl"
    raise undelivered(launch, record, TRANSCRIPT_POLL)


def _codex_record(path: Path, launch: Launch) -> bool:
    records = list(_records(path))
    meta = records[:1] and records[0]
    if not meta or meta.get("type") != "session_meta":
        return False
    cwd = (meta.get("payload") or {}).get("cwd")
    if cwd not in (str(launch.wt), os.path.realpath(launch.wt)):
        return False
    return any(
        record.get("type") == "response_item"
        and (record.get("payload") or {}).get("type") == "message"
        and record["payload"].get("role") == "user"
        and _text(record["payload"].get("content"), "input_text") == launch.kickoff
        for record in records
    )


def codex(launch: Launch, delivery: Delivery, marker: float) -> None:
    """The rollout is tied to this launch by its cwd and its age, never by record order."""
    sessions = launch.codex_home / "sessions"
    for _ in range(ROLLOUT_POLL // 2):
        for path in sessions.rglob("rollout-*.jsonl") if sessions.is_dir() else ():
            if path.stat().st_mtime > marker and _codex_record(path, launch):
                delivery.evidence = str(path)
                delivery.session = path.stem.removeprefix("rollout-")[20:]
                return
        model.pause(2)
    raise undelivered(
        launch, f"a rollout under ~/.codex/sessions/ for cwd {launch.wt}", ROLLOUT_POLL
    )


def deliver(launch: Launch, marker: float) -> Delivery:
    """The selected tool's own record proves the kickoff, never the process alone."""
    delivery = process(launch)
    if launch.tool == "claude":
        claude(launch, delivery)
    elif launch.tool == "opencode":
        opencode.confirm(launch, delivery, marker)
    else:
        codex(launch, delivery, marker)
    return delivery
