"""Kickoff text and its files: what the session receives and what a gone session leaves."""

from pathlib import Path

from slopmeister.launch import kickoff
from slopmeister.launch.model import Launch
from slopmeister.session import launch_identity


def _launch(tmp_path: Path, monkeypatch, tool: str = "claude") -> Launch:
    monkeypatch.setenv("PLOT_SESSION_STATE_DIR", str(tmp_path / "state"))
    (tmp_path / "state").mkdir(exist_ok=True)
    return Launch("example-client", "example-client-wt1", "", tool=tool)


def test_codex_kickoff_opens_with_the_session_name(tmp_path, monkeypatch):
    """Bug: a Codex thread is named from the brief because Codex has no name flag."""
    launch = _launch(tmp_path, monkeypatch, "codex")
    launch.issue = ""
    monkeypatch.setattr(kickoff, "_source", lambda _: "brief")
    kickoff.resolve(launch)
    assert launch.kickoff == "example-client-wt1\n\nbrief"


def test_receipt_counts_the_delivered_bytes(tmp_path, monkeypatch):
    """Bug: the receipt counts the file's trailing newline the session never receives."""
    launch = _launch(tmp_path, monkeypatch)
    launch.kickoff = "héllo"
    kickoff.write(launch)
    assert launch.kickoff_file.read_bytes() == "héllo\n".encode()
    assert kickoff.receipt(launch).startswith("delivered (6 bytes, sha256 ")


def test_stale_kickoff_pairs_pruned(tmp_path, monkeypatch, capsys):
    """Bug: dead sessions accumulate kickoff and handle files, or a live session loses them."""
    launch = _launch(tmp_path, monkeypatch)
    live = tmp_path / "live dir's"
    live.mkdir()
    monkeypatch.setattr(launch_identity, "state_home", lambda: tmp_path / "identities")
    for name, workspace in (("gone", tmp_path / "gone"), ("live", live)):
        identity = launch_identity.path(workspace)
        identity.parent.mkdir(parents=True, exist_ok=True)
        identity.write_text(name)
        quoted = str(workspace).replace("'", "'\\''")
        (launch.state_dir / f"{name}.md").write_text("k\n")
        (launch.state_dir / f"{name}.orca").write_text("term_1\n")
        (launch.state_dir / f"{name}.command").write_text(
            f"#!/bin/zsh -l\ncd '{quoted}' && exec tool\n"
        )
    kickoff.prune(launch)
    kept = sorted(path.name for path in launch.state_dir.iterdir())
    assert kept == ["live.command", "live.md", "live.orca"]
    assert not launch_identity.path(tmp_path / "gone").exists()
    assert launch_identity.path(live).read_text() == "live"
    assert "pruned 1 stale kickoff and command file pairs" in capsys.readouterr().out
