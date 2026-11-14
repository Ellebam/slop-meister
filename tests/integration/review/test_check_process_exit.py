"""Only confirmed reviewer exit permits timeout cleanup to release its tester slot."""

import ctypes
import errno
import os
import signal
import subprocess
import sys

import pytest

from slopmeister.check import jobs, ownership
from slopmeister.review import check
from slopmeister.review import run as review_run
from slopmeister.review.schema import CrossToolReviewError
from slopmeister.slots import tester
from tests.integration.review.test_check_slots import borrowed as borrowed

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin", reason="macOS process inspection exit race"
)


@pytest.fixture
def reviewer(borrowed, monkeypatch):
    repo, _data, _args = borrowed
    tool = repo.parent / "claude"
    tool.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(30)\n")
    tool.chmod(0o700)
    monkeypatch.setenv("CROSS_TOOL_REVIEW_TIMEOUT_SECONDS", "1")
    processes, start = [], review_run._start_reviewer

    def launch(*values):
        process = start(*values)
        processes.append(process)
        return process

    monkeypatch.setattr(review_run, "_start_reviewer", launch)
    return tool, processes


def fail_inspection(monkeypatch, processes, exited):
    cdll, inspected = ctypes.CDLL, []
    libproc = cdll("/usr/lib/libproc.dylib", use_errno=True)
    native_inspect = libproc.proc_pidinfo

    def inspect(pid, *values):
        if processes and pid == processes[0].pid and not inspected:
            if exited:
                os.kill(pid, signal.SIGTERM)
                jobs.wait_unreaped(processes[0], 5)
                os.kill(pid, 0)  # The exited reviewer still exists until its parent reaps it.
            inspected.append(pid)
            ctypes.set_errno(errno.EPERM)
            return 0
        return native_inspect(pid, *values)

    def library(name, **options):
        return libproc if name == "/usr/lib/libproc.dylib" else cdll(name, **options)

    monkeypatch.setattr(libproc, "proc_pidinfo", inspect)
    monkeypatch.setattr(ctypes, "CDLL", library)
    return inspected


@pytest.fixture
def unrelated_process():
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        yield process, ownership.identity(process.pid)
    finally:
        process.terminate()
        process.wait(timeout=5)


@pytest.mark.parametrize("exited", [True, False], ids=["unreaped", "live"])
def test_timeout_with_exited_process_releases_only_a_verified_slot(
    borrowed, reviewer, monkeypatch, unrelated_process, exited
):
    repo, data, args = borrowed
    tool, processes = reviewer
    inspected = fail_inspection(monkeypatch, processes, exited)
    try:
        with check.prepared(args, None) as prepared:
            assert (data / tester.RECORD).exists(), "the reviewer never acquired a tester slot"
            with pytest.raises(CrossToolReviewError) as raised:
                prepared.runner([str(tool)], cwd=prepared.checkout)
            assert inspected == [processes[0].pid]
            assert raised.value.category.value == ("TIMEOUT" if exited else "CONTROL_FAILURE")
            assert raised.value.process_stopped is exited
            assert prepared.stopped is exited
        assert prepared.checkout.exists() is not exited
        assert (data / tester.RECORD).exists() is not exited
        assert bool(prepared.cleanup_error) is not exited
        assert unrelated_process[0].poll() is None
        assert ownership.identity(unrelated_process[0].pid) == unrelated_process[1]
    finally:
        for process in processes:
            if process.returncode is None:
                jobs.stop_group(process, anchored=True)
        if (data / tester.RECORD).exists():
            tester.recover(data, repo.parent.parent, "1")
        assert not (data / tester.RECORD).exists()
        assert not prepared.checkout.exists()
