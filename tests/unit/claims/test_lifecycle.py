"""Claim lifecycle writes remain recoverable and idempotent."""

from contextlib import contextmanager
import json

import pytest

from slopmeister.claims import cli, evidence, github, inventory, lifecycle, locks
from tests.support import trees


def test_claim_write_failure_preserves_pending_owner(service, monkeypatch):
    context, path, saved, remote, writes = service
    original = github.request

    def fail(ctx, call):
        if call.method != "GET":
            raise ValueError("write failed")
        return original(ctx, call)

    monkeypatch.setattr(github, "request", fail)
    with pytest.raises(ValueError, match="claim unconfirmed"):
        lifecycle.confirm(context, path, saved)
    row = inventory.classify(remote, inventory.Classification(owners=[evidence.read(path)]))
    assert row["category"] == "unknown" and not row["recommend"]
    assert path.exists()


def test_redispatch_owner_retains_claim_without_duplicate_transition(service):
    context, path, saved, remote, writes = service
    lifecycle.confirm(context, path, saved)
    assert len(writes) == 1
    lifecycle.confirm(context, path, evidence.read(path))
    assert len(writes) == 1


def test_harvest_closes_before_removing_claim_and_retries_idempotently(service):
    context, path, saved, remote, writes = service
    lifecycle.confirm(context, path, saved)
    lifecycle.close_issue(context, lifecycle.Closure(path, evidence.read(path)))
    assert remote["state"] == "closed" and not remote["labels"]
    assert [value[0] for value in writes] == ["POST", "PATCH", "DELETE"]
    lifecycle.close_issue(context, lifecycle.Closure(path, evidence.read(path)))
    assert [value[0] for value in writes] == ["POST", "PATCH", "DELETE"]


def test_harvest_failure_keeps_claim_and_recovery_evidence(service, monkeypatch):
    context, path, saved, remote, writes = service
    lifecycle.confirm(context, path, saved)
    original = github.request

    def fail(ctx, call):
        if call.method == "PATCH":
            raise ValueError("close failed")
        return original(ctx, call)

    monkeypatch.setattr(github, "request", fail)
    with pytest.raises(ValueError):
        lifecycle.close_issue(context, lifecycle.Closure(path, evidence.read(path)))
    assert remote["state"] == "open" and remote["labels"]
    assert evidence.read(path)["phase"] == "closing"


def test_applied_claim_with_lost_response_recovers_without_duplicate_write(service, monkeypatch):
    context, path, saved, remote, writes = service
    original = github.request

    def lost(ctx, call):
        result = original(ctx, call)
        if call.method == "POST":
            raise ValueError("response lost after apply")
        return result

    monkeypatch.setattr(github, "request", lost)
    with pytest.raises(ValueError, match="claim unconfirmed"):
        lifecycle.confirm(context, path, saved)
    values = inventory.Classification(owners=[evidence.read(path)])
    assert inventory.classify(remote, values)["category"] == "unknown"
    monkeypatch.setattr(github, "request", original)
    lifecycle.confirm(context, path, evidence.read(path))
    assert len(writes) == 1 and evidence.read(path)["phase"] == "claimed"


@pytest.mark.parametrize("phase", ["released", "closed", "abandoning", "closing"])
def test_reconcile_cannot_restart_a_finished_lifecycle(service, phase):
    context, path, saved, remote, writes = service
    saved["phase"] = phase
    with pytest.raises(ValueError, match="claim unconfirmed"):
        lifecycle.confirm(context, path, saved)
    assert not writes


def test_handoff_parent_traversal_cannot_select_outside_recovery_file(
    service, monkeypatch, tmp_path
):
    context, path, saved, remote, writes = service
    workspace = tmp_path / "worker"
    workspace.mkdir()
    handoff = trees.write(tmp_path, "outside.md", "Not this workspace.\n")
    saved["workspace"] = str(workspace)
    monkeypatch.setattr(inventory, "census", lambda workspace: [])
    with pytest.raises(ValueError, match="inside"):
        operation = lifecycle.Abandonment(path, saved, workspace / "../outside.md")
        lifecycle.abandon(context, operation)
    assert handoff.exists() and not writes


def test_lifecycle_rereads_receipt_after_acquiring_issue_lock(service, monkeypatch):
    context, path, saved, remote, writes = service

    @contextmanager
    def acquire(ctx, number, inherited):
        finished = evidence.read(path)
        finished["phase"] = "closed"
        evidence.save(path, finished)
        yield

    monkeypatch.setattr(evidence, "receipt_path", lambda workspace: path)
    monkeypatch.setattr(
        evidence, "workspace_record", lambda *args, **kwargs: (context, path, evidence.read(path))
    )
    monkeypatch.setattr(evidence, "eligible", lambda *args: True)
    monkeypatch.setattr(inventory, "census", lambda *args: [])
    monkeypatch.setattr(locks, "locked", acquire)
    assert cli.main(["reconcile", "--workspace", str(path.parent)]) == 1
    assert not writes


def test_legacy_recovery_never_overwrites_a_concurrent_association(monkeypatch, tmp_path):
    path = tmp_path / "issue.json"
    trees.write(tmp_path, "state.json", json.dumps({"ship_target": {"remote": "remote"}}))
    kickoff = trees.write(tmp_path, "kickoff.md", "Mode: spine\nWork.\n")
    monkeypatch.setattr(evidence, "receipt_path", lambda _: path)
    monkeypatch.setattr(evidence, "eligible", lambda *_: True)
    other = {"issue": 8, "phase": "pending"}
    monkeypatch.setattr(evidence, "delivery_evidence", lambda _: evidence.save(path, other))
    context = github.Repository(tmp_path, tmp_path, "owner/project", "remote", "slopmeister")
    with pytest.raises(FileExistsError):
        operation = lifecycle.Initialization(tmp_path, 7, kickoff, {"session": "native"})
        lifecycle.initialize(context, operation)
    assert evidence.read(path) == other


@pytest.mark.parametrize(
    "reason, sent", [("completed", "completed"), ("not-planned", "not_planned")]
)
def test_close_reason_reaches_github_and_releases_the_claim(service, reason, sent):
    """Bug: a dropped task is recorded as completed, or the reason changes a normal close."""
    context, path, saved, remote, writes = service
    lifecycle.confirm(context, path, saved)
    lifecycle.close_issue(context, lifecycle.Closure(path, evidence.read(path), reason))
    assert writes[1][2] == {"state": "closed", "state_reason": sent}
    assert remote["state"] == "closed" and not remote["labels"]


def test_not_planned_close_still_requires_the_owning_worker(service, monkeypatch):
    """Bug: the not-planned reason skips the ownership check and closes another worker's issue."""
    context, path, saved, remote, writes = service
    lifecycle.confirm(context, path, saved)
    monkeypatch.setattr(lifecycle, "other_owners", lambda *args: [{"issue": 7}])
    with pytest.raises(ValueError, match="verified owning worker"):
        lifecycle.close_issue(context, lifecycle.Closure(path, evidence.read(path), "not-planned"))
    assert remote["state"] == "open" and remote["labels"]
