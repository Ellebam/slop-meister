"""Bound subprocess output, duration and process-group cleanup."""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import time

from .constants import KNOWN_FAILURES, LIMIT


@dataclass(frozen=True)
class Run:
    argv: list[str]
    env: dict[str, str]
    payload: bytes = b""
    timeout: float = 45
    failure: str = "ACTION_FAILED"
    own_group: bool = True
    deadline: float | None = None
    cwd: Path | None = None


@dataclass
class Capture:
    process: subprocess.Popen
    output: bytearray = field(default_factory=bytearray)
    errors: int = 0
    remaining: memoryview = field(default_factory=lambda: memoryview(b""))


def _timeout(run: Run) -> float:
    return min(run.timeout, run.deadline - time.monotonic()) if run.deadline else run.timeout


def _register(capture: Capture, selector: selectors.BaseSelector) -> None:
    for stream in (capture.process.stdout, capture.process.stderr):
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, selectors.EVENT_READ)
    if capture.remaining:
        os.set_blocking(capture.process.stdin.fileno(), False)
        selector.register(capture.process.stdin, selectors.EVENT_WRITE)
    else:
        capture.process.stdin.close()


def _event(capture: Capture, selector: selectors.BaseSelector, stream) -> None:
    if stream is capture.process.stdin:
        try:
            sent = os.write(stream.fileno(), capture.remaining[:65536])
            capture.remaining = capture.remaining[sent:]
        except BrokenPipeError:
            capture.remaining = memoryview(b"")
        if not capture.remaining:
            selector.unregister(stream)
            stream.close()
        return
    chunk = os.read(stream.fileno(), 65536)
    if not chunk:
        selector.unregister(stream)
        stream.close()
    elif stream is capture.process.stdout:
        capture.output.extend(chunk)
    else:
        capture.errors += len(chunk)
    if len(capture.output) > LIMIT or capture.errors > 65536:
        raise ValueError("ACTION_OUTPUT_LIMIT")


def _capture(capture: Capture, deadline: float) -> None:
    with selectors.DefaultSelector() as selector:
        _register(capture, selector)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError("ACTION_TIMEOUT")
            for key, _ in selector.select(min(0.2, remaining)):
                _event(capture, selector, key.fileobj)


def _failure(output: bytearray, fallback: str) -> ValueError:
    try:
        code = json.loads(output).get("result", "")
    except (
        ValueError,
        AttributeError,
    ):
        code = ""
    if code in KNOWN_FAILURES or re.fullmatch(r"HTTP_[0-9]{3}", code):
        return ValueError(code)
    return ValueError(fallback)


def invoke(run: Run) -> bytes:
    timeout = _timeout(run)
    if timeout <= 0:
        raise ValueError("ACTION_TIMEOUT")
    process = subprocess.Popen(
        run.argv,
        env=run.env,
        cwd=run.cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        process_group=0 if run.own_group else None,
    )
    capture = Capture(process, remaining=memoryview(run.payload))
    deadline = time.monotonic() + timeout
    try:
        _capture(capture, deadline)
        if process.wait(timeout=max(0.01, deadline - time.monotonic())):
            raise _failure(capture.output, run.failure)
        return bytes(capture.output)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL) if run.own_group else process.kill()
            process.wait()
        for stream in (process.stdin, process.stdout, process.stderr):
            if not stream.closed:
                stream.close()
