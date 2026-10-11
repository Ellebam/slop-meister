"""The installed launcher must select its runtime without changing a consumer's Python setup."""

import json
import re
import subprocess
import sys

import pytest

from tests.integration.session.test_secret_run import ROOT, installed
from tests.integration.session.test_secret_run import machine as machine


def test_missing_fixed_interpreter_reports_the_required_version(tmp_path):
    """A PATH-only Python install must not make the shim execute an older system interpreter."""
    home, search = installed(tmp_path)
    own = home / ".local/bin/op"
    text = (ROOT / "plots/home/bin/op").read_text()
    text = re.sub(r"/[^ ]*/python3\.14", str(tmp_path / "missing-python3.14"), text)
    own.write_text(text)
    done = subprocess.run(
        [str(own), "--version"],
        env={"HOME": str(home), "PATH": search},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert done.returncode == 2
    assert done.stderr == "op: Python 3.14 is required at a fixed system path\n"
    assert not (home / "real-op.log").exists()


@pytest.mark.parametrize("route", ["run", "tier-two", "desktop"])
def test_consumer_keeps_its_python_environment_and_import_path(machine, route):
    """Python consumers still import their modules, while the launcher ignores caller imports."""
    modules = machine.home / "caller-modules"
    modules.mkdir()
    (modules / "consumer_input.py").write_text('VALUE = "caller-module"\n')
    shadow = modules / "slopmeister"
    shadow.mkdir()
    (shadow / "__init__.py").write_text('raise RuntimeError("caller shadow reached launcher")\n')
    code = (
        "import consumer_input,json,os; "
        "print(json.dumps([consumer_input.VALUE, os.environ['PYTHONPATH'], "
        "os.environ['PYTHONDONTWRITEBYTECODE'], os.environ.get('SLOPMEISTER_OP_LAUNCHER')]))"
    )
    command = ["op", "run", "--", sys.executable, "-c", code]
    if route != "run":
        command = ["op", route, "--", *command]
    env = {"HOME": str(machine.home), "PATH": machine.path, "SLOPMEISTER_SECRET_BROKER": "1"}
    env.update(PYTHONPATH=str(modules), PYTHONDONTWRITEBYTECODE="0")
    done = subprocess.run(
        command, cwd=machine.home, env=env, capture_output=True, text=True, timeout=10
    )
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == ["caller-module", str(modules), "0", None]
