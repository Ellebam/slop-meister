"""One check is one child process with its own private root and log."""

from dataclasses import dataclass, field
import os
from pathlib import Path
import signal
import subprocess
import threading
import time

from slopmeister.check import ownership

CHECK_TIMEOUT, EXIT_TIMEOUT, EXIT_UNSTARTED = 600, 124, 125
GROUP_STOP_TIMEOUT, PROCESS_INSPECT_TIMEOUT, POLL_INTERVAL = 4, 2, 0.02


@dataclass(frozen=True)
class Check:
    id: str
    argv: tuple[str, ...]
    layer: str = "portable"
    kind: str = "tests"
    phase: str = "parallel"
    seconds: float = 1


@dataclass
class Context:
    cwd: Path
    logs: Path
    child_umask: int = -1
    lock: threading.Lock = field(default_factory=threading.Lock)
    cancelled: threading.Event = field(default_factory=threading.Event)
    active: dict[str, subprocess.Popen] = field(default_factory=dict)


def wait_unreaped(
    process: subprocess.Popen, timeout: float, cancelled: threading.Event | None = None
) -> bool:
    """Observe exit while retaining the leader as the process-group ownership anchor."""
    deadline = time.monotonic() + timeout
    while True:
        if cancelled is not None and cancelled.is_set():
            return False
        try:
            options = os.WEXITED | os.WNOHANG | os.WNOWAIT
            exited = os.waitid(os.P_PID, process.pid, options)
        except ChildProcessError as error:
            message = f"process leader {process.pid} was reaped outside its owner"
            raise RuntimeError(message) from error
        if exited is not None:
            return True
        if time.monotonic() >= deadline:
            raise subprocess.TimeoutExpired(process.args, timeout)
        time.sleep(POLL_INTERVAL)


def stop_group(process: subprocess.Popen, *, anchored: bool = False) -> None:
    if anchored:
        _stop_anchored_group(process)
        return
    owned = _group_identities(process.pid)
    if not owned:
        return
    if process.poll() is None:
        _signal(process.pid, signal.SIGTERM, group=True)
        deadline = time.monotonic() + GROUP_STOP_TIMEOUT / 2
        while ownership.identity(process.pid) and time.monotonic() < deadline:
            time.sleep(POLL_INTERVAL)
        if any(_group_identities(process.pid).values()):
            _signal(process.pid, signal.SIGKILL, group=True)
        process.wait(timeout=GROUP_STOP_TIMEOUT / 2)
        return
    for pid, start in owned.items():
        if start and ownership.identity(pid) == start:
            _signal(pid, signal.SIGKILL)
    deadline = time.monotonic() + GROUP_STOP_TIMEOUT / 2
    while (
        any(start and ownership.identity(pid) == start for pid, start in owned.items())
        and time.monotonic() < deadline
    ):
        time.sleep(POLL_INTERVAL)


def _stop_anchored_group(process: subprocess.Popen) -> None:
    deadline = time.monotonic() + GROUP_STOP_TIMEOUT
    if ownership.identity(process.pid):
        _signal(process.pid, signal.SIGTERM, group=True)
        graceful = min(deadline, time.monotonic() + GROUP_STOP_TIMEOUT / 2)
        while _group_identities(process.pid) and time.monotonic() < graceful:
            time.sleep(POLL_INTERVAL)
    while remaining := _group_identities(process.pid):
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"owned process group {process.pid} still active: {sorted(remaining)}"
            )
        _signal(process.pid, signal.SIGKILL, group=True)
        time.sleep(POLL_INTERVAL)
    getattr(process, "reap", process.wait)(timeout=max(POLL_INTERVAL, deadline - time.monotonic()))


def _group_identities(group_id: int) -> dict[int, str | None]:
    rows = subprocess.run(
        ["ps", "-axo", "pid=,pgid=,stat="],
        capture_output=True,
        text=True,
        check=True,
        timeout=PROCESS_INSPECT_TIMEOUT,
    ).stdout.splitlines()
    owned = {}
    for pid_text, group, status in map(str.split, rows):
        if int(group) == group_id and not status.startswith("Z"):
            pid = int(pid_text)
            if birth := ownership.identity(pid):
                owned[pid] = birth
    return owned


def _signal(pid: int, signum: signal.Signals, *, group: bool = False) -> None:
    try:
        (os.killpg if group else os.kill)(pid, signum)
    except ProcessLookupError:
        pass
    except PermissionError as error:
        raise PermissionError(f"{signum.name}: {error}") from error


def _cleanup(root: Path, stream) -> bool:
    try:
        ownership.stop_run(root)
        ownership.remove(root)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        stream.write(f"cleanup failed: {error}\n")
        return False
    return True


def _stop_child(process: subprocess.Popen, stream, *, anchored: bool = False) -> None:
    try:
        stop_group(process, anchored=anchored)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        stream.write(f"cleanup failed: {error}\n")


def _environment(job_root: Path) -> dict[str, str]:
    # A gate run inside a test keeps the outer folder so the outer job still stops its jobs.
    inherited = os.environ.get(ownership.ROOT_VARIABLE)
    marker = f"{inherited}:{job_root}" if inherited else str(job_root)
    return dict(os.environ, TMPDIR=str(job_root), **{ownership.ROOT_VARIABLE: marker})


@dataclass
class Launch:
    check: Check
    env: dict[str, str]
    stream: object


def _run_child(launch: Launch, context: Context) -> int:
    check = launch.check
    with context.lock:
        if context.cancelled.is_set():
            return EXIT_UNSTARTED
        process = subprocess.Popen(
            check.argv,
            cwd=context.cwd,
            stdout=launch.stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            umask=context.child_umask,
            env=launch.env,
        )
        context.active[check.id] = process
    try:
        if not wait_unreaped(process, CHECK_TIMEOUT, context.cancelled):
            _stop_child(process, launch.stream, anchored=True)
            return EXIT_UNSTARTED
        return process.wait()
    except subprocess.TimeoutExpired:
        _stop_child(process, launch.stream, anchored=True)
        launch.stream.write(f"Check exceeded its {CHECK_TIMEOUT}-second execution limit.\n")
        return EXIT_TIMEOUT
    except BaseException:
        _stop_child(process, launch.stream, anchored=True)
        raise
    finally:
        with context.lock:
            context.active.pop(check.id, None)


def _new_job(check: Check, context: Context) -> tuple[Path, dict, Path]:
    root, owner = ownership.new_run()
    return root, owner, context.logs / (check.id + ".log")


def execute(check: Check, context: Context) -> dict | None:
    began, began_at = time.monotonic(), ownership.utc()
    job_root, job_owner, output = _new_job(check, context)
    with output.open("w") as stream:
        try:
            launch = Launch(check, _environment(job_root), stream)
            rc = _run_child(launch, context)
        except OSError as error:
            stream.write(str(error) + "\n")
            rc = EXIT_UNSTARTED
        finally:
            cleanup_ok = _cleanup(job_root, stream)
    rc = 1 if not cleanup_ok and rc == 0 else rc
    if rc == EXIT_UNSTARTED and context.cancelled.is_set():
        return None
    return {
        "id": check.id,
        "returncode": rc,
        "owner": job_owner,
        "started_at": began_at,
        "finished_at": ownership.utc(),
        "elapsed_seconds": time.monotonic() - began,
        "log": str(output),
    }
