"""The installed op as a session runs it, with a stand-in real op and a stand-in Home Assistant."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import threading

import pytest

from slopmeister.session import secret_approval, secret_tier
from slopmeister.workstation import manifest
from tests.support.fakes import fake_binary

ROOT = Path(__file__).resolve().parents[3]
ONE, TWO = "ops_tier-one-synthetic", "ops_tier-two-synthetic"
LISTS = {
    "tier-one": [{"id": "idone", "name": "Everyday"}],
    "tier-two": [{"id": "idone", "name": "Everyday"}, {"id": "idtwo", "name": "Production"}],
}
# The stand-in records how it was called, then runs the command as the real op run does.
REAL_OP = (
    'echo "$* token=${OP_SERVICE_ACCOUNT_TOKEN:-none}" >> "$HOME/real-op.log"\n'
    'if [ "$1" = run ]; then shift; while [ "$1" != -- ]; do shift; done; shift; exec "$@"; fi'
)
CHILD = ["sh", "-c", 'echo "CHILD token=${OP_SERVICE_ACCOUNT_TOKEN:-absent} demo=$DEMO"']


class HomeAssistant(BaseHTTPRequestHandler):
    """Records each question and answers it at once with the test's verdict."""

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.asked.append(body)
        self.server.decisions[body["id"]] = self.server.verdict
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps({"attributes": {"decisions": self.server.decisions}}).encode())

    def log_message(self, *args):
        pass


def private(path: Path, text: str) -> None:
    path.write_text(text)
    path.chmod(0o600)


def installed(tmp_path: Path) -> tuple[Path, str]:
    """A home with the op library the installer copies, and a PATH with this op before the real."""
    home = tmp_path / "home"
    for entry in manifest.COMMON:
        if entry.destination.startswith(manifest.OP_LIBRARY):
            target = home / entry.destination
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / entry.source, target)
    own = home / ".local/bin/op"
    own.parent.mkdir(parents=True)
    text = (ROOT / "plots/home/bin/op").read_text()
    text = re.sub(
        r"for python in [^\n]+; do",
        f"for python in {shlex.quote(sys.executable)}; do",
        text,
        count=1,
    )
    own.write_text(text)
    own.chmod(0o755)
    fake_binary(tmp_path / "real", "op", REAL_OP)
    return home, f"{own.parent}:{tmp_path / 'real'}:/usr/bin:/bin"


def machine_files(home: Path, port: int) -> None:
    """Both tokens, the tier lists, the route and one env file per tier."""
    files = home / secret_tier.DIRECTORY
    files.mkdir(parents=True)
    base = f"http://127.0.0.1:{port}"
    route = {"ask_url": base + "/ask", "answer_url": base + "/answer", "token": "read"}
    private(files / "tier-one.token", ONE + "\n")
    private(files / "tier-two.token", TWO + "\n")
    private(files / secret_tier.LISTS, json.dumps(LISTS))
    private(files / secret_approval.SETTINGS, json.dumps(route))
    (home / "one.env").write_text("DEMO=op://Everyday/Item/credential\n")
    (home / "two.env").write_text("DEMO=op://Production/Item/credential\n")


@pytest.fixture
def machine(tmp_path):
    """The installed op on a machine with its files, and Home Assistant answering as told."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), HomeAssistant)
    server.asked, server.decisions, server.verdict = [], {}, "approved"
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    server.home, server.path = installed(tmp_path)
    machine_files(server.home, server.server_port)
    yield server
    server.shutdown()
    thread.join()
    server.server_close()


def op(machine, *args: str) -> subprocess.CompletedProcess[str]:
    env = {"HOME": str(machine.home), "PATH": machine.path, "SLOPMEISTER_SECRET_BROKER": "1"}
    env["SECRET_ASK_REASON"] = "Deploy the host"
    return subprocess.run(
        ["op", *args], capture_output=True, text=True, env=env, cwd=machine.home, timeout=30
    )


def real_calls(machine) -> list[str]:
    log = machine.home / "real-op.log"
    return log.read_text().splitlines() if log.exists() else []


def test_tier_one_reaches_the_command_without_a_question_or_the_token(machine):
    """Bug: an everyday secret asks the phone, or the command can read the service token."""
    done = op(machine, "run", "--env-file=one.env", "--", *CHILD)
    assert done.returncode == 0, done.stderr
    assert done.stdout == "CHILD token=absent demo=op://Everyday/Item/credential\n"
    (call,) = real_calls(machine)
    assert call.startswith("run -- /usr/bin/env -u OP_SERVICE_ACCOUNT_TOKEN sh -c")
    assert call.endswith(f"token={ONE}")
    assert machine.asked == []


def test_tier_two_needs_the_word_and_then_the_approval(machine):
    """Bug: a production secret resolves without the operator's word, or without the phone."""
    plain = op(machine, "run", "--env-file=two.env", "--", *CHILD)
    assert plain.returncode == 1 and "op tier-two -- <command>" in plain.stderr
    assert real_calls(machine) == [] and machine.asked == []
    done = op(machine, "tier-two", "--", "op", "run", "--env-file=two.env", "--", *CHILD)
    assert done.returncode == 0, done.stderr
    assert done.stdout == "CHILD token=absent demo=op://Production/Item/credential\n"
    assert real_calls(machine)[0].endswith(f"token={TWO}")
    (asked,) = machine.asked
    assert "References: DEMO=op://Production/Item/credential" in asked["message"]
    assert f"request {asked['id']} waits for Home Assistant approval" in done.stderr


def test_denial_starts_nothing(machine):
    """Bug: the operator presses Deny and the command runs anyway."""
    machine.verdict = "denied"
    done = op(machine, "tier-two", "--", "op", "run", "--env-file=two.env", "--", *CHILD)
    assert done.returncode == 1 and done.stdout == ""
    assert f"request {machine.asked[0]['id']} denied" in done.stderr
    assert real_calls(machine) == []


def test_route_word_inside_an_op_run_is_refused(machine):
    """Bug: op run -- op tier-two passes the tools' allow rule and still counts as the word."""
    done = op(
        machine,
        "run",
        "--",
        "op",
        "tier-two",
        "--",
        "op",
        "run",
        "--env-file=two.env",
        "--",
        *CHILD,
    )
    assert done.returncode == 1 and "must be the outermost command" in done.stderr
    assert real_calls(machine) == [] and machine.asked == []


def test_desktop_route_uses_no_token_and_no_home_assistant(machine):
    """Bug: the ordered desktop route still depends on a token file or on Home Assistant."""
    for name in ("tier-one.token", "tier-two.token", secret_tier.LISTS, secret_approval.SETTINGS):
        (machine.home / secret_tier.DIRECTORY / name).unlink()
    done = op(machine, "desktop", "--", "op", "run", "--env-file=two.env", "--", *CHILD)
    assert done.returncode == 0, done.stderr
    assert real_calls(machine) == [f"run --env-file=two.env -- {' '.join(CHILD)} token=none"]
    assert machine.asked == []


def test_token_file_others_can_read_is_refused(machine):
    """Bug: a token file with loose permissions is used as if it were private."""
    os.chmod(machine.home / secret_tier.DIRECTORY / "tier-one.token", 0o644)
    done = op(machine, "run", "--env-file=one.env", "--", *CHILD)
    assert (
        done.returncode == 1 and "must be a regular file of this user with mode 600" in done.stderr
    )
    assert real_calls(machine) == []
