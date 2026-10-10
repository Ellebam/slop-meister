"""slot:down keeps a worktree whose issue claim is still active."""

import shutil

import pytest

from slopmeister.claims import evidence, github
from slopmeister.errors import SlopmeisterError
from slopmeister.slots import claimed
from tests.support import repos


def _receipt(tmp_path, monkeypatch, phase):
    path = tmp_path / "issue.json"
    if phase == "{}":
        evidence.save(path, {})
    elif phase:
        evidence.save(path, {"issue": 7, "phase": phase})
    monkeypatch.setattr(evidence, "receipt_path", lambda workspace: path)
    (tmp_path / ".git").touch()


@pytest.mark.parametrize("phase", [*sorted(github.ACTIVE), "claimd", "{}"])
def test_down_refuses_an_active_claim_and_names_abandon(tmp_path, monkeypatch, phase):
    """Bug: teardown deleted the receipt and left agent:claimed on the issue for good."""
    _receipt(tmp_path, monkeypatch, phase)
    with pytest.raises(SlopmeisterError, match=r"holds the claim on issue .*--abandon --handoff"):
        claimed.refuse(tmp_path, "scratch")


@pytest.mark.parametrize("phase", ["released", "closed", ""])
def test_down_proceeds_once_the_claim_is_released_closed_or_absent(tmp_path, monkeypatch, phase):
    """Bug: the claim guard blocked teardown after abandon or finalize."""
    _receipt(tmp_path, monkeypatch, phase)
    claimed.refuse(tmp_path, "scratch")


def test_down_refuses_an_unreadable_association(tmp_path, monkeypatch):
    """Bug: a corrupt receipt was read as no claim and the worktree was removed."""
    (tmp_path / "issue.json").write_text("{")
    (tmp_path / ".git").touch()
    monkeypatch.setattr(evidence, "receipt_path", lambda workspace: tmp_path / "issue.json")
    with pytest.raises(SlopmeisterError, match="cannot read the issue association"):
        claimed.refuse(tmp_path, "scratch")


def test_local_receipt_does_not_shadow_the_authoritative_claim(tmp_path, monkeypatch):
    """Bug: plain and slot cleanup accepted a worker-written release over the real active claim."""
    _receipt(tmp_path, monkeypatch, "claimed")
    local = tmp_path / ".slopmeister-config/issue.json"
    local.parent.mkdir()
    evidence.save(local, {"issue": 7, "phase": "closed"})
    with pytest.raises(SlopmeisterError, match="holds the claim"):
        claimed.refuse(tmp_path, "scratch")


@pytest.mark.parametrize("lost", ["link", "directory"])
def test_down_refuses_an_active_claim_whose_worktree_lost_its_git_link(tmp_path, lost):
    """Bug: teardown pruned the Git metadata, and with it an active claim's receipt."""
    root = repos.scratch_repo(tmp_path / "repo").resolve()
    repos.git(root, "worktree", "add", "-q", "-b", "scratch-one", ".worktrees/scratch-one")
    worktree = root / ".worktrees/scratch-one"
    receipt = root / ".git/worktrees/scratch-one" / evidence.RECEIPT
    receipt.parent.mkdir()
    evidence.save(receipt, {"issue": 7, "phase": "claimed"})
    if lost == "link":
        (worktree / ".git").unlink()
    else:
        shutil.rmtree(worktree)
    with pytest.raises(SlopmeisterError, match=r"issue 7 .*--abandon --handoff"):
        claimed.refuse(worktree, "scratch")
