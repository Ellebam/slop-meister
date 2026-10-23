"""Only an intact recorded hand-back may pass the self-cleanup claim gate."""

import os

import pytest

from slopmeister.claims import evidence
from slopmeister.errors import SlopmeisterError
from slopmeister.slots import claimed


@pytest.fixture
def handback(tmp_path, monkeypatch):
    root = tmp_path / "worker"
    root.mkdir()
    handoff = root / "handoff.md"
    handoff.write_text("unfinished work\n")
    receipt = tmp_path / "issue.json"
    saved = {
        "workspace": str(root),
        "phase": "abandoning",
        "handoff": {"path": str(handoff), "sha256": evidence.digest(handoff)},
    }
    evidence.save(receipt, saved)
    monkeypatch.setattr(claimed, "_receipt", lambda *_: receipt)
    return root, handoff, receipt, saved


@pytest.mark.parametrize("damage", ["changed", "outside", "linked", "pipe", "phase"])
def test_unsafe_or_unrecorded_handback_does_not_allow_cleanup(handback, damage, monkeypatch):
    root, handoff, receipt, saved = handback
    if damage == "changed":
        handoff.write_text("changed after recording")
    elif damage in {"outside", "linked"}:
        outside = root.parent / "outside"
        outside.write_bytes(handoff.read_bytes())
        if damage == "outside":
            saved["handoff"]["path"] = str(outside)
        else:
            handoff.unlink()
            handoff.symlink_to(outside)
    elif damage == "pipe":
        handoff.unlink()
        os.mkfifo(handoff)
    else:
        saved["phase"] = "claimed"
    evidence.save(receipt, saved)
    monkeypatch.setattr(claimed.cli, "main", lambda *_: pytest.fail("claim mutation"))
    assert not claimed.handback_recorded(root)
    if damage != "phase":
        with pytest.raises(SlopmeisterError, match="changed, claim preserved"):
            claimed.complete_handback(root)


def test_intact_handback_releases_only_the_saved_workspace(handback, monkeypatch):
    root, handoff, _, _ = handback
    calls = []
    monkeypatch.setattr(claimed.cli, "main", lambda argv: calls.append(argv) or 0)
    assert claimed.handback_recorded(root)
    claimed.complete_handback(root)
    assert calls == [["abandon-complete", "--workspace", str(root), "--handoff", str(handoff)]]
