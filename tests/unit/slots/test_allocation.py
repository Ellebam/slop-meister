from pathlib import Path
import subprocess

import pytest

from slopmeister.errors import SlopmeisterError
from slopmeister.slots import allocation, down, status, up


def slot_identity(tmp_path, monkeypatch, worktree_slot=1):
    text = f"SLOT={worktree_slot}\nSLOT_TARGET=scratch\nSLOT_NAME=scratch-one\n"
    worktree = tmp_path / "repo/.worktrees/scratch-one"
    state = tmp_path / "slots/scratch-slot1"
    worktree.mkdir(parents=True)
    state.mkdir(parents=True)
    (worktree / allocation.ALLOCATION).write_text(text)
    (state / allocation.ALLOCATION).write_text(text.replace(f"SLOT={worktree_slot}", "SLOT=1"))
    monkeypatch.setenv("SLOT_STATE_DIR", str(tmp_path / "slots"))
    return worktree


def test_port_expansion_is_sorted_and_stable():
    """Bug: recreating a slot changed its port set."""
    slots = {"ports": {"WEB": 4000, "API": 3000}}
    assert allocation.expand(slots, 2) == {"API": 3002, "WEB": 4002}


def test_allocation_reads_only_strict_identity_rows(tmp_path):
    """Bug: edited resource paths in .slot.env redirected destructive teardown."""
    path = tmp_path / ".slot.env"
    path.write_text(
        "SLOT=2\nSLOT_TARGET=scratch\nSLOT_NAME=scratch-one\n"
        "SLOT_DATA=/tmp/foreign\nSLOT_COMPOSE=/tmp/foreign.yml\n"
    )
    assert allocation.read(path) == allocation.Live("scratch", 2, "scratch-one", tmp_path)


@pytest.mark.parametrize(
    "text",
    [
        "SLOT=0\nSLOT_TARGET=scratch\nSLOT_NAME=scratch-one\n",
        "SLOT=1\nSLOT_TARGET=Bad\nSLOT_NAME=scratch-one\n",
        "SLOT=1\nSLOT_TARGET=scratch\nSLOT_NAME=../one\n",
    ],
)
def test_malformed_allocation_cannot_authorize_teardown(tmp_path, text):
    """Bug: malformed slot identity was read as an available or deletable allocation."""
    (path := tmp_path / ".slot.env").write_text(text)
    with pytest.raises(SlopmeisterError, match="strict shape"):
        allocation.read(path)


def test_compose_symlink_cannot_escape_checkout(tmp_path):
    """Bug: compose teardown followed a worktree symlink to a foreign file."""
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside.yml"
    outside.write_text("services: {}\n")
    (root / "stack.yml").symlink_to(outside)
    with pytest.raises(SlopmeisterError, match="outside the checkout"):
        allocation.resolve_compose(root, "stack.yml")


def test_project_resources_are_selected_only_by_exact_compose_label(monkeypatch):
    """Bug: status or teardown guessed resources from editable manifest names."""
    calls = []
    outputs = {
        ("ps", "-a"): "c1\towned-api\tUp 10 seconds\n",
        ("volume", "ls"): "owned-data\towned-data\n",
        ("network", "ls"): "n1\towned-default\n",
    }

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, outputs.get(tuple(argv[1:3]), ""), "")

    monkeypatch.setattr(allocation.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(allocation, "run", run)
    resources = allocation.project_resources("scratch-slot2")
    assert resources == (
        allocation.Resource("container", "c1", "owned-api", "Up 10 seconds"),
        allocation.Resource("volume", "owned-data", "owned-data"),
        allocation.Resource("network", "n1", "owned-default"),
    )
    assert all("label=com.docker.compose.project=scratch-slot2" in call for call in calls[1:])


def test_remove_project_deletes_only_inventoried_ids(monkeypatch):
    """Bug: an edited Compose manifest could steer teardown to a foreign named resource."""
    inventories = iter(
        [
            (
                allocation.Resource("container", "c-owned", "owned-api"),
                allocation.Resource("volume", "v-owned", "owned-data"),
                allocation.Resource("network", "n-owned", "owned-default"),
            ),
            (),
        ]
    )
    calls = []
    monkeypatch.setattr(allocation, "project_resources", lambda project: next(inventories))
    monkeypatch.setattr(
        allocation,
        "run",
        lambda argv, **kwargs: calls.append(argv) or subprocess.CompletedProcess(argv, 0),
    )
    assert allocation.remove_project("scratch-slot2") == ["containers", "volumes", "networks"]
    assert calls == [
        ["docker", "rm", "-f", "c-owned"],
        ["docker", "volume", "rm", "v-owned"],
        ["docker", "network", "rm", "n-owned"],
    ]
    assert not any("foreign" in field for call in calls for field in call)


def test_written_environment_is_sorted_and_private_values_are_literal(tmp_path):
    """Bug: shell metacharacters were evaluated or allocation order changed between runs."""
    live = allocation.Live("scratch", 1, "scratch-one", Path("/worktree"))
    claim = allocation.Claim(live, tmp_path, None, {"WEB": 4001, "API": 3001})
    path = tmp_path / ".slot.env"
    allocation.write(path, claim)
    assert path.read_text().splitlines() == sorted(path.read_text().splitlines())
    assert "SLOT_DATA=" + str(tmp_path) in path.read_text()


def test_failed_allocation_write_releases_the_claim_directory(tmp_path, monkeypatch):
    """Bug: a failed .slot.env write left residue that permanently consumed the slot."""
    state = tmp_path / "slots"
    monkeypatch.setenv("SLOT_STATE_DIR", str(state))
    monkeypatch.setattr(up, "_available", lambda request, root, slots: 1)
    monkeypatch.setattr(allocation, "bound_ports", lambda: [])
    monkeypatch.setattr(
        allocation, "write", lambda path, claim: (_ for _ in ()).throw(OSError("disk full"))
    )
    request = up.Request("repo", "scratch", "scratch-one", "", [])
    with pytest.raises(OSError, match="disk full"):
        up._claim(request, {"ports": {"WEB": 4000}}, tmp_path / "repo")
    assert not (state / "scratch-slot1").exists()


def test_down_refuses_a_worktree_slot_that_disagrees_with_owned_state(tmp_path, monkeypatch):
    """Bug: edited SLOT selected another live slot's resources for destructive teardown."""
    worktree = slot_identity(tmp_path, monkeypatch, 2)
    monkeypatch.setattr(down, "_occupied", lambda worktree, project: None)
    clean = subprocess.CompletedProcess([], 0, "", "")
    monkeypatch.setattr(allocation, "run", lambda argv, **kwargs: clean)
    item = down.Request("/repo", "scratch", "scratch-one", False, "")
    with pytest.raises(SlopmeisterError, match="owned state.*slot 1"):
        down._worktree_slot(item, worktree)
    honest = (tmp_path / "slots/scratch-slot1" / allocation.ALLOCATION).read_text()
    (worktree / allocation.ALLOCATION).write_text(honest)
    (other := tmp_path / "repo/.worktrees/scratch-two").mkdir()
    (other / allocation.ALLOCATION).write_text(honest.replace("scratch-one", "scratch-two"))
    with pytest.raises(SlopmeisterError, match="also claimed by worktree"):
        down._worktree_slot(item, worktree)


def test_down_refuses_an_occupied_worktree_before_git_or_resource_cleanup(tmp_path, monkeypatch):
    """Bug: resource teardown removed a worktree from under its live worker."""
    worktree = slot_identity(tmp_path, monkeypatch)
    monkeypatch.setattr(
        allocation,
        "run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, "claude pid 42\n", ""),
    )
    with pytest.raises(SlopmeisterError, match="worker still occupies"):
        down._worktree_slot(down.Request("/repo", "scratch", "scratch-one", True, ""), worktree)


def test_down_requires_force_for_dirty_worktree_then_accepts_it(tmp_path, monkeypatch):
    """Bug: ordinary down deleted uncommitted work, or --force could not confirm it."""
    worktree = slot_identity(tmp_path, monkeypatch)
    monkeypatch.setattr(down, "_occupied", lambda worktree, project: None)
    monkeypatch.setattr(
        allocation,
        "run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, "?? local.txt\n", ""),
    )
    with pytest.raises(SlopmeisterError, match="uncommitted work"):
        down._worktree_slot(down.Request("/repo", "scratch", "scratch-one", False, ""), worktree)
    forced = down.Request("/repo", "scratch", "scratch-one", True, "")
    assert down._worktree_slot(forced, worktree) == 1


def test_down_refuses_the_current_worktree(tmp_path, monkeypatch):
    """Bug: down removed the worktree containing the invoking shell."""
    root = tmp_path / "repo"
    worktree = root / ".worktrees/scratch-one"
    worktree.mkdir(parents=True)
    monkeypatch.chdir(worktree)
    monkeypatch.setattr(allocation, "definition", lambda target: {"max": 2})
    monkeypatch.setattr(allocation, "main_root", lambda repo: root)
    with pytest.raises(SlopmeisterError, match="this shell's worktree"):
        down._context(down.Request(str(root), "scratch", "scratch-one", False, ""))


def test_down_refuses_allocation_identity_that_disagrees_with_request(tmp_path):
    """Bug: a mismatched allocation authorized deletion under caller-supplied names."""
    worktree = tmp_path / "repo/.worktrees/scratch-one"
    worktree.mkdir(parents=True)
    (worktree / allocation.ALLOCATION).write_text(
        "SLOT=1\nSLOT_TARGET=other\nSLOT_NAME=scratch-one\n"
    )
    with pytest.raises(SlopmeisterError, match="names target 'other'"):
        down._worktree_slot(down.Request("/repo", "scratch", "scratch-one", False, ""), worktree)


def test_down_by_number_refuses_another_session_residue(tmp_path, monkeypatch):
    """Bug: a stale or mistyped name deleted another session's surviving slot data."""
    root, state = tmp_path / "repo", tmp_path / "slots"
    root.mkdir()
    data = state / "scratch-slot2"
    data.mkdir(parents=True)
    (data / allocation.ALLOCATION).write_text(
        "SLOT=2\nSLOT_TARGET=scratch\nSLOT_NAME=scratch-other\n"
    )
    monkeypatch.setenv("SLOT_STATE_DIR", str(state))
    monkeypatch.setattr(allocation, "definition", lambda target: {"max": 2})
    monkeypatch.setattr(allocation, "main_root", lambda repo: root)
    monkeypatch.setattr(allocation, "live", lambda current: [])
    request = down.Request(str(root), "scratch", "scratch-typo", False, "2")
    with pytest.raises(SlopmeisterError, match="allocation names scratch-slot2.*scratch-other"):
        down._context(request)


def test_status_attributes_live_worker_from_shared_occupant_census(tmp_path, monkeypatch, capsys):
    """Bug: live status omitted a Claude worker that teardown correctly treated as an occupant."""
    item = allocation.Live("scratch", 1, "scratch-one", tmp_path / "scratch-one")
    monkeypatch.setattr(
        allocation,
        "run",
        lambda argv, **kwargs: subprocess.CompletedProcess(
            argv, 0, f"claude pid 42 in {item.worktree}\n", ""
        ),
    )
    status._workers([item])
    assert "scratch-one worker claude pid 42" in capsys.readouterr().out


def test_listener_cwd_failure_is_not_reported_as_an_empty_inventory(monkeypatch):
    """Bug: a failed native cwd census silently hid slot listeners."""
    monkeypatch.setattr(status.shutil, "which", lambda name: "/usr/bin/lsof")
    monkeypatch.setattr(
        allocation,
        "run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 1, "", "denied"),
    )
    with pytest.raises(SlopmeisterError, match="listener working directories"):
        status._working_directories([42])
