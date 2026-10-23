"""The launcher cannot open a worker or release a workspace past an unsafe native preflight."""

from types import SimpleNamespace

import pytest

from slopmeister.launch import cli
from slopmeister.launch.model import Delivery, Launch, Stop


def test_native_refusal_precedes_opening_the_worker(tmp_path, monkeypatch):
    monkeypatch.setenv("PLOT_SESSION_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("PLOT_SESSION_NO_LAUNCH", raising=False)
    launch = Launch("scratch", "scratch-one", "", wt=tmp_path)
    monkeypatch.setattr(cli, "_prepare", lambda _: None)
    monkeypatch.setattr(cli.report, "prepare_identity", lambda _: None)
    monkeypatch.setattr(cli.command, "line", lambda _: "true")
    monkeypatch.setattr(cli.command, "write", lambda _: None)
    opened = []
    monkeypatch.setattr(cli, "_open", lambda _: opened.append(True))
    monkeypatch.setattr(cli.confirm, "deliver", lambda *_: Delivery(123))
    monkeypatch.setattr(cli, "_finish_delivery", lambda *_: None)

    def refused(_):
        raise Stop(1, "native fixture refused")

    monkeypatch.setattr(cli, "native_check", SimpleNamespace(check=refused))
    with pytest.raises(Stop, match="native fixture refused"):
        cli._launch(launch)
    assert not opened


def test_unknown_native_cleanup_retains_the_prepared_workspace(tmp_path, monkeypatch):
    launch = Launch("scratch", "scratch-one", "", wt=tmp_path)
    monkeypatch.setattr(cli, "_validate", lambda *_: launch)

    def stopped(*_):
        launch.native_pending = True
        raise Stop(1, "native cleanup unverified")

    monkeypatch.setattr(cli, "_launch", stopped)
    assert cli.run([]) == (1, True)


def test_redispatch_preflight_refusal_keeps_the_predecessor_and_saved_commands(
    tmp_path, monkeypatch
):
    launch = Launch("scratch", "scratch-one", "", wt=tmp_path, redispatch=True)
    monkeypatch.setenv("PLOT_SESSION_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("PLOT_SESSION_NO_LAUNCH", raising=False)
    launch.command_file.write_text("existing command\n")
    steps = []
    monkeypatch.setattr(cli.workspace, "adopt", lambda _: steps.append("verified"))
    monkeypatch.setattr(cli.workspace, "capabilities", lambda _: steps.append("saved capabilities"))
    monkeypatch.setattr(cli.closure, "close", lambda _: pytest.fail("predecessor closed"))
    monkeypatch.setattr(cli.workspace, "trust_write", lambda _: pytest.fail("trust rewritten"))

    def refused(_):
        steps.append("preflight")
        raise Stop(1, "native fixture refused")

    monkeypatch.setattr(cli.native_check, "check", refused)
    with pytest.raises(Stop, match="native fixture refused"):
        cli._redispatch(launch)
    assert steps == ["verified", "saved capabilities", "preflight"]
    assert launch.command_file.read_text() == "existing command\n"
