"""Expose one fixed writer through the native client's per-tool approval boundary."""

from contextlib import suppress
import json
import os
from pathlib import Path
import selectors
import shlex
import signal
import subprocess
import sys
import time

from service_actions.constants import PYTHON, PYTHON_FLAGS
from service_actions.native_gate import diagnostic, require_host
from service_actions.native_process import NATIVE_ERROR

ROOT = Path(__file__).resolve().parent
MAX_INPUT = 512 * 1024
MAX_COMMAND = 65536
TIMEOUT = 330


def reply(identity, result, *, error=False):
    key = "error" if error else "result"
    message = {"jsonrpc": "2.0", "id": identity, key: result}
    print(json.dumps(message), flush=True)


def tool(why: str) -> dict:
    return dict(
        name="run",
        description=why,
        inputSchema={
            "type": "object",
            "properties": {"command": {"type": "string", "maxLength": MAX_COMMAND}},
            "required": ["command"],
            "additionalProperties": False,
        },
        annotations={"readOnlyHint": False},
    )


def arguments(params: dict) -> tuple[list[str], str]:
    if params.get("name") != "run" or not isinstance(params.get("arguments"), dict):
        raise ValueError("ARGUMENTS_NOT_SUPPORTED")
    values = params["arguments"]
    command = values.get("command")
    if set(values) != {"command"} or not isinstance(command, str) or len(command) > MAX_COMMAND:
        raise ValueError("ARGUMENTS_NOT_SUPPORTED")
    argv = shlex.split(command)
    prefix = [str(PYTHON), *PYTHON_FLAGS, str(ROOT / "entry.py"), "--output"]
    if argv[: len(prefix)] != prefix or len(argv) < len(prefix) + 2:
        raise ValueError("ARGUMENTS_NOT_SUPPORTED")
    return argv, argv[len(prefix)]


def start(request: dict, binding: dict) -> dict:
    require_host(ROOT, binding)
    argv, output = arguments(request.get("params", {}))
    child = subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return dict(
        child=child, identity=request["id"], output=output, deadline=time.monotonic() + TIMEOUT
    )


def stop(job: dict) -> None:
    child = job["child"]
    if child.poll() is None:
        try:
            os.killpg(child.pid, signal.SIGTERM)
            child.wait(timeout=5)
        except ProcessLookupError, subprocess.TimeoutExpired:
            pass
    # A leader can exit on TERM while one of its descendants keeps running.
    with suppress(ProcessLookupError):
        os.killpg(child.pid, signal.SIGKILL)
    child.wait()


def completed(job: dict, *, uncertain=False) -> None:
    status = job["child"].returncode
    value = dict(exit_code=status, result_file=job["output"])
    if uncertain:
        value["uncertain"] = True
    reply(
        job["identity"],
        dict(content=[dict(type="text", text=json.dumps(value))], isError=status != 0),
    )


def dispatch(request: dict, binding: dict, job: dict | None) -> dict | None:
    method, identity = request.get("method"), request.get("id")
    if method == "notifications/cancelled":
        if job and request.get("params", {}).get("requestId") == job["identity"]:
            stop(job)
            completed(job, uncertain=True)
            job = None
        return job
    if identity is None:
        return job
    if method == "initialize":
        result = dict(
            protocolVersion=request["params"]["protocolVersion"],
            capabilities={"tools": {}},
            serverInfo={"name": ROOT.name, "version": "1"},
        )
    elif method == "tools/list":
        result = {"tools": [tool(binding["why"])]}
    elif method == "tools/call" and job is None:
        return start(request, binding)
    else:
        reply(identity, {"code": -32600, "message": "REQUEST_INVALID"}, error=True)
        result = None
    if result is not None:
        reply(identity, result)
    return job


def fresh_state() -> dict:
    """The served job and the two signal flags, shared by serve, batch and the handler."""
    return {"job": None, "handoff": False, "stopping": False}


def stop_signal(state: dict):
    """Raising between spawning a writer and recording it would leave the writer unowned,
    so a signal during that handoff is deferred and acted on right after it."""

    def terminate(_signal, _frame):
        if state["handoff"]:
            state["stopping"] = True
            return
        raise SystemExit(1)

    return terminate


def batch(pending: bytes, binding: dict, state: dict) -> bytes | None:
    chunk = os.read(0, MAX_INPUT)
    if not chunk:
        return None
    pending += chunk
    if len(pending) > MAX_INPUT:
        raise ValueError("INPUT_INVALID")
    *lines, pending = pending.split(b"\n")
    for line in lines:
        try:
            request = json.loads(line)
            valid = isinstance(request, dict) and request.get("jsonrpc") == "2.0"
            if not valid or not isinstance(request.get("params", {}), dict):
                raise ValueError("INPUT_INVALID")
            if type(request.get("id")) not in (str, int, type(None)):
                raise ValueError("INPUT_INVALID")
        except ValueError, UnicodeError, RecursionError:
            reply(None, {"code": -32600, "message": "INPUT_INVALID"}, error=True)
            return None
        # A writer may be spawned before it is recorded, so preserve an active handoff.
        state["handoff"] = state["handoff"] or request.get("method") == "tools/call"
        try:
            state["job"] = dispatch(request, binding, state["job"])
        except (ValueError, KeyError, TypeError, OSError) as error:
            message = "ARGUMENTS_NOT_SUPPORTED"
            if str(error).partition(":")[0] == NATIVE_ERROR:
                message = diagnostic(error)
            reply(request.get("id"), {"code": -32602, "message": message}, error=True)
    return pending


def settle(state: dict) -> None:
    """Report a job that exited or ran past its deadline, stopping what it left behind."""
    job = state["job"]
    if job and (job["child"].poll() is not None or time.monotonic() > job["deadline"]):
        expired = job["child"].poll() is None
        stop(job)
        completed(job, uncertain=expired)
        state["job"] = None


def serve(binding: dict) -> None:
    require_host(ROOT, binding)
    state = fresh_state()
    signal.signal(signal.SIGTERM, stop_signal(state))
    signal.signal(signal.SIGHUP, stop_signal(state))
    pending = b""
    poll = selectors.DefaultSelector()
    poll.register(0, selectors.EVENT_READ)
    try:
        while pending is not None:
            settle(state)
            if not poll.select(0.1):
                continue
            pending = batch(pending, binding, state)
            state["handoff"] = False
            if state["stopping"]:
                raise SystemExit(1)
    finally:
        poll.close()
        if state["job"]:
            stop(state["job"])


def main() -> int:
    try:
        profile = json.loads((ROOT / "config.json").read_text())
        serve(profile["native"])
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(diagnostic(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
