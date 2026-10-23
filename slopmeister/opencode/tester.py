"""OpenCode as the autonomous tester: its command, its environment and its native outcome."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

from slopmeister.opencode import native
from slopmeister.review.process import project_child_env
from slopmeister.review.redact import redact

CAUSE_CHARACTERS = 200


def settings(args: argparse.Namespace) -> dict:
    """Checked before a run starts, so a missing CLI or key creates no run."""
    names = native.require_provider(os.environ)
    return {
        "tool": "opencode",
        "model": args.tester_model or "",
        "effort": "",
        "binary": native.binary(),
        "provider_names": names,
    }


def command(run: dict) -> list[str]:
    selected = ["-m", run["model"]] if run["model"] else []
    return [
        run["binary"], "run", "--format", "json", "--dir", run["checkout"],
        "--print-logs", "--log-level", "INFO", *selected,
    ]  # fmt: skip


def supervisor_env(run: dict) -> dict:
    """The supervisor needs the named provider values to hand them on, run.json keeps names."""
    names = run["provider_names"]
    return {
        **project_child_env(),
        **{name: os.environ[name] for name in names if name in os.environ},
    }


def child_env(run: dict) -> dict:
    """The guide, notes and evidence sit in the run root above the checkout, and only there."""
    root = Path(run["checkout"]).parent
    rules = {**native.permission(edit=False), "external_directory": {f"{root}/*": "allow"}}
    return native.child_env(os.environ, run["provider_names"], rules)


def scrub(root: Path, run: dict) -> None:
    values = [os.environ[name] for name in run["provider_names"] if name in os.environ]
    native.scrub(root, values, Path(run["checkout"]))


def _events(root: Path) -> list[tuple[int, dict]]:
    rows = []
    for number, line in enumerate((root / "events.jsonl").read_text().splitlines(), 1):
        try:
            event = json.loads(line)
        except ValueError:
            continue  # --print-logs keeps logs on stderr, a stray line is not an event
        if isinstance(event, dict):
            rows.append((number, event))
    return rows


def _check_stream(root: Path, run: dict, events: list[tuple[int, dict]]) -> None:
    where = root / "events.jsonl"
    for number, event in events:
        if event.get("type") == "error":
            error = event.get("error") or {}
            data = error.get("data") or {}
            status = data.get("statusCode", "no status")
            cause = redact(str(data.get("message", "")))[:CAUSE_CHARACTERS]
            raise native.Blocked(
                "provider error",
                f"{error.get('name', 'error')} ({status}): {cause}",
                f"check the provider's reachability and key. Evidence: {where}:{number}",
            )
    _refusals(where, events)
    finishes = [(n, e) for n, e in events if e.get("type") == "step_finish"]
    reason = finishes[-1][1].get("part", {}).get("reason") if finishes else None
    if reason != "stop" or run.get("tester_exit"):
        line = finishes[-1][0] if finishes else len(events)
        raise native.Blocked(
            "interrupted",
            f"the run ended with reason {reason!r} and exit {run.get('tester_exit')}",
            f"report this blocked run, the subject was not graded. Evidence: {where}:{line}",
        )


def _refusals(where: Path, events: list[tuple[int, dict]]) -> None:
    """A headless run auto-rejects every permission question, the model then stops early."""
    for number, event in events:
        state = (event.get("part") or {}).get("state") or {}
        if event.get("type") == "tool_use" and "rejected permission" in str(state.get("error")):
            tool = event["part"].get("tool")
            raise native.Blocked(
                "permission refused",
                f"OpenCode refused a {tool} call that a headless run cannot approve",
                f"read the refused call and stderr.log. Evidence: {where}:{number}",
            )


def _completion(root: Path, events: list[tuple[int, dict]]) -> None:
    texts = [(n, e["part"].get("text", "")) for n, e in events if e.get("type") == "text"]
    if texts and texts[-1][1].strip():
        return
    line = texts[-1][0] if texts else 0
    raise native.Blocked(
        "interrupted",
        "the run has no final message",
        f"read the final text event. Evidence: {root / 'events.jsonl'}:{line}",
    )


def _receipt(root: Path, run: dict, prompt: str) -> dict:
    checkout = Path(run["checkout"])
    store = native.Store(run["binary"], checkout, child_env(run))
    found = native.receipt(native.export(store, run["session_id"]))
    problems = []
    if found["directory"] != os.path.realpath(checkout):
        problems.append("its directory is not the tester checkout")
    if found["prompt_sha256"] != hashlib.sha256(prompt.encode()).hexdigest():
        problems.append("its first prompt is not the tester prompt")
    if not found["models"] or run["model"] and found["models"] != [run["model"]]:
        problems.append(f"it ran {found['models']}, requested {run['model'] or 'the default'}")
    (root / "native.json").write_text(json.dumps(found, indent=2) + "\n")
    if problems:
        raise native.Blocked(
            "no native evidence",
            "; ".join(problems),
            f"inspect the checked fields. Evidence: {root / 'native.json'}",
        )
    return found


def _delete(run: dict, session: str) -> None:
    """The receipt is saved first, a failed delete leaves a session, never a lost proof."""
    try:
        done = subprocess.run(
            [run["binary"], "session", "delete", session],
            cwd=run["checkout"], env=child_env(run), capture_output=True, stdin=subprocess.DEVNULL,
            timeout=native.COMMAND_SECONDS, check=False,
        )  # fmt: skip
    except OSError, subprocess.SubprocessError:
        run["session_deleted"] = False
        return
    run["session_deleted"] = done.returncode == 0


def outcome(root: Path, run: dict, prompt: str) -> None:
    events = _events(root)
    session = next((e["sessionID"] for _, e in events if e.get("sessionID")), None)
    if not session:
        raise native.Blocked(
            "no native evidence",
            "the event stream names no session",
            f"read the startup failure in {root / 'stderr.log'}",
        )
    run["session_id"] = session
    try:
        _check_stream(root, run, events)
        found = _receipt(root, run, prompt)
        run.update(observed_model=",".join(found["models"]), native_source="opencode export")
        _completion(root, events)
    finally:
        _delete(run, session)
