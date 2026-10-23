"""Service testers receive a separate allocation without opening another worker."""

import argparse
import json
from pathlib import Path
import subprocess
import sys

import pytest

from slopmeister.errors import SlopmeisterError
from slopmeister.slots import allocation, down, status, tester
from slopmeister.spine import candidate
from slopmeister.spine.tester import launch, runs
from slopmeister.spine.tester.supervise import _verify_subject
from tests.support.repos import git, scratch_repo

pytestmark = pytest.mark.xdist_group("tester-slots")


@pytest.fixture
def allocated_subject(tmp_path, monkeypatch):
    repo = scratch_repo(tmp_path / "subject")
    plots = tmp_path / "plots/scratch"
    plots.mkdir(parents=True)
    (plots / "plot.toml").write_text(
        '[plot]\nbase="code"\n[target]\ntasks="github"\n'
        '[target.repository]\ncommit="allow"\n[slots]\nmax=3\n[slots.ports]\nWEB=42000\n'
    )
    guide, notes = tmp_path / "guide.md", tmp_path / "notes.md"
    guide.write_text("### Scenario basic: Read subject\nRead README.md.\n")
    notes.write_text("\n## Validation\nRead the exact commit.\n")
    monkeypatch.setenv("PLOT_DECLARATIONS", str(plots.parent))
    monkeypatch.setenv("SLOT_STATE_DIR", str(tmp_path / "slots"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(allocation, "bound_ports", lambda: [])
    monkeypatch.setattr(tester.occupants, "census", lambda checkout: [])
    monkeypatch.setattr(status, "_workers", lambda current: None)
    monkeypatch.setattr(launch, "trust", lambda *args: None)
    args = argparse.Namespace(
        cwd=str(repo), commit="HEAD", task="Same_Task.1", worker_tool="codex",
        guide=str(guide), validation=str(notes), slot_target="scratch",
    )  # fmt: skip
    return repo, args


def admit(root, run):
    """Admission sees setup already delivered, without starting a model."""
    checkout = Path(run["checkout"])
    assert (checkout / ".slot.env").is_file(), "tester has no slot before admission"
    assert git(checkout, "status", "--porcelain").strip() == ""
    assert git(checkout, "rev-parse", "HEAD").strip() == run["commit"]
    runs.save(root / "accepted.json", {"supervisor_pid": 999999999})


def test_same_task_runs_get_distinct_slots_and_existing_teardown_recovers_them(
    allocated_subject, monkeypatch, capsys
):
    repo, args = allocated_subject
    monkeypatch.setattr(launch, "_start_supervisor", admit)
    roots = [launch.launch(args), launch.launch(args)]
    held = [allocation.read(root / "checkout/.slot.env") for root in roots]
    assert [item.slot for item in held] == [1, 2]
    assert held[0].name != held[1].name
    status.live(str(repo))
    output = capsys.readouterr().out
    assert all(item.name in output for item in held)
    for item, root in zip(held, roots, strict=True):
        assert down.main([str(repo), "scratch", item.name, "--slot", str(item.slot)]) == 0
        assert not (allocation.state_path() / f"scratch-slot{item.slot}").exists()
        assert (root / "checkout/README.md").is_file()
    assert git(repo, "status", "--porcelain").strip() == ""


def test_preparation_failure_releases_its_slot_and_preserves_the_blocked_result(
    allocated_subject, monkeypatch
):
    _, args = allocated_subject

    def refuse(root, run):
        assert (Path(run["checkout"]) / ".slot.env").is_file()
        raise OSError("supervisor unavailable")

    monkeypatch.setattr(launch, "_start_supervisor", refuse)
    with pytest.raises(OSError, match="supervisor unavailable"):
        launch.launch(args)
    assert not list(allocation.state_path().glob("scratch-slot*"))
    results = list(Path(args.cwd).parent.glob("state/slopmeister/spine-tests/*/result.json"))
    assert len(results) == 1
    assert json.loads(results[0].read_text())["status"] == "blocked"


def test_allocation_preserves_the_frozen_candidate_tree(allocated_subject, monkeypatch):
    repo, args = allocated_subject
    args.task = "scratch-candidate"
    (repo / "new.txt").write_text("candidate-only content")
    frozen = candidate.freeze(repo, args.task)
    args.candidate, args.commit = True, None
    monkeypatch.setattr(candidate, "load_for_session", lambda *args: frozen)

    def admit_candidate(root, run):
        assert (root / "checkout/new.txt").read_text() == "candidate-only content"
        assert (root / "checkout/.slot.env").is_file()
        _verify_subject(run)
        runs.save(root / "accepted.json", {"supervisor_pid": 999999999})

    monkeypatch.setattr(launch, "_start_supervisor", admit_candidate)
    root = launch.launch(args)
    assert candidate.worktree_tree(root / "checkout") == frozen.tree
    item = allocation.read(root / "checkout/.slot.env")
    assert down.main([str(repo), "scratch", item.name, "--slot", str(item.slot)]) == 0


def _supervisor(monkeypatch):
    program = (
        "import json,os,sys,time; from pathlib import Path; root=Path(sys.argv[1]); "
        "run=json.loads((root/'run.json').read_text()); os.fstat(run['slot']['fd']); "
        "(root/'accepted.json').write_text(json.dumps({'supervisor_pid':os.getpid()})); "
        "time.sleep(30)"
    )
    monkeypatch.setattr(runs, "command", lambda *args: [sys.executable, "-c", program, args[-1]])
    original, children = subprocess.Popen, []

    def start(command, **kwargs):
        child = original(command, **kwargs)
        if command[0] == sys.executable:
            children.append(child)
        return child

    monkeypatch.setattr(subprocess, "Popen", start)
    return children


def test_supervisor_holds_lease_after_launcher_exit_and_death_allows_recovery(
    allocated_subject, monkeypatch
):
    repo, args = allocated_subject
    children = _supervisor(monkeypatch)
    try:
        root = launch.launch(args)
        item = allocation.read(root / "checkout/.slot.env")
        command = [str(repo), "scratch", item.name, "--slot", str(item.slot)]
        with pytest.raises(SlopmeisterError, match="tester allocation is active"):
            down.main(command)
        children[0].terminate()
        children[0].wait(timeout=10)
        assert down.main(command) == 0
        assert not list(allocation.state_path().glob("scratch-slot*"))
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=10)


@pytest.mark.parametrize("destination", ["tracked", "dangling"])
def test_existing_allocation_destination_is_never_overwritten(
    allocated_subject, monkeypatch, destination
):
    repo, args = allocated_subject
    outside = repo.parent / "outside"
    outside.write_text("private sentinel")
    if destination == "tracked":
        (repo / ".slot.env").write_text("tracked content")
        git(repo, "add", ".slot.env")
        git(repo, "commit", "-qm", "Track allocation fixture")
    else:
        original = launch._checkout

        def checkout(root, run, request):
            original(root, run, request)
            (Path(run["checkout"]) / ".slot.env").symlink_to(outside.parent / "absent")

        monkeypatch.setattr(launch, "_checkout", checkout)
    with pytest.raises(SlopmeisterError, match="allocation destination already exists"):
        launch.launch(args)
    assert outside.read_text() == "private sentinel"
    assert not list(allocation.state_path().glob("scratch-slot*"))


@pytest.mark.parametrize("phase", ["state", "checkout"])
def test_interrupted_allocation_is_readable_and_recoverable_before_environment_publish(
    allocated_subject, capsys, phase
):
    repo, args = allocated_subject
    boundary = "allocation.write" if phase == "state" else "tester._deliver"
    program = (
        "import argparse,json,os,sys; "
        "from slopmeister.slots import allocation,tester; "
        "from slopmeister.spine.tester import launch; "
        f"{boundary}=lambda *args: os._exit(23); allocation.bound_ports=lambda: []; "
        "launch.trust=lambda *args: None; "
        "launch.launch(argparse.Namespace(**json.loads(sys.argv[1])))"
    )
    ended = subprocess.run([sys.executable, "-c", program, json.dumps(vars(args))], check=False)
    assert ended.returncode == 23
    status.live(str(repo))
    assert "scratch-tester-" in capsys.readouterr().out
    marker = next(allocation.state_path().glob("scratch-slot*/tester.json"))
    record = json.loads(marker.read_text())
    assert record["repository"] == str(repo)
    assert (marker.parent / allocation.ALLOCATION).exists() is (phase == "checkout")
    assert down.main([str(repo), "scratch", record["name"], "--slot", str(record["slot"])]) == 0
    assert not marker.parent.exists()


def test_metadata_write_failure_publishes_no_allocation_and_leaves_no_claim(
    allocated_subject, monkeypatch
):
    _, args = allocated_subject
    original = json.dump

    def refuse(record, stream, **kwargs):
        if "environment" in record:
            raise OSError("ownership write failed")
        return original(record, stream, **kwargs)

    monkeypatch.setattr(json, "dump", refuse)
    with pytest.raises(OSError, match="ownership write failed"):
        launch.launch(args)
    assert not list(allocation.state_path().glob("scratch-slot*"))
