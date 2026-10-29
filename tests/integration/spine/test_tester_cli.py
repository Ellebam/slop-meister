"""The tester driven as its user: detached launch and draft checks."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
import uuid

import pytest

from slopmeister.spine.tester import cli
from slopmeister.spine.tester import collect as collection
from slopmeister.spine.tester.collect import collect
from tests.support.repos import git

ROOT = Path(__file__).resolve().parents[3]
ENTRY = ROOT / "bin/slopmeister"
RESULT_SECONDS = 10
LAUNCHER = """import argparse, pathlib, sys
sys.path.insert(0, sys.argv[1])
from slopmeister.spine.tester import launch
launch.DEFAULTS = pathlib.Path(sys.argv[2])
cwd, commit, guide, validation = sys.argv[3:7]
print(launch.launch(argparse.Namespace(cwd=cwd, commit=commit, guide=guide, validation=validation,
                                       worker_tool="codex", task="fixture")))
"""


def validate(root: Path, draft: Path) -> subprocess.CompletedProcess:
    command = [sys.executable, str(ENTRY), "tester", "validate", "--run", str(root)]
    return subprocess.run([*command, "--draft", str(draft)], capture_output=True, text=True)


def _subject(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "subject"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "subject.txt").write_text("committed subject")
    git(repo, "add", "subject.txt")
    git(repo, "commit", "-qm", "Create disposable subject")
    commit = git(repo, "rev-parse", "HEAD").strip()
    (repo / "subject.txt").write_text("uncommitted worker bytes")
    return repo, commit


def _fake_claude(tmp_path: Path) -> None:
    binary = tmp_path / "claude"
    init = json.dumps({"type": "system", "subtype": "init", "session_id": str(uuid.uuid4())})
    binary.write_text(
        f"#!{sys.executable}\nimport json,time,pathlib\n"
        'config=json.loads((pathlib.Path.home()/".claude.json").read_text())\n'
        'assert config["projects"][str(pathlib.Path.cwd())]["hasTrustDialogAccepted"] is True\n'
        "time.sleep(0.3)\n"
        f"print({init!r})\n"
        'print(json.dumps({"type":"result","is_error":False,"structured_output":{}}))\n'
        'pathlib.Path("../evidence/subject.txt").write_text(pathlib.Path("subject.txt").read_text())\n'
    )
    binary.chmod(0o700)


def _fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home


def _assert_trusted(checkout: Path, home: Path) -> None:
    projects = json.loads((home / ".claude.json").read_text())["projects"]
    assert projects[str(checkout)]["hasTrustDialogAccepted"] is True


def _launch(repo: Path, commit: str, guide: Path, notes: Path, defaults: Path) -> Path:
    arguments = [str(ROOT), str(defaults), str(repo), commit, str(guide), str(notes)]
    launcher = [sys.executable, "-c", LAUNCHER, *arguments]
    result = subprocess.run(launcher, capture_output=True, text=True, timeout=15, check=True)
    return Path(result.stdout.strip())


def test_detached_tester_survives_launcher_exit_and_collect_is_idempotent(tmp_path, monkeypatch):
    """The isolated checkout must be trusted before Claude starts inside it."""
    repo, commit = _subject(tmp_path)
    fake_home = _fake_home(tmp_path, monkeypatch)
    guide, notes, defaults = (tmp_path / name for name in ("guide.md", "notes.md", "defaults.toml"))
    guide.write_text("### Scenario basic: Check subject\nRead subject.txt.\n")
    notes.write_text("\n## Validation\nCheck the committed bytes.\n")
    defaults.write_text('[claude]\nmodel="fake-model"\neffort="high"\n')
    _fake_claude(tmp_path)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = _launch(repo, commit, guide, notes, defaults)
    _assert_trusted(root / "checkout", fake_home)
    deadline = time.monotonic() + RESULT_SECONDS
    while (
        not (root / "result.json").exists() or (root / "checkout").exists()
    ) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not (root / "checkout").exists()
    assert (root / "evidence/subject.txt").read_text() == "committed subject"
    assert (repo / "subject.txt").read_text() == "uncommitted worker bytes"
    result = json.loads((root / "result.json").read_text())
    assert result["tool"] == "claude" and result["commit"] == commit
    # A fake CLI has no genuine native record and must never become a passing acceptance.
    assert result["status"] == "blocked"
    assert "native session record" in (root / "report.md").read_text()
    before = (root / "result.json").read_bytes()
    assert collect(root, 0) == collect(root, 0) == 1
    assert (root / "result.json").read_bytes() == before


@pytest.mark.parametrize("outcome", ["pass", "fail", "blocked"])
def test_draft_command_preserves_outcome_and_all_run_bytes(tmp_path, verdict, outcome):
    """A valid draft is not a successful test, nor permission to rewrite receipts."""
    verdict["scenarios"][0]["verdict"] = outcome
    (tmp_path / "run.json").write_text(json.dumps({"required": ["basic"]}))
    (tmp_path / "draft.json").write_text(json.dumps(verdict))
    (tmp_path / "result.json").write_text('{"status": "blocked"}')
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    result = validate(tmp_path, tmp_path / "draft.json")
    assert result.returncode == 0 and not result.stderr
    assert result.stdout == f"VALID DRAFT (outcome: {outcome}; not test proof)\n"
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


@pytest.mark.parametrize("seconds", [300, 301])
def test_collect_five_minute_deadline_and_early_result(tmp_path, monkeypatch, capsys, seconds):
    elapsed = [0.0]
    clock = SimpleNamespace(
        monotonic=lambda: elapsed[0], sleep=lambda n: elapsed.__setitem__(0, elapsed[0] + n)
    )
    monkeypatch.setattr(collection, "time", clock)
    (tmp_path / "accepted.json").write_text(json.dumps({"supervisor_pid": os.getpid()}))
    command = ["collect", "--run", str(tmp_path), "--wait-seconds", str(seconds)]
    status = cli.main(command)
    output = capsys.readouterr()
    if seconds == 301:
        assert status == 1 and "between 0 and 300 seconds" in output.err
        assert elapsed == [0.0]
        return
    assert status == 3 and "PENDING" in output.out
    assert 300 <= elapsed[0] < 300.1
    (tmp_path / "result.json").write_text('{"exit_code":0}')
    (tmp_path / "report.md").write_text("saved report\n")
    before = elapsed[0]
    assert cli.main(command) == 0 and elapsed[0] == before
    assert capsys.readouterr().out == "saved report\n"
