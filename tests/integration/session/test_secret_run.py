"""The shim and the broker together: values reach the command once, never the output."""

from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import threading

import pytest

from slopmeister.secret_ask.broker import Broker
from slopmeister.secret_ask.local import handle
from slopmeister.session import secret_run, secret_transport

pytestmark = pytest.mark.xdist_group("secret-ask-sockets")
SECRET = "synthetic-value-9f1c"
KEY = "-----BEGIN KEY-----\nline-one-of-key\nline-two-of-key\n-----END KEY-----"


def _serve(path, broker, stop, ready):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(path))
        listener.listen(8)
        listener.settimeout(0.1)
        ready.set()
        while not stop.is_set():
            try:
                client, _ = listener.accept()
            except TimeoutError:
                continue
            handle(client, broker, os.getuid())


@contextmanager
def served(tmp_path, monkeypatch):
    """A real broker behind a real socket, approvals driven by the test."""
    broker = Broker(tmp_path, "operator")
    # macOS caps socket paths at about a hundred characters, pytest's directory is longer.
    short = Path(tempfile.mkdtemp(prefix="sa-", dir="/tmp"))
    path = short / "control.sock"
    monkeypatch.setattr(secret_transport, "SOCKET", path)
    monkeypatch.setattr(secret_transport, "POLL_SECONDS", 0.05)
    monkeypatch.setenv(secret_run.MARK, "1")
    stop = threading.Event()
    # The shim falls back to the SSH route when the socket is not listening yet, so wait for it.
    ready = threading.Event()
    thread = threading.Thread(target=_serve, args=(path, broker, stop, ready))
    thread.start()
    try:
        assert ready.wait(timeout=5), "the fake broker never listened"
        yield broker
    finally:
        stop.set()
        thread.join(timeout=5)
        broker.close()
        shutil.rmtree(short, ignore_errors=True)


def approve(broker, values, stop):
    """Approve the first pending request and hand it values, as the daemon would."""
    while not stop.is_set():
        for row in broker.pending():
            approved = broker.decide(
                {"context": {"user_id": "operator"}, "data": {"action": row["approve"]}}
            )
            broker.ready(approved["id"], values)
            return
        stop.wait(0.05)


def run(args, broker, values, capfd):
    stop = threading.Event()
    helper = threading.Thread(target=approve, args=(broker, values, stop))
    helper.start()
    try:
        code = secret_run.main(["run", *args])
    finally:
        stop.set()
        helper.join(timeout=5)
    out, err = capfd.readouterr()
    return code, out, err


def test_approved_values_reach_the_command_masked_in_its_output(tmp_path, monkeypatch, capfd):
    """Bug: a resolved value prints in the tool output, or the command runs elsewhere."""
    (tmp_path / "x.env").write_text("TOKEN=op://Example/Item/credential\nPLAIN=kept\n")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    monkeypatch.chdir(tmp_path)
    program = (
        "import os, sys; open(os.path.expanduser('~/written'), 'w').write(os.environ['TOKEN']); "
        "print(os.getcwd()); print('token=' + os.environ['TOKEN']); "
        "print('plain=' + os.environ['PLAIN']); sys.stderr.write(os.environ['TOKEN'] + '\\n'); "
        "sys.exit(7)"
    )
    with served(tmp_path, monkeypatch) as broker:
        code, out, err = run(
            ["--env-file=x.env", "--", sys.executable, "-I", "-c", program],
            broker,
            {"TOKEN": SECRET},
            capfd,
        )
    assert code == 7
    assert SECRET not in out + err
    assert f"{tmp_path}\ntoken=<concealed by 1Password>\nplain=kept\n" == out
    assert "<concealed by 1Password>" in err and "waits for Home Assistant approval" in err
    assert (tmp_path / "home/written").read_text() == SECRET
    assert SECRET not in (tmp_path / "audit.log").read_text()
    assert SECRET not in (tmp_path / "requests.json").read_text()


def test_signal_terminated_command_exits_as_the_shell_reports(tmp_path, monkeypatch, capfd):
    """Bug: a command killed by a signal exits 241 through the shim where a shell reports 143."""
    assert secret_run.run(["/bin/sh", "-c", "kill -TERM $$"], {}, []) == 143
    assert secret_run.run(["/bin/sh", "-c", "exit 7"], {}, []) == 7


def test_multi_line_value_is_masked_line_by_line(tmp_path, monkeypatch, capfd):
    """Bug: an SSH key printed by a command shows every line but the first."""
    (tmp_path / "x.env").write_text("KEY=op://Example/Item/private_key?ssh-format=openssh\n")
    program = "import os; print(os.environ['KEY'])"
    with served(tmp_path, monkeypatch) as broker:
        code, out, _ = run(
            ["--env-file", str(tmp_path / "x.env"), "--", sys.executable, "-I", "-c", program],
            broker,
            {"KEY": KEY},
            capfd,
        )
    assert code == 0
    assert "line-one-of-key" not in out and "line-two-of-key" not in out
    assert out.count("<concealed by 1Password>") == 4


def test_rerun_of_the_same_command_reattaches_and_a_different_one_does_not(tmp_path, monkeypatch):
    """Bug: a tool timeout costs a second approval, or a different command rides an approval."""
    (tmp_path / "x.env").write_text("TOKEN=op://Example/Item/credential\n")
    monkeypatch.chdir(tmp_path)
    seen = []
    with served(tmp_path, monkeypatch) as broker:
        request = secret_run.request({"TOKEN": "op://Example/Item/credential"}, ["true"])
        first = secret_transport.exchange(secret_transport.SOCKET, {**request, "op": "run"})
        seen.append(first["id"])
        again = secret_transport.exchange(secret_transport.SOCKET, {**request, "op": "run"})
        other = secret_transport.exchange(
            secret_transport.SOCKET, {**request, "argv": ["false"], "op": "run"}
        )
        assert again["id"] == first["id"] and other["id"] != first["id"]
        assert len(broker.pending()) == 2


def test_denied_request_runs_nothing(tmp_path, monkeypatch, capfd):
    """Bug: a denial still runs the command, or exits zero."""
    (tmp_path / "x.env").write_text("TOKEN=op://Example/Item/credential\n")
    marker = tmp_path / "ran"

    def deny(broker):
        while not broker.pending():
            pass
        row = broker.pending()[0]
        broker.decide({"context": {"user_id": "operator"}, "data": {"action": row["deny"]}})

    with served(tmp_path, monkeypatch) as broker:
        helper = threading.Thread(target=deny, args=(broker,))
        helper.start()
        code = secret_run.main(
            ["run", "--env-file", str(tmp_path / "x.env"), "--", "touch", str(marker)]
        )
        helper.join(timeout=5)
    assert code == 1 and not marker.exists()
    assert "denied" in capfd.readouterr().err
    assert Path(tmp_path / "requests.json").exists()


RELAY = (
    "import sys; from pathlib import Path; from slopmeister.session import secret_transport as t; "
    "from slopmeister.secret_ask import cli; t.SOCKET = Path(sys.argv[1]); t.POLL_SECONDS = 0.05; "
    "sys.exit(cli.relay())"
)


def _route_through_relay(monkeypatch, tmp_path, socket_path):
    """The Mac path: no local socket, one SSH alias, and ssh replaced by the relay itself."""
    monkeypatch.setattr(secret_transport, "SOCKET", tmp_path / "absent.sock")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh/slopmeister-remote.conf").write_text("Host broker-box\n")
    relay = [sys.executable, "-c", RELAY, str(socket_path)]
    monkeypatch.setattr(secret_transport.remote_ssh, "argv", lambda home, alias, command: relay)
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[3]))


def test_mac_client_and_relay_settle_an_approval_through_real_pipes(tmp_path, monkeypatch, capfd):
    """Bug: the client closes the relay's input after the request, the relay reads that as the
    client leaving and stops before the decision, so no Mac request ever completes."""
    (tmp_path / "x.env").write_text("TOKEN=op://Example/Item/credential\n")
    program = "import os; print('relayed=' + os.environ['TOKEN'])"
    with served(tmp_path, monkeypatch) as broker:
        _route_through_relay(monkeypatch, tmp_path, secret_transport.SOCKET)
        code, out, err = run(
            ["--env-file", str(tmp_path / "x.env"), "--", sys.executable, "-I", "-c", program],
            broker,
            {"TOKEN": SECRET},
            capfd,
        )
    assert code == 0, err
    assert out == "relayed=<concealed by 1Password>\n"
    assert SECRET not in out + err and "waits for Home Assistant approval" in err
