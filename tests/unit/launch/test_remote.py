"""Remote dispatch must not prepare a workspace on the calling machine."""

import io
import shlex
import subprocess

import pytest

from slopmeister.launch import cli
from slopmeister.slots import up


@pytest.fixture(autouse=True)
def dedicated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    config = tmp_path / ".ssh/slopmeister-remote.conf"
    config.parent.mkdir()
    config.write_text("Host remote-box\nHost box\n")


@pytest.mark.parametrize(
    "entry,args",
    [
        (cli.main, ["~/repo", "example-client", "example-client-one"]),
        (up.main, ["~/repo", "example-client", "example-client-one"]),
    ],
)
@pytest.mark.parametrize("host_args", [["--host", "remote-box"], ["--host=remote-box"]])
def test_remote_dispatch_precedes_local_repository_and_slot_resolution(
    monkeypatch, entry, args, host_args
):
    """Bug: --host reaches local path resolution or allocates local resources."""
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, "remote-ready\n", "")

    def local(*args):
        pytest.fail("remote request reached local preparation")

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(cli, "_validate", local)
    monkeypatch.setattr(up, "_context", local)
    monkeypatch.setattr("sys.stdin", io.StringIO("Mode: freeform\nUnicode: ä\n"))
    assert entry([*args, *host_args, "--tool", "codex"]) == 0
    assert len(calls) == 2
    assert all(call[0][0] == "ssh" for call in calls)
    assert "remote-box" in calls[1][0]
    assert "'~/repo'" in shlex.split(calls[1][0][-1])[-1]


def test_post_open_diagnostic_failure_keeps_may_be_live(monkeypatch):
    """Bug: a closed SSH stderr makes the slot caller roll back a live worker."""
    from slopmeister.launch.model import Launch

    launch = Launch("example-client", "example-client-one", "/repo")
    launch.open_attempted = True

    def fail(*args):
        raise BrokenPipeError("closed output")

    monkeypatch.setattr(cli, "_validate", lambda *args: launch)
    monkeypatch.setattr(cli, "_launch", fail)
    monkeypatch.setattr(cli.traceback, "print_exception", fail)
    assert cli.run([]) == (1, True)


@pytest.mark.parametrize(
    "args",
    [
        ["--host"],
        ["--host", "-F"],
        ["--host", "x;touch BAD"],
        ["--host", "box", "--host", "other"],
        ["--host", "box\nother"],
    ],
)
def test_invalid_host_never_reaches_ssh(monkeypatch, args):
    """Bug: an alias becomes an SSH option or shell expression."""
    from slopmeister.errors import UsageError
    from slopmeister.launch import remote

    def forbidden(*args, **kwargs):
        pytest.fail("invalid host reached SSH")

    monkeypatch.setattr(subprocess, "run", forbidden)
    with pytest.raises(UsageError, match="dedicated SSH alias"):
        remote.launch(["example-client", "example-client-one", *args], ["plot-session"])


def test_native_tool_host_flag_is_not_a_remote_destination():
    """Bug: a native tool's --host after the separator retargets the launcher."""
    from slopmeister.launch import remote

    args = ["example-client", "example-client-one", "--", "--host", "tool-value"]
    assert remote.selected(args) == ("", args)


@pytest.mark.parametrize("failure", [OSError("missing ssh"), subprocess.TimeoutExpired("ssh", 45)])
def test_preflight_errors_never_start_launch(monkeypatch, failure):
    """Bug: an unavailable SSH binary or timeout falls through to launching."""
    from slopmeister.errors import SlopmeisterError
    from slopmeister.launch import remote

    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(SlopmeisterError, match="nothing launched"):
        remote.launch(["example-client", "example-client-one", "--host", "box"], ["plot-session"])


def test_post_open_stop_with_closed_stderr_keeps_resources(monkeypatch):
    """Bug: a failed delivery diagnostic enters the slot rollback after opening a worker."""
    from slopmeister.launch.model import Launch, Stop

    launch = Launch("example-client", "example-client-one", "/repo")
    launch.open_attempted = True

    class Closed(io.StringIO):
        def write(self, value):
            raise BrokenPipeError("SSH disconnected")

    def stop(*args):
        raise Stop(1, "delivery unconfirmed")

    monkeypatch.setattr(cli, "_validate", lambda *args: launch)
    monkeypatch.setattr(cli, "_launch", stop)
    monkeypatch.setattr("sys.stderr", Closed())
    assert cli.run([]) == (1, True)


@pytest.mark.parametrize("entry", [cli.main, up.main])
def test_undeclared_alias_never_uses_default_ssh_identity(monkeypatch, entry):
    """Bug: an undeclared alias falls back to the user's default keys and known hosts."""
    from slopmeister.errors import UsageError

    def forbidden(*args, **kwargs):
        pytest.fail("undeclared alias reached SSH")

    monkeypatch.setattr(subprocess, "run", forbidden)
    with pytest.raises(UsageError, match="not declared"):
        entry(["~/repo", "example-client", "example-client-one", "--host", "otherbox"])
