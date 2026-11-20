"""Cancellation during spawn retains the owned process identity."""

import json
import os
import signal
import subprocess
import sys

import pytest

from slopmeister.check import jobs, ownership, scheduler
from tests.integration.check.test_cli import terminate, wait_for


def cancellation_program(root, phase):
    return f"""
import json, signal, sys, threading, time
from pathlib import Path; from slopmeister.check import cli, jobs, ownership
root = cli.ROOT = Path({str(root)!r})
native_spawn, native_signal, native_stop = jobs.subprocess.Popen, signal.signal, jobs.stop_group
def spawn(*args, **kwargs):
    child = native_spawn(*args, **kwargs)
    if args[0][0] == sys.executable:
        record = dict(pid=child.pid, identity=ownership.identity(child.pid))
        (root/'child.json').write_text(json.dumps(record))
        (root/'spawn-thread').write_text(str(threading.get_ident())); (root/'spawned').touch()
        while not (root/'release').exists(): time.sleep(.01)
    return child
def stop(child, *args, **kwargs):
    (root/'stop-thread').write_text(str(threading.get_ident()))
    return native_stop(child, *args, **kwargs)
def install(signum, handler):
    def observed(*args):
        (root/'signal-received').touch()
        return handler(*args)
    return native_signal(signum, observed if callable(handler) else handler)
jobs.subprocess.Popen, jobs.stop_group, signal.signal = spawn, stop, install
install(signal.SIGINT, signal.default_int_handler); child = 'import time; time.sleep(30)'
cli.catalogue.catalogue = lambda *_, **__: [
    jobs.Check('waiting', (sys.executable, '-c', child), phase={phase!r})
]
raise SystemExit(cli.main(['--jobs', '1', '--report', str(root/'report.json')]))
"""


def stop_record(path):
    if path.exists():
        record = json.loads(path.read_text())
        if ownership.identity(record["pid"]) == record["identity"]:
            os.kill(record["pid"], signal.SIGKILL)


@pytest.mark.parametrize("phase", ["first", "parallel", "last"])
@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
def test_cancellation_during_spawn_registers_and_stops_the_child(tmp_path, phase, signum):
    """Escaping bug: scheduler and worker teardown could race away the group anchor."""
    program = cancellation_program(tmp_path, phase)
    subject = subprocess.Popen(
        [sys.executable, "-c", program], env=dict(os.environ, HOME=str(tmp_path / "home"))
    )
    foreign = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    foreign_birth = ownership.identity(foreign.pid)
    try:
        wait_for(tmp_path / "spawned", subject)
        subject.send_signal(signum)
        wait_for(tmp_path / "signal-received", subject)
        (tmp_path / "release").touch()
        assert subject.wait(timeout=5) == 1
        result = json.loads((tmp_path / "report.json").read_text())
        record = json.loads((tmp_path / "child.json").read_text())
        assert result["interrupted"] and not result["complete"] and not result["passed"]
        assert ownership.identity(record["pid"]) != record["identity"]
        assert (tmp_path / "stop-thread").read_text() == (tmp_path / "spawn-thread").read_text()
        assert foreign.poll() is None and ownership.identity(foreign.pid) == foreign_birth
    finally:
        (tmp_path / "release").touch()
        terminate(subject)
        stop_record(tmp_path / "child.json")
        terminate(foreign)


def test_signal_that_surfaces_as_another_error_still_stops_the_running_check(tmp_path):
    """Bug: a signal inside Thread.start became RuntimeError and the gate waited for its child."""
    program = f"""
import os, signal, sys, time
from pathlib import Path; from slopmeister.check import cli, jobs, scheduler
root = cli.ROOT = Path({str(tmp_path)!r})
native_spawn, native_submit = jobs.subprocess.Popen, scheduler.ThreadPoolExecutor.submit
def spawn(*args, **kwargs):
    child = native_spawn(*args, **kwargs)
    if args[0][0] == sys.executable: (root/'spawned').touch()
    return child
def submit(self, *args, **kwargs):
    future = native_submit(self, *args, **kwargs)
    while not (root/'spawned').exists(): time.sleep(.01)
    try:
        os.kill(os.getpid(), signal.SIGTERM); time.sleep(5)
    except KeyboardInterrupt:
        raise RuntimeError('release unlocked lock')
    return future
jobs.subprocess.Popen, scheduler.ThreadPoolExecutor.submit = spawn, submit
cli.catalogue.catalogue = lambda *_, **__: [
    jobs.Check('waiting', (sys.executable, '-c', 'import time; time.sleep(30)'), phase='last')
]
raise SystemExit(cli.main(['--jobs', '1', '--report', str(root/'report.json')]))
"""
    subject = subprocess.Popen([sys.executable, "-c", program])
    try:
        assert subject.wait(timeout=10) == 1
        result = json.loads((tmp_path / "report.json").read_text())
        assert result["interrupted"] and not result["complete"] and not result["passed"]
    finally:
        terminate(subject)


def test_an_error_without_a_signal_still_fails_the_gate(tmp_path, monkeypatch):
    """Bug: treating every error as a cancel would report a crashed gate as interrupted."""

    def broken(*_):
        raise RuntimeError("scheduler fault")

    monkeypatch.setattr(scheduler, "execute", broken)
    settings = scheduler.Settings(1, tmp_path, tmp_path / "logs")
    with pytest.raises(RuntimeError, match="scheduler fault"):
        scheduler.run_checks([jobs.Check("broken", (sys.executable, "-c", "pass"))], settings)
    assert settings.cancelled.is_set()
