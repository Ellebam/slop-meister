"""Service-action process cancellation leaves no consumer descendants."""

from contextlib import suppress
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from slopmeister.session.service_actions.process import Run, invoke
from tests.integration.install.helpers import profile

RUNNER_ENV = {
    "PATH": "/usr/bin:/bin",
    "PYTHONPATH": str(Path(__file__).resolve().parents[3]),
    "SLOPMEISTER_SERVICE_ACTION_INPUT": '["--issue", "TEST-7"]',
}


def _op_stub(tmp_path, data):
    ready = tmp_path / "ready.json"
    stub = tmp_path / "op-stub"
    stub.write_text(
        "#!"
        + sys.executable
        + "\nimport json,os,subprocess,sys,time\n"
        + f"data={data!r}\nready={str(ready)!r}\n"
        + "if sys.argv[1] == 'user': "
        + "print(json.dumps(dict(id=data['account_id'],type='SERVICE_ACCOUNT',state='ACTIVE')))\n"
        + "elif sys.argv[1] == 'vault': "
        + "print(json.dumps([dict(id=data['vault_id'],name=data['vault_name'])]))\n"
        + "elif sys.argv[1] == 'run':\n"
        + " child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])\n"
        + " open(ready,'w').write(json.dumps([os.getpid(),child.pid]))\n"
        + " time.sleep(30)\n"
    )
    stub.chmod(0o700)
    return ready, stub


def _runner(tmp_path, data, op, timeout):
    token = tmp_path / "service.env"
    token.write_text("OP_SERVICE_ACCOUNT_TOKEN=ops_SYNTHETIC_CANARY\n")
    token.chmod(0o600)
    data["token_file"] = str(token)
    (tmp_path / "config.json").write_text(json.dumps(data))
    script = tmp_path / "runner.py"
    script.write_text(
        "from dataclasses import replace\n"
        "from pathlib import Path\n"
        "from slopmeister.session.service_actions import supervisor\n"
        + f"supervisor.ROOT=Path({str(tmp_path)!r})\n"
        + "supervisor.runtime.require=lambda **kwargs: None\n"
        + f"supervisor.OP=Path({str(op)!r})\n"
        + "original=supervisor.invoke\n"
        + f"timeout={timeout!r}\n"
        + "def bounded(run):\n"
        + " if run.argv[1:3] == ['run','--']: run=replace(run,timeout=timeout,deadline=None)\n"
        + " return original(run)\n"
        + "supervisor.invoke=bounded\n"
        + "raise SystemExit(supervisor.main([]))\n"
    )
    return subprocess.Popen(
        [sys.executable, str(script)],
        env=RUNNER_ENV,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        process_group=0,
    )


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def _finish(process, ready, ending):
    descendants, deadline = None, time.monotonic() + 5
    while descendants is None and process.poll() is None and time.monotonic() < deadline:
        # The file exists before its content does, so only parsed content counts as ready.
        with suppress(FileNotFoundError, ValueError):
            descendants = json.loads(ready.read_text())
            break
        time.sleep(0.02)
    assert descendants is not None, "stub chain did not start"
    if ending != "timeout":
        os.killpg(process.pid, ending)
    process.wait(timeout=5)
    deadline = time.monotonic() + 2
    while any(_alive(pid) for pid in descendants) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not any(_alive(pid) for pid in descendants)
    return process.communicate(timeout=1)


@pytest.mark.parametrize("ending", [signal.SIGTERM, signal.SIGHUP, "timeout"])
def test_cancel_and_outer_timeout_leave_no_consumer_or_http_child(tmp_path, ending):
    data = profile()
    del data["password_ref"], data["certificate_document"]
    ready, op = _op_stub(tmp_path, data)
    process = _runner(tmp_path, data, op, 1.5 if ending == "timeout" else 30)
    stdout, stderr = _finish(process, ready, ending)
    if ending == "timeout":
        assert json.loads(stdout)["result"] == "ACTION_TIMEOUT"
    assert not stderr


def test_unicode_page_stays_within_the_bounded_nested_transport():
    value = "é" * 400000
    code = (
        "import json; print(json.dumps({'result':'CONFLUENCE_FETCH_PASS',"
        + "'body_storage':'é'*400000}, ensure_ascii=False))"
    )
    result = invoke(Run([sys.executable, "-c", code], {"PATH": "/usr/bin:/bin"}))
    assert json.loads(result)["body_storage"] == value
    assert len(result) < 1024 * 1024
