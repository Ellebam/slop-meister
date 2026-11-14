"""A diff check borrows the worker allocation and returns it ready."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

import pytest

from slopmeister import workspace_removal
from slopmeister.errors import SlopmeisterError
from slopmeister.review import check
from slopmeister.review.schema import CrossToolReviewError
from slopmeister.session import launch_identity
from slopmeister.slots import allocation, down, status, tester
from slopmeister.spine import candidate
from tests.support.repos import git, scratch_repo

PLOT = '[plot]\nbase="code"\n[target]\ntasks="github"\n[target.repository]\ncommit="allow"\n'


@pytest.fixture
def borrowed(tmp_path, monkeypatch):
    """A check must reset and return the allocated worker slot, without a second claim."""
    repo = scratch_repo(tmp_path / "subject")
    program = """import os, sys
from pathlib import Path
phase = os.environ.get('SLOPMEISTER_SLOT_PHASE', '')
data = Path(os.environ['SLOT_DATA'])
assert Path('.slot.env').is_file(), 'missing allocation'
if (data / ('fail-' + phase)).exists():
    raise SystemExit(17)
if (data / 'ignore-phase').exists():
    sys.exit(0)
if phase == 'reset':
    (data / 'sentinel').write_text('clean')
if phase == 'ready':
    (data / 'ready').touch()
print('SLOPMEISTER_SLOT_PHASE_OK=' + phase)
"""
    (repo / "prepare.py").write_text(program)
    git(repo, "add", "prepare.py")
    git(repo, "commit", "-qm", "Add reset fixture")
    plots = tmp_path / "plots/scratch"
    plots.mkdir(parents=True)
    (plots / "plot.toml").write_text(
        PLOT
        + '[slots]\nmax=1\nsetup=["'
        + sys.executable
        + '","prepare.py"]\n[slots.ports]\nWEB=42000\n'
    )
    worker = repo / ".worktrees/scratch-one"
    git(repo, "worktree", "add", "-q", "-b", worker.name, str(worker))
    data = tmp_path / "slots/scratch-slot1"
    data.mkdir(parents=True)
    item = allocation.Claim(
        allocation.Live("scratch", 1, worker.name, worker), data, None, {"WEB": 42001}
    )
    allocation.write(data / ".slot.env", item)
    allocation.write(worker / ".slot.env", item)
    exclude = Path(git(worker, "rev-parse", "--git-path", "info/exclude").strip())
    exclude.write_text(exclude.read_text() + "\n.slot.env\n")
    (data / "sentinel").write_text("worker leftovers")
    guide = tmp_path / "guide.md"
    guide.write_text("### Scenario basic: Read subject\nRead README.md.\n")
    monkeypatch.setenv("PLOT_DECLARATIONS", str(plots.parent))
    monkeypatch.setenv("SLOT_STATE_DIR", str(data.parent))
    monkeypatch.setattr(allocation, "bound_ports", lambda: [])
    monkeypatch.setattr(tester.occupants, "census", lambda checkout: [])
    return (
        worker,
        data,
        argparse.Namespace(
            cwd=str(worker), guide=str(guide), subject_manifest=None, slot_target="scratch"
        ),
    )


def test_check_borrows_worker_slot_and_returns_it_ready(borrowed):
    worker, data, args = borrowed
    original = (worker / ".slot.env").read_bytes()
    with check.prepared(args, None) as prepared:
        assert (prepared.checkout / ".slot.env").read_bytes() == original
        assert (data / "sentinel").read_text() == "clean"
        assert list(data.parent.iterdir()) == [data]
        (data / "sentinel").write_text("tester leftovers")
    assert not prepared.cleanup_error
    assert not prepared.checkout.exists()
    assert (data / "sentinel").read_text() == "clean"
    assert (data / "ready").is_file()
    assert (worker / ".slot.env").read_bytes() == (data / ".slot.env").read_bytes() == original
    assert not (data / tester.RECORD).exists()


@pytest.mark.parametrize("verdict", ["pass", "fail"])
def test_public_check_returns_a_failed_verdict_without_restarting_rejected_code(
    borrowed, tmp_path, verdict
):
    worker, data, args = borrowed
    if verdict == "fail":
        (data / "fail-ready").touch()
    session = str(uuid.uuid4())
    launch_identity.write(worker, (worker.name, "codex", session))
    binary = tmp_path / "bin/claude"
    binary.parent.mkdir()
    binary.write_text(
        f"#!{sys.executable}\n"
        "import json\nfrom pathlib import Path\n"
        "root=Path.cwd().parent\n"
        "(root/'evidence/basic.out').write_text('same slot clean checkout')\n"
        "print(json.dumps({'findings':[], 'security_lens':{'finding':None,"
        "'checks':['synthetic fixture'],'evidence':'No external data'},"
        f"'scenarios':[{{'id':'basic','status':'{verdict}','reason':'','evidence':"
        "[{'path':'evidence/basic.out','quote':'same slot clean checkout'}]}],"
        "'guide_findings':[]}))\n"
    )
    binary.chmod(0o700)
    command = [
        str(Path(__file__).resolve().parents[3] / "bin/slopmeister"),
        "review",
        "review",
        "--direction",
        "codex-to-claude",
        "--mode",
        "diff",
        "--cwd",
        str(worker),
        "--guide",
        args.guide,
        "--slot-target",
        "scratch",
        "--prompt",
        "Review the synthetic subject.",
    ]
    result = subprocess.run(
        command,
        cwd=worker,
        env=dict(
            os.environ,
            CODEX_THREAD_ID=session,
            PATH=str(binary.parent) + os.pathsep + os.environ["PATH"],
        ),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == (0 if verdict == "pass" else 1), result.stdout + result.stderr
    assert f"basic: {verdict}" in result.stdout
    assert (data / "sentinel").read_text() == "clean" and not (data / tester.RECORD).exists()
    assert (data / "ready").exists() is (verdict == "pass")
    print(result.stdout)


def test_same_worker_cannot_start_a_second_check(borrowed, monkeypatch):
    _, data, args = borrowed
    with check.prepared(args, None):
        with pytest.raises(CrossToolReviewError, match="holds|leased"), check.prepared(args, None):
            pytest.fail("the second check must not run")
        with pytest.raises(SlopmeisterError, match="still holds"):
            down.main([args.cwd, "scratch", "scratch-one", "--slot", "1"])
        monkeypatch.setattr(down, "_calling_worker", lambda *args: None)
        monkeypatch.setattr(down, "_detach", lambda *args: pytest.fail("leased worker stopped"))
        with pytest.raises(SlopmeisterError, match="check lease"):
            workspace_removal.main(["--self", "--", args.cwd])
        assert (data / tester.RECORD).exists()


def test_legacy_lease_does_not_block_another_workers_release(borrowed, monkeypatch, capsys):
    worker, data, _ = borrowed
    legacy = data.parent / "scratch-slot2"
    legacy.mkdir()
    content = json.dumps({"name": "scratch-old-tester", "repository": str(worker.parent.parent)})
    (legacy / tester.RECORD).write_text(content)

    def reached(request):
        raise RuntimeError("release reached")

    monkeypatch.setattr(down, "_context", reached)
    with pytest.raises(RuntimeError, match="release reached"):
        down.main([str(worker.parent.parent), "scratch", worker.name])
    assert (legacy / tester.RECORD).read_text() == content
    status.live(str(worker.parent.parent))
    assert f"retained check record {legacy / tester.RECORD}" in capsys.readouterr().out


@pytest.mark.parametrize("phase", ["stop", "reset"])
def test_failed_preparation_never_admits_reviewer(borrowed, phase):
    _, data, args = borrowed
    (data / ("fail-" + phase)).touch()
    with pytest.raises(CrossToolReviewError, match="exited 17"), check.prepared(args, None):
        pytest.fail("the checker must not run on unreset data")
    assert (data / ".slot.env").exists() and (data / tester.RECORD).exists()


def test_interrupted_delivery_recovers_through_worker_setup(borrowed, monkeypatch):
    worker, data, args = borrowed

    def interrupted(*args):
        raise OSError("allocation delivery interrupted")

    monkeypatch.setattr(tester, "_deliver", interrupted)
    with (
        pytest.raises(CrossToolReviewError, match="delivery interrupted"),
        check.prepared(args, None),
    ):
        pytest.fail("an undelivered check must not run")
    assert (data / tester.RECORD).exists()
    tester.recover(data, worker.parent.parent, "1")
    assert (data / "ready").is_file() and not (data / tester.RECORD).exists()
    assert (data / ".slot.env").read_bytes() == (worker / ".slot.env").read_bytes()


def test_missing_allocation_after_admission_keeps_checkout_and_lease(borrowed, monkeypatch):
    _, data, args = borrowed
    with check.prepared(args, None) as prepared:
        (prepared.checkout / ".slot.env").unlink()
        monkeypatch.setattr(
            tester.setup, "phase", lambda *args: pytest.fail("changed allocation reached setup")
        )
    assert "allocation changed" in prepared.cleanup_error
    assert prepared.checkout.exists() and (data / tester.RECORD).exists()


def test_setup_ignoring_phase_blocks_admission(borrowed):
    _, data, args = borrowed
    (data / "ignore-phase").touch()
    with pytest.raises(CrossToolReviewError, match="acknowledge"), check.prepared(args, None):
        pytest.fail("unsupported setup must not run a checker")
    assert (data / "sentinel").read_text() == "worker leftovers"


def test_failed_return_can_be_recovered_without_releasing_worker(borrowed):
    worker, data, args = borrowed
    original = (data / ".slot.env").read_bytes()
    (data / "unrelated").write_text("keep this")
    with check.prepared(args, None) as prepared:
        (data / "fail-ready").touch()
    assert "exited 17" in prepared.cleanup_error
    assert prepared.checkout.exists() and (data / tester.RECORD).exists()
    (data / "fail-ready").unlink()
    assert down.main([str(worker.parent.parent), "scratch", worker.name, "--slot", "1"]) == 0
    assert not (data / tester.RECORD).exists() and not prepared.checkout.exists()
    assert (data / ".slot.env").read_bytes() == (worker / ".slot.env").read_bytes() == original
    assert (data / "unrelated").read_text() == "keep this" and (data / "ready").exists()


def test_unknown_reviewer_stop_retains_lease(borrowed):
    _, data, args = borrowed
    with check.prepared(args, None) as prepared:
        prepared.stopped = False
    assert "stop unverified" in prepared.cleanup_error
    assert (data / tester.RECORD).exists() and prepared.checkout.exists()


@pytest.mark.parametrize("changed", ["worker", "state", "checkout", "owner"])
def test_changed_identity_blocks_cleanup(borrowed, changed):
    worker, data, args = borrowed
    with check.prepared(args, None) as prepared:
        paths = {
            "worker": worker / ".slot.env",
            "state": data / ".slot.env",
            "checkout": prepared.checkout / ".slot.env",
        }
        if changed == "owner":
            marker = data / tester.RECORD
            value = __import__("json").loads(marker.read_text())
            value["run"] = str(data.parent / "foreign")
            marker.write_text(__import__("json").dumps(value))
        else:
            paths[changed].write_text("foreign allocation\n")
    assert "changed" in prepared.cleanup_error
    assert (data / tester.RECORD).exists() and prepared.checkout.exists()


def test_frozen_candidate_keeps_tree_and_worker_identity(borrowed):
    worker, data, args = borrowed
    (worker / "new.txt").write_text("candidate only")
    frozen = candidate.freeze(worker, "scratch-candidate")
    with check.prepared(args, frozen) as prepared:
        assert (prepared.checkout / "new.txt").read_text() == "candidate only"
        assert allocation.read(prepared.checkout / ".slot.env").name == worker.name
        prepared.verify()
    assert not prepared.cleanup_error and not (data / tester.RECORD).exists()


def test_composed_worker_stack_is_never_started_or_removed_by_checker(borrowed, monkeypatch):
    worker, data, args = borrowed
    from slopmeister.slots import compose

    (worker / "stack.yml").write_text("services: {}\n")
    git(worker, "add", "stack.yml")
    git(worker, "commit", "-qm", "Add compose fixture")
    plots = Path(os.environ["PLOT_DECLARATIONS"]) / "scratch/plot.toml"
    plots.write_text(plots.read_text().replace("max=1", 'max=1\ncompose="stack.yml"'))
    claim = allocation.Claim(
        allocation.Live("scratch", 1, worker.name, worker),
        data,
        worker / "stack.yml",
        {"WEB": 42001},
    )
    allocation.write(data / ".slot.env", claim)
    allocation.write(worker / ".slot.env", claim)
    monkeypatch.setattr(allocation, "remove_project", lambda *args: pytest.fail("stack removed"))
    monkeypatch.setattr(compose, "_compose_up", lambda *args: pytest.fail("second stack started"))
    with check.prepared(args, None) as prepared:
        assert allocation.read(prepared.checkout / ".slot.env").slot == 1
    assert not prepared.cleanup_error and data.exists()


def test_different_workers_can_check_their_own_slots_concurrently(borrowed):
    worker, data, args = borrowed
    repository = worker.parent.parent
    second = worker.parent / "scratch-two"
    git(repository, "worktree", "add", "-q", "-b", second.name, str(second))
    plots = Path(os.environ["PLOT_DECLARATIONS"]) / "scratch/plot.toml"
    plots.write_text(plots.read_text().replace("max=1", "max=2"))
    other_data = data.parent / "scratch-slot2"
    other_data.mkdir()
    claim = allocation.Claim(
        allocation.Live("scratch", 2, second.name, second), other_data, None, {"WEB": 42002}
    )
    allocation.write(other_data / ".slot.env", claim)
    allocation.write(second / ".slot.env", claim)
    second_args = argparse.Namespace(**(vars(args) | {"cwd": str(second)}))
    with check.prepared(args, None) as first, check.prepared(second_args, None) as other:
        assert allocation.read(first.checkout / ".slot.env").slot == 1
        assert allocation.read(other.checkout / ".slot.env").slot == 2
        assert len(list(data.parent.iterdir())) == 2
    assert not first.cleanup_error and not other.cleanup_error
    assert not (data / tester.RECORD).exists() and not (other_data / tester.RECORD).exists()


@pytest.mark.parametrize("destination", ["tracked", "symlink"])
def test_existing_checkout_allocation_is_not_overwritten(borrowed, monkeypatch, destination):
    worker, data, args = borrowed
    outside = data / "sentinel"
    if destination == "tracked":
        git(worker, "add", "-f", ".slot.env")
        git(worker, "commit", "-qm", "Track fixture allocation")
    else:
        original = check._checkout

        def checkout(prepared, frozen):
            original(prepared, frozen)
            (prepared.checkout / ".slot.env").symlink_to(outside)

        monkeypatch.setattr(check, "_checkout", checkout)
    with (
        pytest.raises(CrossToolReviewError, match="destination already exists"),
        check.prepared(args, None),
    ):
        pytest.fail("foreign allocation must not be overwritten")
    assert outside.read_text() == "worker leftovers"
    assert (data / ".slot.env").exists() and (data / tester.RECORD).exists()
