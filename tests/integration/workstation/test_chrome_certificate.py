"""The operator's certificate setup keeps the key out of arguments, files and agent sessions."""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "slopmeister/workstation/chrome_certificate.sh"
PASSWORD = "dummy-private-password"
STUBS = {
    "uname": 'echo "${FAKE_UNAME:-Linux}"',
    "op": f"""echo "op $*" >> "$LOG"
if [ "$1" = document ]; then
    while [ "$#" -gt 1 ]; do
        if [ "$1" = --out-file ]; then echo key > "$2"; dirname "$2" > "$LOG.dir"; fi
        shift
    done
else
    printf %s {PASSWORD}
fi""",
    "certutil": 'echo "certutil $*" >> "$LOG"; touch "$HOME/.pki/nssdb/cert9.db"',
    "pk12util": """echo "pk12util $*" >> "$LOG"
while [ "$#" -gt 0 ]; do [ "$1" = -w ] && cat "$2" > "$LOG.password"; shift; done""",
    "sudo": 'echo "sudo $*" >> "$LOG"; cat > "$LOG.policy"',
}


@pytest.fixture
def run(tmp_path):
    stubs = tmp_path / "bin"
    stubs.mkdir()
    for name, body in STUBS.items():
        path = stubs / name
        path.write_text("#!/bin/bash\n" + body + "\n")
        path.chmod(0o755)
    log = tmp_path / "log"

    def execute(*arguments, **extra):
        env = {
            "PATH": f"{stubs}:/usr/bin:/bin",
            "HOME": str(tmp_path),
            "LOG": str(log),
            "TMPDIR": str(tmp_path),
            **extra,
        }
        return subprocess.run(
            ["bash", str(SCRIPT), *arguments], capture_output=True, text=True, env=env
        )

    return execute, log, tmp_path


ARGUMENTS = ("vault", "item", "https://[*.]example.com")


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_key_reaches_the_store_through_a_pipe_and_the_file_is_removed(run):
    execute, log, home = run
    done = execute(*ARGUMENTS)
    assert done.returncode == 0, done.stderr
    calls = log.read_text()
    assert PASSWORD not in calls + done.stdout + done.stderr
    assert Path(str(log) + ".password").read_text() == PASSWORD
    assert "certutil -d sql:" in calls and "op document get item --vault vault" in calls
    private = Path(Path(str(log) + ".dir").read_text().strip())
    assert not private.exists(), "the private directory must be gone"
    assert not (home / ".pki/nssdb").stat().st_mode & 0o077


def test_chrome_gets_a_rule_for_that_pattern_only(run):
    execute, log, _ = run
    assert execute(*ARGUMENTS).returncode == 0
    policy = json.loads(Path(str(log) + ".policy").read_text())
    rule = json.loads(policy["AutoSelectCertificateForUrls"][0])
    assert rule == {"pattern": "https://[*.]example.com", "filter": {}}


def test_an_existing_store_is_kept(run):
    execute, log, home = run
    store = home / ".pki/nssdb"
    store.mkdir(parents=True)
    (store / "cert9.db").write_text("kept")
    assert execute(*ARGUMENTS).returncode == 0
    assert "certutil" not in log.read_text() and (store / "cert9.db").read_text() == "kept"


@pytest.mark.parametrize(
    ("arguments", "extra", "message"),
    [
        (ARGUMENTS, {"SLOPMEISTER_SECRET_BROKER": "1"}, "not in an agent session"),
        (ARGUMENTS, {"FAKE_UNAME": "Darwin"}, "Keychain Access"),
        (ARGUMENTS[:2], {}, "usage:"),
    ],
)
def test_refusals_touch_nothing(run, arguments, extra, message):
    execute, log, _ = run
    done = execute(*arguments, **extra)
    assert done.returncode == 2 and message in done.stderr
    assert not log.exists()


def test_the_script_stays_executable():
    assert os.access(SCRIPT, os.X_OK)
