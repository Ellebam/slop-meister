"""Launch admission and preparation failures against fake git and a fake supervisor start."""

import argparse
import json
from pathlib import Path
import subprocess
import time

import pytest

from slopmeister.spine.tester import launch, runs
from slopmeister.spine.tester.collect import collect


def _request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> argparse.Namespace:
    repo = tmp_path / "subject"
    repo.mkdir()
    guide, notes, defaults = (tmp_path / name for name in ("guide.md", "notes.md", "defaults.toml"))
    guide.write_text("### Scenario basic: Check subject\nRead subject.txt.\n")
    notes.write_text("\n## Validation\nOriginal proof.\n")
    defaults.write_text('[claude]\nmodel="fake-model"\neffort="high"\n')
    monkeypatch.setattr(launch, "DEFAULTS", defaults)
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    ticks = iter(range(1000))
    monkeypatch.setattr(time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    return argparse.Namespace(
        cwd=str(repo),
        commit="HEAD",
        guide=str(guide),
        validation=str(notes),
        worker_tool="codex",
        task="fixture",
    )


def _fake_git(failure: str):
    def fake_git(cwd, *args):
        if "--git-common-dir" in args:
            return str(Path(cwd) / ".git")
        if args[0] == "rev-parse":
            return "a" * 40
        if args[0] == "clone":
            if failure == "clone":
                raise subprocess.CalledProcessError(1, "git clone")
            Path(args[-1]).mkdir()
        return ""

    return fake_git


@pytest.mark.parametrize("failure", ["clone", "supervisor-start", "admission-unconfirmed"])
def test_launch_failure_distinguishes_unstarted_from_unconfirmed_supervisor(
    tmp_path, monkeypatch, failure
):
    args = _request(tmp_path, monkeypatch)

    def failed_start(*args, **kwargs):
        root = Path(args[0][-1])
        run = json.loads((root / "run.json").read_text())
        projects = json.loads((tmp_path / "home/.claude.json").read_text())["projects"]
        assert projects[run["checkout"]]["hasTrustDialogAccepted"] is True
        if failure == "admission-unconfirmed":
            return object()
        raise OSError("supervisor could not start")

    monkeypatch.setattr(runs, "git", _fake_git(failure))
    monkeypatch.setattr(subprocess, "Popen", failed_start)
    with pytest.raises((OSError, ValueError, subprocess.SubprocessError)):
        launch.launch(args)
    roots = list((tmp_path / "state/slopmeister/spine-tests").glob("run-*"))
    assert len(roots) == 1
    if failure == "admission-unconfirmed":
        assert not (roots[0] / "result.json").exists()
        assert collect(roots[0], 0) == 3
        return
    assert collect(roots[0], 0) == 1
    assert json.loads((roots[0] / "result.json").read_text())["status"] == "blocked"
    assert "Tester BLOCKED" in (roots[0] / "report.md").read_text()


def test_trust_refusal_persists_blocked_receipt_before_supervisor_start(tmp_path, monkeypatch):
    """A native trust refusal must remain diagnosable after the launcher exits."""
    args = _request(tmp_path, monkeypatch)
    monkeypatch.setattr(runs, "git", _fake_git("trust"))

    def refuse_trust(*args, **kwargs):
        raise SystemExit("trust write refused")

    def unexpected_start(*args, **kwargs):
        pytest.fail("supervisor started without checkout trust")

    monkeypatch.setattr(launch, "trust", refuse_trust)
    monkeypatch.setattr(subprocess, "Popen", unexpected_start)
    with pytest.raises(SystemExit, match="trust write refused"):
        launch.launch(args)
    roots = list((tmp_path / "state/slopmeister/spine-tests").glob("run-*"))
    assert len(roots) == 1
    assert collect(roots[0], 0) == 1
    assert json.loads((roots[0] / "result.json").read_text())["status"] == "blocked"
    assert "trust write refused" in (roots[0] / "report.md").read_text()
