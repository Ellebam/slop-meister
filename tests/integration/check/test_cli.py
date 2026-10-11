"""The check command preserves evidence, cancellation, and catalogue coverage."""

import contextlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

import pytest

from slopmeister.check import catalogue, cli, jobs, ownership

ROOT = Path(__file__).resolve().parents[3]
CHECK_BIN = ROOT / "bin/slopmeister"
ALL_CHECK_IDS = """render ruff format shellcheck quality
pytest-unit pytest-integration pytest-native drift"""
ALL_CHECKS = set(ALL_CHECK_IDS.split())


def termination_program(root, report, phase):
    child = (
        "import os, time\n"
        "from pathlib import Path\n"
        "pid = Path('child.pid.tmp')\n"
        "pid.write_text(str(os.getpid()))\n"
        "pid.replace('child.pid')\n"
        "time.sleep(30)\n"
    )
    return f"""
from pathlib import Path
from slopmeister.check import cli, jobs
cli.ROOT = Path({str(root)!r})
cli.catalogue.catalogue = lambda *_, **__: [
    jobs.Check('waiting', ({sys.executable!r}, '-c', {child!r}), phase={phase!r})
]
raise SystemExit(cli.main(['--jobs', '1', '--report', {str(report)!r}]))
"""


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


def umask_program(root, report, phase, mask):
    child = "import os; from pathlib import Path; Path('created').touch(); print(os.umask(0))"
    return f"""
import os, sys
from pathlib import Path
from slopmeister.check import cli, jobs
cli.ROOT = Path({str(root)!r})
cli.catalogue.catalogue = lambda *_, **__: [
    jobs.Check('permissions', (sys.executable, '-c', {child!r}), phase={phase!r})
]
os.umask({mask})
raise SystemExit(cli.main(['--jobs', '1', '--report', {str(report)!r}]))
"""


def wait_for(path, process):
    deadline = time.monotonic() + 5
    while not path.exists():
        assert process.poll() is None and time.monotonic() < deadline, path.name
        time.sleep(0.01)


def terminate(process):
    if process.poll() is None:
        process.terminate()
    process.wait(timeout=5)


def stop_record(path):
    if path.exists():
        record = json.loads(path.read_text())
        if ownership.identity(record["pid"]) == record["identity"]:
            os.kill(record["pid"], signal.SIGKILL)


def stop_group_from(path):
    if path.exists():
        with contextlib.suppress(ProcessLookupError):
            os.killpg(int(path.read_text()), signal.SIGKILL)


def test_cli_refuses_an_existing_report_before_running_checks(tmp_path):
    report = tmp_path / "report.json"
    report.write_text("foreign report")
    command = [str(CHECK_BIN), "check", "--ci", "--report", str(report)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=10)
    assert result.returncode == 2 and "evidence already exists" in result.stderr
    assert report.read_text() == "foreign report"
    assert not report.with_suffix(".logs").exists()


def test_local_catalogue_contains_exactly_the_expected_checks():
    checks = catalogue.catalogue()
    assert {item.id for item in checks} == ALL_CHECKS


@pytest.mark.parametrize("phase", ["first", "parallel", "last"])
@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
def test_termination_stops_the_owned_child_and_preserves_an_incomplete_report(
    tmp_path, phase, signum
):
    report = tmp_path / "report.json"
    subject = subprocess.Popen([sys.executable, "-c", termination_program(tmp_path, report, phase)])
    foreign = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    foreign_birth = ownership.identity(foreign.pid)
    try:
        wait_for(tmp_path / "child.pid", subject)
        child = int((tmp_path / "child.pid").read_text())
        subject.send_signal(signum)
        assert subject.wait(timeout=5) == 1
        result = json.loads(report.read_text())
        assert foreign.poll() is None and ownership.identity(foreign.pid) == foreign_birth
        assert result["interrupted"] and not result["complete"] and not result["passed"]
        with pytest.raises(ProcessLookupError):
            os.kill(child, 0)
    finally:
        terminate(subject)
        stop_group_from(tmp_path / "child.pid")
        terminate(foreign)


@pytest.mark.parametrize("phase", ["first", "parallel", "last"])
@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
def test_cancellation_during_spawn_registers_and_stops_the_child(tmp_path, phase, signum):
    """Escaping bug: scheduler and worker teardown could race away the group anchor."""
    program = cancellation_program(tmp_path, phase)
    subject = subprocess.Popen([sys.executable, "-c", program])
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


@pytest.mark.parametrize("mask", [0o022, 0o027])
@pytest.mark.parametrize("phase", ["first", "parallel", "last"])
def test_cli_preserves_child_umask_without_exposing_its_report_or_logs(tmp_path, mask, phase):
    report = tmp_path / "report.json"
    program = umask_program(tmp_path, report, phase, mask)
    result = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, text=True, timeout=10
    )
    log = report.with_suffix(".logs") / "permissions.log"
    assert result.returncode == 0, result.stderr
    assert int(log.read_text()) == mask
    assert (tmp_path / "created").stat().st_mode & 0o777 == 0o666 & ~mask
    assert report.stat().st_mode & 0o777 == 0o600
    assert log.stat().st_mode & 0o777 == 0o600
    assert log.parent.stat().st_mode & 0o777 == 0o700


def test_passing_default_run_leaves_no_temporary_folder(tmp_path, run_root, monkeypatch):
    """Escaping bug: every passing gate left an empty slopmeister-check- folder behind."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli.catalogue, "catalogue", lambda *_: [jobs.Check("quick", ("true",))])
    assert cli.main(["--ci", "--jobs", "1"]) == 0
    assert not list(tmp_path.glob("slopmeister-check-*"))
