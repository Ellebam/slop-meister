"""Failed checks expose bounded evidence without restructuring the CI jobs."""

import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from slopmeister.check import jobs, ownership
from slopmeister.check.jobs import stop_group

ROOT = Path(__file__).resolve().parents[3]
LATE_CHILD_SCRIPT = (
    "import signal, subprocess, sys, time\n"
    "from pathlib import Path\n"
    "child_pid, ready = Path({child_pid}), Path({ready})\n"
    "def stop(*_):\n"
    "    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
    "    child_pid.write_text(str(child.pid))\n"
    "    raise SystemExit(0)\n"
    "signal.signal(signal.SIGTERM, stop)\n"
    "ready.touch()\n"
    "while True: time.sleep(1)\n"
)
FORK_ON_TERM_SCRIPT = (
    "import signal, subprocess, sys, time\n"
    "from pathlib import Path\n"
    "def stop(*_):\n"
    "    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
    "    Path(sys.argv[1]).write_text(str(child.pid))\n"
    "    raise SystemExit(0)\n"
    "signal.signal(signal.SIGTERM, stop)\n"
    "Path(sys.argv[2]).touch()\n"
    "while True: time.sleep(1)\n"
)
ORPHAN_FORK_SCRIPT = (
    "import subprocess, sys, time\n"
    "from pathlib import Path\n"
    f"child_script = {FORK_ON_TERM_SCRIPT!r}\n"
    "child_pid, grandchild_pid, ready = map(Path, sys.argv[1:])\n"
    "child = subprocess.Popen([sys.executable, '-c', child_script, "
    "str(grandchild_pid), str(ready)])\n"
    "child_pid.write_text(str(child.pid))\n"
    "while not ready.exists(): time.sleep(0.01)\n"
)
FAST_FORK_SCRIPT = (
    "import subprocess, sys, time\n"
    "from pathlib import Path\n"
    "pids = Path(sys.argv[1])\n"
    "deadline = time.monotonic() + 1\n"
    "while time.monotonic() < deadline:\n"
    "    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
    "    with pids.open('a') as stream: stream.write(str(child.pid) + '\\n')\n"
    "time.sleep(30)\n"
)


def failing_check_program(root: Path, child: str | None = None, before_main: str = "") -> str:
    child = child or "print('FAILED tests/test_widget.py::test_broken'); raise SystemExit(1)"
    return f"""
import sys
from pathlib import Path
from slopmeister.check import cli, jobs
cli.ROOT = Path({str(root)!r})
cli.catalogue.catalogue = lambda *_, **__: [
    jobs.Check('fixture-failure', (sys.executable, '-c', {child!r}), phase='parallel')
]
{before_main}
raise SystemExit(cli.main(['--report', str(cli.ROOT/'report.json')]))
"""


def test_captured_failure_prints_actionable_bounded_evidence(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-c", failing_check_program(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1, result.stderr
    assert "FAIL fixture-failure" in result.stdout
    assert "FAILED tests/test_widget.py::test_broken" in result.stdout


def test_captured_failure_survives_ascii_stdout(tmp_path: Path) -> None:
    child = (
        "import sys; "
        "sys.stdout.buffer.write(b'FAILED tests/test_widget.py::test_broken \\xff\\n'); "
        "raise SystemExit(1)"
    )
    result = subprocess.run(
        [sys.executable, "-c", failing_check_program(tmp_path, child)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        env={**os.environ, "PYTHONIOENCODING": "ascii"},
    )
    assert result.returncode == 1, result.stderr
    assert "FAILED tests/test_widget.py::test_broken" in result.stdout
    assert (tmp_path / "report.json").stat().st_size > 0


def test_failed_report_is_written_before_console_rendering(tmp_path: Path) -> None:
    child_env = os.environ.copy()
    child_env.pop("FORCE_COLOR", None)
    child_env["PYTHON_COLORS"] = "0"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            failing_check_program(
                tmp_path,
                before_main=(
                    "cli.results.console_lines = lambda *_args, **_kwargs: "
                    "(_ for _ in ()).throw(RuntimeError('console failed'))"
                ),
            ),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        env=child_env,
    )
    assert result.returncode == 1
    assert "RuntimeError: console failed" in result.stderr
    assert (tmp_path / "report.json").stat().st_size > 0


def test_stop_group_reaches_a_child_forked_during_term(tmp_path: Path) -> None:
    """Escaping bug: the initial process snapshot missed a child forked during TERM."""
    child_pid = tmp_path / "late-child.pid"
    ready = tmp_path / "ready"
    leader = tmp_path / "leader.py"
    leader.write_text(
        LATE_CHILD_SCRIPT.format(child_pid=repr(str(child_pid)), ready=repr(str(ready)))
    )
    process = subprocess.Popen([sys.executable, str(leader)], start_new_session=True)
    late_pid = None
    try:
        deadline = time.monotonic() + 5
        while not ready.exists():
            assert process.poll() is None and time.monotonic() < deadline
            time.sleep(0.01)
        stop_group(process)
        late_pid = int(child_pid.read_text())
        deadline = time.monotonic() + 2
        while ownership.identity(late_pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ownership.identity(late_pid) is None
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        if late_pid and ownership.identity(late_pid):
            os.kill(late_pid, signal.SIGKILL)


def test_stop_group_does_not_let_a_reaped_leaders_child_fork_during_term(tmp_path: Path) -> None:
    """Escaping bug: a reaped leader's captured child forked while handling TERM."""
    paths = [tmp_path / name for name in ("child.pid", "grandchild.pid", "ready")]
    leader = tmp_path / "leader.py"
    leader.write_text(ORPHAN_FORK_SCRIPT)
    process = subprocess.Popen(
        [sys.executable, str(leader), *(str(path) for path in paths)], start_new_session=True
    )
    process.wait(timeout=5)
    child_pid = int(paths[0].read_text())
    try:
        stop_group(process)
        assert ownership.identity(child_pid) is None
        assert not paths[1].exists()
    finally:
        for pid in (child_pid, int(paths[1].read_text()) if paths[1].exists() else None):
            if pid and ownership.identity(pid):
                os.kill(pid, signal.SIGKILL)


def test_anchored_stop_reaches_descendants_forked_during_teardown(tmp_path: Path) -> None:
    """Escaping bug: a fast same-group fork after a snapshot survived cleanup."""
    pids, ready = tmp_path / "pids", tmp_path / "ready"
    leader = tmp_path / "leader.py"
    leader.write_text(
        "import subprocess, sys, time\nfrom pathlib import Path\n"
        f"pids = Path({str(pids)!r})\n"
        f"subprocess.Popen([sys.executable, '-c', {FAST_FORK_SCRIPT!r}, {str(pids)!r}])\n"
        "while not pids.exists(): time.sleep(.01)\n"
        f"Path({str(ready)!r}).touch()\n"
    )
    process = subprocess.Popen([sys.executable, str(leader)], start_new_session=True)
    foreign = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    foreign_birth = ownership.identity(foreign.pid)
    try:
        assert jobs.wait_unreaped(process, 5)
        jobs.stop_group(process, anchored=True)
        descendants = [int(pid) for pid in pids.read_text().splitlines()]
        assert descendants and all(ownership.identity(pid) is None for pid in descendants)
        assert foreign.poll() is None and ownership.identity(foreign.pid) == foreign_birth
    finally:
        if process.returncode is None:
            process.kill()
            process.wait(timeout=5)
        foreign.terminate()
        foreign.wait(timeout=5)


def test_anchored_stop_bounds_a_nonconvergent_group(monkeypatch) -> None:
    """Escaping bug: repeated group cleanup could block forever."""
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True
    )
    try:
        monkeypatch.setattr(jobs, "GROUP_STOP_TIMEOUT", 0.05)
        monkeypatch.setattr(jobs, "_group_identities", lambda _: {process.pid: "birth"})
        monkeypatch.setattr(jobs, "_signal", lambda *_args, **_kwargs: None)
        with pytest.raises(RuntimeError, match="still active"):
            jobs.stop_group(process, anchored=True)
    finally:
        process.kill()
        process.wait(timeout=5)
