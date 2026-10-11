"""Completed testers discard only their owned checkout after preserving the result."""

import json
import shutil
import stat

import pytest

from slopmeister.spine.tester import runs
from slopmeister.spine.tester.collect import collect
from slopmeister.spine.tester.supervise import supervise


@pytest.mark.parametrize("status", ["pass", "fail", "blocked"])
def test_readonly_cache_cleanup_keeps_evidence_and_outside_files(supervised_run, verdict, status):
    root, _, _ = supervised_run
    cache = root / "checkout/tmp/go-mod/module"
    cache.mkdir(parents=True)
    (cache / "module.go").write_text("readonly module")
    fixture = root / "checkout/fixture"
    fixture.mkdir()
    (fixture / "input.txt").write_text("readonly fixture")
    outside = root.parent / "outside.txt"
    outside.write_text("unrelated bytes")
    outside.chmod(0o444)
    (cache / "outside-link").symlink_to(outside)
    for path in (cache / "module.go", fixture / "input.txt"):
        path.chmod(0o444)
    for path in (cache, cache.parent, fixture):
        path.chmod(0o555)
    with pytest.raises(PermissionError):
        shutil.rmtree(cache)
    (root / "evidence/retained.txt").write_text("retained proof")
    original = {
        p: p.read_bytes() for p in root.rglob("*") if p.is_file() and "checkout" not in p.parts
    }
    verdict["scenarios"][0]["verdict"] = status
    assert supervise(root) == (0 if status == "pass" else 1)
    assert not (root / "checkout").exists()
    assert all(path.read_bytes() == value for path, value in original.items())
    assert outside.read_text() == "unrelated bytes"
    assert stat.S_IMODE(outside.stat().st_mode) == 0o444
    assert "checkout_cleanup_error" not in json.loads((root / "result.json").read_text())


@pytest.mark.parametrize("status", ["pass", "fail", "blocked"])
def test_cleanup_failure_records_redacted_error_after_saving_original_outcome(
    supervised_run, verdict, status, monkeypatch, capsys
):
    root, _, _ = supervised_run
    verdict["scenarios"][0]["verdict"] = status
    original_result = []

    def refuse(path, **kwargs):
        assert path == root / "checkout"
        original_result.append(json.loads((root / "result.json").read_text()))
        assert original_result[0]["status"] == status
        raise OSError("cleanup failed password=private-fixture-value")

    monkeypatch.setattr(shutil, "rmtree", refuse)
    expected = 0 if status == "pass" else 1
    assert supervise(root) == expected
    result = json.loads((root / "result.json").read_text())
    assert result["status"] == status and result["exit_code"] == expected
    assert result.keys() - original_result[0].keys() == {"checkout_cleanup_error"}
    assert "password=[REDACTED]" in result["checkout_cleanup_error"]
    assert "private-fixture-value" not in (root / "result.json").read_text()
    assert (root / "checkout").is_dir()
    report = (root / "report.md").read_text()
    assert collect(root, 0) == expected
    assert capsys.readouterr().out == report


def test_process_record_failure_after_start_never_deletes_checkout(supervised_run, monkeypatch):
    """A missing stop flag after Popen must not be mistaken for a tester that never started."""
    root, world, _ = supervised_run
    save = runs.save

    def refuse_record(path, value):
        if path.name == "process.json":
            raise OSError("process record unavailable")
        save(path, value)

    monkeypatch.setattr(runs, "save", refuse_record)
    assert supervise(root) == 1
    assert len(world.calls) == 1 and not world.signals
    result = json.loads((root / "result.json").read_text())
    assert result["status"] == "blocked" and result["process_stopped"] is False
    assert "unverified" in result["checkout_cleanup_error"]
    assert (root / "checkout").is_dir()


def test_checkout_root_symlink_cannot_delete_or_chmod_retained_evidence(supervised_run):
    root, _, _ = supervised_run
    evidence = root / "evidence"
    (evidence / "retained.txt").write_text("retained proof")
    evidence.chmod(0o555)
    checkout = root / "checkout"
    checkout.rmdir()
    checkout.symlink_to(evidence, target_is_directory=True)
    try:
        assert supervise(root) == 0
        result = json.loads((root / "result.json").read_text())
        assert result["status"] == "pass"
        assert result["checkout_cleanup_error"] == "checkout is a symlink, not removed"
        assert checkout.is_symlink()
        assert (evidence / "retained.txt").read_text() == "retained proof"
        assert stat.S_IMODE(evidence.stat().st_mode) == 0o555
    finally:
        evidence.chmod(0o700)
