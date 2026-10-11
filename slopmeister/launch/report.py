"""Report delivery, persist launcher identity and observe the model the worker runs."""

from __future__ import annotations

import json
import time

from slopmeister.launch import arguments, command, kickoff, model
from slopmeister.launch.model import Delivery, Launch, Stop, shq
from slopmeister.opencode import launch as opencode
from slopmeister.session import launch_identity

MODEL_CONFIRM_SECONDS = 60


def _thread_name(launch: Launch, thread_id: str) -> str:
    """The automatic name is cut from the kickoff, so only its relation to the name is shown."""
    try:
        lines = (launch.codex_home / "session_index.jsonl").read_text().splitlines()
        rows = [line for line in lines if f'"id":"{thread_id}"' in line]
        name = json.loads(rows[-1]).get("thread_name") or "" if rows else ""
    except OSError, ValueError, AttributeError:
        name = ""
    if not name:
        return "none recorded yet"
    if name == launch.name or name.startswith(launch.name + " "):
        return "carries the session name, automatic, the model may rename it"
    return "rewritten by the model, no longer the session name"


def delivered(launch: Launch, delivery: Delivery) -> None:
    lines = ["plot-session: delivered", f"  tool: {launch.tool}", f"  name: {launch.name}"]
    lines += [f"  pid: {delivery.pid}", f"  directory: {launch.wt}"]
    if launch.tool == "claude":
        lines += [f"  session id: {delivery.session}", "  registered: yes (claude agents)"]
    elif launch.tool == "opencode":
        lines += [f"  session id: {delivery.session}"]
        lines.append(f"  resume: cd {launch.wt} && opencode -s {delivery.session}")
    else:
        thread = delivery.session
        lines += [f"  thread id: {thread}", f"  thread name: {_thread_name(launch, thread)}"]
        wt = shq(str(launch.wt))
        overrides = "".join(
            " -c " + shq(value)
            for index, token in enumerate(launch.extra)
            if (value := arguments.config_override(token, launch.extra, index))
            and value.partition("=")[0].strip(" '\"") == "approvals_reviewer"
        )
        # A manually reviewed launch must not resume with automatic approval.
        settings = command.CODEX_APPROVAL + overrides + command.CODEX_ROOTS
        resume = (
            f"cd {wt} && env CODEX_HOME={shq(str(launch.codex_home))} "
            f"{shq(str(launch.codex_bin))} resume {shq(thread)} --no-daemon"
            f"{settings}{command._native_approvals(launch)} -C {wt}"
        )
        lines.append(f"  resume: {resume}")
    lines += [f"  kickoff: {kickoff.receipt(launch)}", f"  evidence: {delivery.evidence}"]
    print("\n".join(lines))


def prepare_identity(launch: Launch) -> None:
    path = launch_identity.write(launch.wt, (launch.name, launch.tool, None))
    print(f"  launcher identity: prepared ({path})")


def confirm_identity(launch: Launch, delivery: Delivery) -> None:
    try:
        path = launch_identity.write(launch.wt, (launch.name, launch.tool, delivery.session))
    except (OSError, ValueError) as error:
        raise Stop(
            1,
            "plot-session: worker running, launcher identity unconfirmed, kickoff delivered\n"
            f"  directory: {json.dumps(str(launch.wt))}\n"
            f"  session id: {json.dumps(delivery.session)}\n"
            f"  evidence: {json.dumps(delivery.evidence)}\n"
            f"  identity error: {json.dumps(str(error))}\n"
            "Inspect the existing worker before recovery. Keep its session and worktree "
            "intact while it is running.",
        ) from error
    print(f"  launcher identity: confirmed ({path})")


def _observed(tool: str, evidence: str) -> tuple[str, int] | None:
    record_type, field = (
        ("turn_context", "payload") if tool == "codex" else ("assistant", "message")
    )
    try:
        with open(evidence, encoding="utf-8") as stream:
            lines = stream.readlines()
    except OSError, UnicodeError:
        return None
    for number, line in enumerate(lines, 1):
        if not line.endswith("\n"):
            return None  # A writer may still be appending this record.
        model = _model(line, record_type, field)
        if model and not (tool == "claude" and model == "<synthetic>"):
            return model, number
    return None


def _model(line: str, record_type: str, field: str) -> str | None:
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(record, dict) or record.get("type") != record_type:
        return None
    payload = record.get(field)
    model = payload.get("model") if isinstance(payload, dict) else None
    return model if isinstance(model, str) and model.strip() else None


def observe_model(launch: Launch, delivery: Delivery) -> None:
    """JSON encoding keeps an observed name from injecting terminal controls into the report."""
    if not (launch.model_set or launch.claim_managed and launch.claim_model):
        return
    requested = launch.claim_model or launch.model
    print("  model requested: " + json.dumps(requested), flush=True)
    record_type = "turn_context" if launch.tool == "codex" else "assistant"
    deadline = time.monotonic() + MODEL_CONFIRM_SECONDS
    for attempt in range(MODEL_CONFIRM_SECONDS + 1):
        if launch.tool == "opencode":
            opencode.refresh(launch, delivery)
        found = _observed(launch.tool, delivery.evidence)
        if found:
            print("  model observed: " + json.dumps(found[0]))
            print("  model comparison: " + ("same" if found[0] == requested else "different"))
            print(f"  model evidence: {delivery.evidence}:{found[1]} ({record_type})")
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0 or attempt == MODEL_CONFIRM_SECONDS:
            break
        model.pause(min(1, remaining))
    raise Stop(
        1,
        f"plot-session: worker running, model unconfirmed after {MODEL_CONFIRM_SECONDS}s, "
        "kickoff delivered\nInspect the existing worker using the PID, directory and evidence "
        "file above. Keep its session and worktree intact while it is running.",
    )
