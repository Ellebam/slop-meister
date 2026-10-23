"""Damaged tester ownership never hides other allocations or bypasses recovery guards."""

import pytest

from slopmeister.errors import SlopmeisterError
from slopmeister.slots import allocation, down, status, tester
from slopmeister.spine.tester import launch
from tests.integration.spine.test_tester_slots import admit
from tests.integration.spine.test_tester_slots import allocated_subject as allocated_subject


def test_unreadable_record_does_not_hide_other_slot_status(allocated_subject, monkeypatch, capsys):
    repo, args = allocated_subject
    monkeypatch.setattr(launch, "_start_supervisor", admit)
    root = launch.launch(args)
    damaged = allocation.state_path() / "scratch-slot3/tester.json"
    damaged.parent.mkdir()
    damaged.write_text("")
    item = allocation.read(root / "checkout/.slot.env")
    status.live(str(repo))
    output = capsys.readouterr().out
    assert item.name in output and "unreadable tester" in output
    assert damaged.read_bytes() == b""
    assert down.main([str(repo), "scratch", item.name, "--slot", str(item.slot)]) == 0


def test_dangling_ownership_record_cannot_bypass_recovery_with_force(
    allocated_subject, monkeypatch
):
    repo, args = allocated_subject
    monkeypatch.setattr(launch, "_start_supervisor", admit)
    root = launch.launch(args)
    item = allocation.read(root / "checkout/.slot.env")
    data = allocation.state_path() / f"scratch-slot{item.slot}"
    marker = data / tester.RECORD
    marker.unlink()
    marker.symlink_to(repo.parent / "absent-owner")
    with pytest.raises(SlopmeisterError, match="unreadable tester ownership"):
        down.main([str(repo), "scratch", item.name, "--slot", str(item.slot), "--force"])
    assert data.is_dir() and marker.is_symlink()
