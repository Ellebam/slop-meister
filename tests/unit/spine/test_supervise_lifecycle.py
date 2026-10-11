"""Supervisor record handling, timeouts and collection against a fake tester process."""

import json
import os
import subprocess
import time

import pytest

from slopmeister.spine.tester import process, runs
from slopmeister.spine.tester.collect import collect
from slopmeister.spine.tester.supervise import supervise
from slopmeister.spine.tester.validate import render_report, validate_verdict
from tests.unit.spine.conftest import GROUP


@pytest.mark.parametrize("separator", ["\u0085", "\u2028", "\u2029"])
@pytest.mark.parametrize("source", ["events", "native"])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_unicode_content_cannot_split_jsonl_records(supervised_run, separator, source, newline):
    root, world, native = supervised_run
    payload = "before" + separator + "after"
    world.newline = newline
    if source == "events":
        world.event_text = payload
    else:
        identity = json.loads(native.read_text())
        line = json.dumps({**identity, "fixture_text": payload}, ensure_ascii=False) + newline
        native.write_bytes(line.encode())
    assert supervise(root) == 0
    saved = json.loads((root / "result.json").read_text())
    assert saved["status"] == "pass"
    assert (saved["observed_model"], saved["observed_effort"]) == ("fake-model", "high")
    assert len(world.calls) == 1
    artifact = root / ("events.jsonl" if source == "events" else "native.jsonl")
    assert payload.encode() in artifact.read_bytes()


@pytest.mark.parametrize("source", ["events", "native"])
def test_jsonl_delimiter_fix_still_blocks_truncated_records(supervised_run, source):
    root, world, native = supervised_run
    truncated = '{"fixture_text":"unfinished'
    if source == "events":
        world.invalid_event = truncated
    else:
        with native.open("a") as stream:
            stream.write(truncated)
    assert supervise(root) == 1
    assert json.loads((root / "result.json").read_text())["status"] == "blocked"
    assert "Unterminated string" in (root / "report.md").read_text()
    assert not (root / "verdict.json").exists()


def test_tester_timeout_preserves_partial_evidence_and_stops_the_anchored_group(
    supervised_run, monkeypatch
):
    root, world, _ = supervised_run
    world.timeout = True
    stops = []
    monkeypatch.setattr(
        process.jobs, "stop_group", lambda child, anchored: stops.append((child.pid, anchored))
    )
    assert supervise(root) == 1
    result = json.loads((root / "result.json").read_text())
    assert result["status"] == "blocked"
    assert result["process_stopped"] is True
    assert not (root / "checkout").exists()
    assert stops == [(GROUP, True)] and not world.signals
    assert (root / "events.jsonl").stat().st_size > 0
    assert "timed out" in (root / "report.md").read_text()


def test_tester_timeout_cannot_claim_a_group_stopped_when_the_stop_fails(
    supervised_run, monkeypatch
):
    root, world, _ = supervised_run
    world.timeout = True

    def survive(child, anchored):
        raise RuntimeError("owned process group still active")

    monkeypatch.setattr(process.jobs, "stop_group", survive)
    assert supervise(root) == 1
    result = json.loads((root / "result.json").read_text())
    assert result["process_stopped"] is False
    assert (root / "checkout").is_dir()
    assert "unverified" in result["checkout_cleanup_error"]
    assert "unverified live group 123456789" in (root / "report.md").read_text()


@pytest.mark.parametrize("status", ["pass", "fail", "blocked"])
def test_supervisor_preserves_terminal_verdict_and_collects_exact_report(
    supervised_run, verdict, status, capsys
):
    root, world, _ = supervised_run
    (root / "evidence/retained.txt").write_text("retained proof")
    verdict["scenarios"][0]["verdict"] = status
    expected = 0 if status == "pass" else 1
    assert supervise(root) == expected
    result = json.loads((root / "result.json").read_text())
    assert result["status"] == status
    assert not (root / "checkout").exists()
    assert (root / "evidence/retained.txt").read_text() == "retained proof"
    assert all(
        (root / name).is_file()
        for name in ("run.json", "verdict.json", "events.jsonl", "native.jsonl")
    )
    assert (result["observed_model"], result["observed_effort"]) == ("fake-model", "high")
    assert len(world.calls) == 1
    report = (root / "report.md").read_text()
    assert report == render_report(verdict)
    assert collect(root, 0) == expected
    assert capsys.readouterr().out == report
    saved = (root / "result.json").read_bytes()
    with pytest.raises(FileExistsError):
        supervise(root)
    assert len(world.calls) == 1
    assert (root / "result.json").read_bytes() == saved


def test_supervisor_preserves_long_test_names_and_saved_evidence(supervised_run, verdict, capsys):
    """Length-only secret masking erased real test names and invalidated a saved pass."""
    root, _, _ = supervised_run
    name = "test_detached_tester_survives_launcher_exit_and_collect_is_idempotent"
    (root / "evidence/output.txt").write_text(name + "\n")
    verdict["scenarios"][0]["evidence"][0]["quote"] = name
    verdict["regressions"] = [
        {"name": name, "bug": "Launcher exit loses tester.", "evidence": name}
    ]
    assert supervise(root) == 0
    saved = json.loads((root / "verdict.json").read_text())
    assert saved == verdict
    assert not list(root.glob("**/report-evidence-*"))
    assert validate_verdict(saved, ["basic"], root) == "pass"
    report = (root / "report.md").read_text()
    assert name in report
    assert collect(root, 0) == 0
    assert capsys.readouterr().out == report


def test_collect_pending_never_launches_and_completed_report_is_verbatim(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("collection launched"))
    runs.save(tmp_path / "run.json", {"started_at": time.time()})
    assert collect(tmp_path, 0) == 3
    (tmp_path / "result.json").write_text('{"status":"pass","exit_code":0}')
    (tmp_path / "report.md").write_text("persisted report\n")
    capsys.readouterr()
    assert collect(tmp_path, 0) == 0
    assert capsys.readouterr().out == "persisted report\n"


OVERDUE = runs.TIMEOUT_SECONDS + 31


def _dead(pid, sig):
    raise ProcessLookupError


def test_collect_stays_pending_while_the_supervisor_lives(tmp_path, capsys):
    """A slow run must not be recorded blocked while its supervisor still writes the result."""
    runs.save(tmp_path / "run.json", {"started_at": time.time() - OVERDUE})
    runs.save(tmp_path / "accepted.json", {"supervisor_pid": os.getpid()})
    assert collect(tmp_path, 0) == 3
    assert "PENDING" in capsys.readouterr().out
    assert not (tmp_path / "result.json").exists()


@pytest.mark.parametrize("accepted", [True, False])
def test_collect_reports_a_gone_supervisor_blocked_without_writing(
    tmp_path, capsys, monkeypatch, accepted
):
    """A crashed supervisor must not leave the worker collecting forever."""
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("collection relaunched"))
    monkeypatch.setattr(os, "kill", _dead)
    started = time.time() - (0 if accepted else OVERDUE)
    runs.save(tmp_path / "run.json", {"started_at": started})
    if accepted:
        runs.save(tmp_path / "accepted.json", {"supervisor_pid": 4242})
    assert collect(tmp_path, 0) == 1
    assert "Tester BLOCKED" in capsys.readouterr().out
    assert not (tmp_path / "result.json").exists() and not (tmp_path / "report.md").exists()


def test_collect_reads_a_result_saved_while_it_checked_the_supervisor(
    tmp_path, capsys, monkeypatch
):
    """The supervisor saves its result before it exits, so a dead pid alone proves nothing."""

    def finish(pid, sig):
        (tmp_path / "result.json").write_text('{"status":"pass","exit_code":0}')
        (tmp_path / "report.md").write_text("persisted report\n")
        raise ProcessLookupError

    monkeypatch.setattr(os, "kill", finish)
    runs.save(tmp_path / "run.json", {"started_at": time.time()})
    runs.save(tmp_path / "accepted.json", {"supervisor_pid": 4242})
    assert collect(tmp_path, 0) == 0
    assert capsys.readouterr().out == "persisted report\n"


@pytest.mark.parametrize("name", ["guide.md", "validation.md"])
def test_supervisor_refuses_changed_inputs_before_starting_tester(supervised_run, name):
    root, world, _ = supervised_run
    (root / name).write_text("Different instructions after launch preparation")
    assert supervise(root) == 1
    assert not world.calls
    assert not (root / "checkout").exists()
    assert "tester input changed" in (root / "report.md").read_text()
