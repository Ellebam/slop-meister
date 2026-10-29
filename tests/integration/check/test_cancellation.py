"""Cancellation during spawn retains the owned process identity."""

import json
import os
import signal
import subprocess
import sys

import pytest

from slopmeister.check import ownership
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
