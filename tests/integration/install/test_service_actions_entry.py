"""The absolute selected-read entry passes raw argv to the fixed supervisor."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

from tests.integration.install.helpers import ROOT, profile

SOURCE = ROOT / "slopmeister/session/service_actions"
PYTHON = (sys.executable, "-E", "-s", "-S")


def test_direct_entry_keeps_selectors_literal_before_credentials(tmp_path):
    """Bug: Task expands an approved literal into an environment secret before provider access."""
    action = tmp_path / "action"
    shutil.copytree(SOURCE, action / "service_actions")
    shutil.copyfile(SOURCE / "entry.py", action / "entry.py")
    (action / "service_actions/runtime.py").write_text("def require(**_kwargs): pass\n")
    data = profile() | {"token_file": str(tmp_path / "missing-service.env")}
    (action / "config.json").write_text(json.dumps(data))
    entry = action / "entry.py"
    output = tmp_path / "result.json"
    output.write_bytes(b"")
    output.chmod(0o600)

    def run(*selector):
        output.write_bytes(b"")
        return subprocess.run(
            [*PYTHON, str(entry), "--output", str(output), *selector],
            env=dict(os.environ, RV340_SECRET="s3cr3t-demo"),
            capture_output=True,
            text=True,
            timeout=15,
        )

    valid = run("--find", "--text", "{{.RV340_SECRET}}")
    assert valid.returncode != 0
    assert json.loads(output.read_text())["result"] == "LOCAL_CREDENTIAL_NOT_PROVISIONED"
    assert "s3cr3t-demo" not in valid.stdout + valid.stderr + output.read_text()
    invalid = run("unexpected")
    assert invalid.returncode != 0
    assert json.loads(output.read_text())["result"] == "ARGUMENTS_NOT_SUPPORTED"


@pytest.mark.parametrize("unsafe", ["symlink", "permissions", "nonempty", "hardlink"])
def test_direct_entry_refuses_unsafe_result_file_before_any_provider(tmp_path, unsafe):
    """Bug: a selected read overwrites a linked, shared or prior result file."""
    action = tmp_path / "action"
    shutil.copytree(SOURCE, action / "service_actions")
    shutil.copyfile(SOURCE / "entry.py", action / "entry.py")
    output = tmp_path / "result.json"
    output.write_bytes(b"CANARY" if unsafe == "nonempty" else b"")
    output.chmod(0o644 if unsafe == "permissions" else 0o600)
    if unsafe in ("symlink", "hardlink"):
        target = tmp_path / "target.json"
        output.rename(target)
        if unsafe == "symlink":
            output.symlink_to(target)
        else:
            os.link(target, output)
    result = subprocess.run(
        [*PYTHON, str(action / "entry.py"), "--output", str(output), "--issue", "TEST-7"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode != 0
    assert json.loads(result.stdout)["result"] == "OUTPUT_FILE_UNSAFE"
    assert output.read_bytes() == (b"CANARY" if unsafe == "nonempty" else b"")


def test_direct_entry_captures_complete_large_result_without_tool_output(tmp_path):
    """Bug: removing the worker truncates a 2 MiB result or leaks it to the tool window."""
    action = tmp_path / "action"
    package = action / "service_actions"
    package.mkdir(parents=True)
    shutil.copyfile(SOURCE / "entry.py", action / "entry.py")
    (package / "__init__.py").write_text("")
    (package / "supervisor.py").write_text(
        "import sys\n"
        "def main(argv, direct=False):\n"
        '    prefix = b\'{"result":"SYNTHETIC_PASS","data":"\'\n'
        "    suffix = b'\"}\\n'\n"
        "    blob = prefix + b'x' * (2097152 - len(prefix) - len(suffix)) + suffix\n"
        "    sys.stdout.buffer.write(blob)\n"
        "    return 0\n"
    )
    output = tmp_path / "result.json"
    output.write_bytes(b"")
    output.chmod(0o600)
    result = subprocess.run(
        [*PYTHON, str(action / "entry.py"), "--output", str(output), "--issue", "TEST-7"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0 and result.stdout == "" and result.stderr == ""
    assert output.stat().st_size == 2097152 and output.stat().st_mode & 0o777 == 0o600
    assert json.loads(output.read_bytes())["result"] == "SYNTHETIC_PASS"


def test_rendered_result_directory_is_admitted_without_a_symlink_parent(tmp_path):
    """Bug: the rendered mktemp command gives Mac sessions a result path the entry refuses."""
    instruction = (ROOT / "src/service-actions/instructions.md").read_text()
    commands = re.findall(r"/usr/bin/mktemp -d (/[^`\s]+)", instruction)
    template = commands[0 if sys.platform == "darwin" else -1]
    directory = subprocess.check_output(["/usr/bin/mktemp", "-d", template], text=True).strip()
    pattern = directory + "/result.XXXXXXXX"
    output = Path(subprocess.check_output(["/usr/bin/mktemp", pattern], text=True).strip())
    action = tmp_path / "action"
    package = action / "service_actions"
    shutil.copytree(SOURCE, package)
    shutil.copyfile(SOURCE / "entry.py", action / "entry.py")
    (package / "supervisor.py").write_text(
        "def main(*args, **kwargs):\n print('PATH_ADMITTED'); return 0\n"
    )
    try:
        result = subprocess.run(
            [*PYTHON, str(action / "entry.py"), "--output", str(output), "--issue", "TEST-7"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert output.read_text() == "PATH_ADMITTED\n"
    finally:
        assert output.read_bytes() in (b"", b"PATH_ADMITTED\n")
        output.unlink()
        Path(directory).rmdir()
