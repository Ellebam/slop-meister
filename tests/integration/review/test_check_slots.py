"""A diff check whose guide starts a service holds its own slot through the existing owner."""

import argparse
import json
from pathlib import Path
import subprocess
import sys

import pytest

from slopmeister.errors import SlopmeisterError
from slopmeister.review import check
from slopmeister.review.schema import CrossToolReviewError
from slopmeister.slots import allocation, compose, down, status, tester, up
from slopmeister.spine import candidate
from tests.support.repos import git, scratch_repo

PLOT = '[plot]\nbase="code"\n[target]\ntasks="github"\n[target.repository]\ncommit="allow"\n'


@pytest.fixture
def subject(tmp_path, monkeypatch):
    repo = scratch_repo(tmp_path / "subject")
    plots = tmp_path / "plots/scratch"
    plots.mkdir(parents=True)
    (plots / "plot.toml").write_text(PLOT + "[slots]\nmax=3\n[slots.ports]\nWEB=42000\n")
    guide = tmp_path / "guide.md"
    guide.write_text("### Scenario basic: Read subject\nRead README.md.\n")
    monkeypatch.setenv("PLOT_DECLARATIONS", str(plots.parent))
    monkeypatch.setenv("SLOT_STATE_DIR", str(tmp_path / "slots"))
    monkeypatch.setattr(allocation, "bound_ports", lambda: [])
    monkeypatch.setattr(tester.occupants, "census", lambda checkout: [])
    monkeypatch.setattr(status, "_workers", lambda current: None)
    args = argparse.Namespace(
        cwd=str(repo), guide=str(guide), subject_manifest=None, slot_target="scratch"
    )
    return repo, args


def held(prepared):
    return allocation.read(prepared.checkout / ".slot.env")


def claims():
    return list(allocation.state_path().glob("scratch-slot*"))


def test_concurrent_checks_get_distinct_slots_and_release_them(subject, capsys):
    repo, args = subject
    with check.prepared(args, None) as first, check.prepared(args, None) as second:
        items = [held(first), held(second)]
        assert [item.slot for item in items] == [1, 2] and items[0].name != items[1].name
        assert git(first.checkout, "status", "--porcelain").strip() == ""
        status.live(str(repo))
        output = capsys.readouterr().out
        assert all(item.name in output for item in items)
    assert not claims() and not first.checkout.exists() and not first.cleanup_error
    assert git(repo, "status", "--porcelain").strip() == ""


def test_running_check_holds_its_lease_until_it_ends(subject):
    repo, args = subject
    with check.prepared(args, None) as prepared:
        item = held(prepared)
        command = [str(repo), "scratch", item.name, "--slot", str(item.slot)]
        with pytest.raises(SlopmeisterError, match="a diff check still holds this allocation"):
            down.main(command)
    assert not claims()


def test_preparation_failure_releases_its_slot(subject, monkeypatch):
    _, args = subject

    def refuse(claim, evidence):
        assert (Path(claim.live.worktree) / ".slot.env").is_file()
        raise OSError("stack unavailable")

    monkeypatch.setattr(compose, "_compose_up", refuse)
    with pytest.raises(CrossToolReviewError, match="stack unavailable"), check.prepared(args, None):
        pytest.fail("a check without its slot must not run")
    assert not claims()


def test_allocation_preserves_the_frozen_candidate_tree(subject):
    repo, args = subject
    (repo / "new.txt").write_text("candidate-only content")
    frozen = candidate.freeze(repo, "scratch-candidate")
    with check.prepared(args, frozen) as prepared:
        assert (prepared.checkout / "new.txt").read_text() == "candidate-only content"
        assert held(prepared).slot == 1
        prepared.verify()
        assert candidate.worktree_tree(prepared.checkout) == frozen.tree
    assert not claims()


@pytest.mark.parametrize("destination", ["tracked", "dangling"])
def test_existing_allocation_destination_is_never_overwritten(subject, monkeypatch, destination):
    repo, args = subject
    outside = repo.parent / "outside"
    outside.write_text("private sentinel")
    if destination == "tracked":
        (repo / ".slot.env").write_text("tracked content")
        git(repo, "add", ".slot.env")
        git(repo, "commit", "-qm", "Track allocation fixture")
    else:
        original = check._checkout

        def checkout(prepared, frozen):
            original(prepared, frozen)
            (prepared.checkout / ".slot.env").symlink_to(outside.parent / "absent")

        monkeypatch.setattr(check, "_checkout", checkout)
    with (
        pytest.raises(CrossToolReviewError, match="allocation destination already exists"),
        check.prepared(args, None),
    ):
        pass
    assert outside.read_text() == "private sentinel"
    assert not claims()


@pytest.mark.parametrize("phase", ["state", "checkout"])
def test_interrupted_allocation_is_readable_and_recoverable(subject, capsys, phase):
    repo, args = subject
    boundary = "allocation.write" if phase == "state" else "tester._deliver"
    program = (
        "import argparse,json,os,sys; "
        "from slopmeister.slots import allocation,tester; from slopmeister.review import check; "
        f"{boundary}=lambda *args: os._exit(23); allocation.bound_ports=lambda: []; "
        "check.prepared(argparse.Namespace(**json.loads(sys.argv[1])), None).__enter__()"
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


def test_metadata_write_failure_publishes_no_allocation(subject, monkeypatch):
    _, args = subject
    original = json.dump

    def refuse(record, stream, **kwargs):
        if "environment" in record:
            raise OSError("ownership write failed")
        return original(record, stream, **kwargs)

    monkeypatch.setattr(json, "dump", refuse)
    with (
        pytest.raises(CrossToolReviewError, match="ownership write failed"),
        check.prepared(args, None),
    ):
        pass
    assert not claims()


def test_unreadable_record_does_not_hide_other_slot_status(subject, capsys):
    repo, args = subject
    with check.prepared(args, None) as prepared:
        damaged = allocation.state_path() / "scratch-slot3/tester.json"
        damaged.parent.mkdir()
        damaged.write_text("")
        status.live(str(repo))
        output = capsys.readouterr().out
        assert held(prepared).name in output and "unreadable tester" in output
    assert damaged.read_bytes() == b""


def test_dangling_ownership_record_cannot_bypass_recovery_with_force(subject):
    repo, args = subject
    with check.prepared(args, None) as prepared:
        item = held(prepared)
        data = allocation.state_path() / f"scratch-slot{item.slot}"
        marker = data / tester.RECORD
        marker.unlink()
        marker.symlink_to(repo.parent / "absent-owner")
        with pytest.raises(SlopmeisterError, match="unreadable tester ownership"):
            down.main([str(repo), "scratch", item.name, "--slot", str(item.slot), "--force"])
    assert data.is_dir() and marker.is_symlink() and prepared.cleanup_error


class FakeDocker:
    """Exact-label Docker state, so tests see what Compose started and what release removed."""

    def __init__(self, healthy=True):
        self.healthy, self.resources, self.calls = healthy, {}, []

    def compose(self, argv, ok=True):
        self.calls.append(["compose", *argv])
        project = argv[argv.index("-p") + 1]
        if "up" in argv:
            self.resources[project] = [
                allocation.Resource("container", "c1", f"{project}-db", "running"),
                allocation.Resource("network", "n1", f"{project}_default"),
            ]
        return subprocess.CompletedProcess(argv, 0 if self.healthy else 1, "", "unhealthy db")

    def project_resources(self, project):
        return tuple(self.resources.get(project, []))

    def run(self, original):
        def run(argv, **kwargs):
            if argv[0] != "docker":
                return original(argv, **kwargs)
            self.calls.append(argv)
            if "logs" in argv:
                assert self.resources["scratch-slot3"], "logs attempted after teardown"
                kwargs["stdout"].write(b"db | check startup marker\xff\n")
                return subprocess.CompletedProcess(argv, 0)
            if argv[1:3] == ["ps", "-a"]:
                return subprocess.CompletedProcess(argv, 0, "img:1\nimg:1\n", "")
            if argv[1:3] in (["rm", "-f"], ["network", "rm"]):
                for items in self.resources.values():
                    items[:] = [item for item in items if item.identifier not in argv]
            return subprocess.CompletedProcess(argv, 0, "", "")

        return run


@pytest.fixture
def composed(subject, monkeypatch):
    repo, args = subject
    (repo / "stack.yml").write_text("services: {}\n")
    git(repo, "add", "stack.yml")
    git(repo, "commit", "-qm", "Add stack fixture")
    (Path(allocation.declarations_path()) / "scratch/plot.toml").write_text(
        PLOT + '[slots]\nmax=2\ntesters=1\ncompose="stack.yml"\n[slots.ports]\nWEB=42000\n'
    )
    docker = FakeDocker()
    monkeypatch.setattr(allocation, "compose", docker.compose)
    monkeypatch.setattr(allocation, "project_resources", docker.project_resources)
    monkeypatch.setattr(allocation, "run", docker.run(allocation.run))
    monkeypatch.setattr(subprocess, "run", docker.run(subprocess.run))
    workers = {}
    for number in (1, 2):
        data = allocation.state_path() / f"scratch-slot{number}"
        data.mkdir(parents=True)
        (data / allocation.ALLOCATION).write_text(f"SLOT={number}\nSLOT_NAME=scratch-w{number}\n")
        workers[data] = (data / allocation.ALLOCATION).read_bytes()
    return repo, args, docker, workers


def test_tester_only_slot_starts_its_own_stack_and_release_removes_only_it(composed):
    _, args, docker, workers = composed
    with check.prepared(args, None) as prepared:
        assert held(prepared).slot == 3 and docker.project_resources("scratch-slot3")
        start = next(call for call in docker.calls if "up" in call)
        assert start[start.index("-f") + 1] == str((prepared.checkout / "stack.yml").resolve())
        assert start[start.index("-p") + 1] == "scratch-slot3"
        with (
            pytest.raises(CrossToolReviewError, match="every tester slot of target 'scratch'"),
            check.prepared(args, None),
        ):
            pass
    assert docker.project_resources("scratch-slot3") == () and not prepared.cleanup_error
    assert not (allocation.state_path() / "scratch-slot3").exists()
    assert {data: data.joinpath(".slot.env").read_bytes() for data in workers} == workers
    # The stack's own image hands bind-mounted files back before the checkout goes.
    assert any(call[1] == "run" and "img:1" in call for call in docker.calls)


def test_unhealthy_stack_blocks_the_check_and_unwinds_only_its_slot(composed, monkeypatch):
    _, args, docker, workers = composed
    docker.healthy = False
    monkeypatch.setattr(compose.time, "sleep", lambda seconds: None)
    with pytest.raises(CrossToolReviewError, match="unhealthy db"), check.prepared(args, None):
        pytest.fail("a check without its stack must not run")
    assert docker.project_resources("scratch-slot3") == ()
    assert not (allocation.state_path() / "scratch-slot3").exists()
    assert {data: data.joinpath(".slot.env").read_bytes() for data in workers} == workers
    [log] = (Path(args.cwd).parent / "state/slopmeister/checks").glob("run-*/evidence/compose.log")
    assert log.read_bytes() == b"db | check startup marker\xff\n"
    assert log.stat().st_mode & 0o777 == 0o600
    calls = docker.calls
    assert next(i for i, call in enumerate(calls) if "logs" in call) < next(
        i for i, call in enumerate(calls) if call[1:3] == ["rm", "-f"]
    )


def test_declared_tester_range_is_never_given_to_a_worker(composed):
    repo, _, _, _ = composed
    slots = allocation.definition("scratch")
    request = up.Request(str(repo), "scratch", "scratch-w3", "", [])
    with pytest.raises(SlopmeisterError, match="every slot of target 'scratch'.*2 declared"):
        up._available(request, repo, slots)
    with pytest.raises(SlopmeisterError, match="--slot must be 1 to 2"):
        up._available(up.Request(str(repo), "scratch", "scratch-w3", "3", []), repo, slots)


def test_reclaim_failure_keeps_the_checkout_and_reports_it(subject, monkeypatch):
    _, args = subject

    def refuse(checkout, images):
        raise SlopmeisterError("cannot run docker")

    monkeypatch.setattr(check, "_reclaim", refuse)
    with check.prepared(args, None) as prepared:
        pass
    assert prepared.cleanup_error == "cannot run docker" and prepared.checkout.is_dir()
    assert "**Cleanup:** retained" in prepared.footer()


def test_failed_teardown_after_failed_startup_keeps_the_checkout(subject, monkeypatch, tmp_path):
    """Containers may still mount the checkout while their slot could not be released."""
    _, args = subject

    def refuse(claim, evidence):
        holder = allocation.Listener(claim.ports["WEB"], 72, "app")
        monkeypatch.setattr(allocation, "bound_ports", lambda: [holder])
        raise OSError("stack unavailable")

    monkeypatch.setattr(compose, "_compose_up", refuse)
    with pytest.raises(CrossToolReviewError, match="stack unavailable"), check.prepared(args, None):
        pytest.fail("a check without its slot must not run")
    [root] = (tmp_path / "state/slopmeister/checks").glob("run-*")
    assert (root / "checkout/README.md").is_file() and claims()
