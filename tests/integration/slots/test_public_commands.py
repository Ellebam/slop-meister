"""Public Task slot commands allocate, inspect and release one disposable repository."""

from pathlib import Path
import socket
import subprocess

from tests.integration.launch.helpers import ROOT, executable, machine, target
from tests.support.repos import git


def _port() -> int:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    listener.close()
    return port


def _world(tmp_path):
    world = machine(tmp_path)
    repository = target(tmp_path / "repo")
    plot = world.root / "plots/slopmeister/plot.toml"
    plot.parent.mkdir(parents=True, exist_ok=True)
    plot.write_text(
        '[plot]\nbase = "code"\n\n[target]\ntasks = "manual"\n'
        '\n[target.repository]\ncommit = "allow"\n\n[slots]\nmax = 2\n'
        f"\n[slots.ports]\nWEB = {_port() - 1}\n"
    )
    executable(tmp_path / "bin/docker", "#!/bin/sh\nexit 1\n")
    env = dict(world.env, SLOT_STATE_DIR=str(tmp_path / "slots"))
    return world, repository, env


def _docker_script(log: Path, container: Path, network: Path) -> str:
    return (
        "#!/bin/sh\n"
        f"echo \"$*\" >> '{log}'\n"
        'case "$1" in\n'
        "  info) exit 0 ;;\n"
        "  compose)\n"
        "    shift\n"
        "    manifest=\n"
        "    while [ $# -gt 0 ]; do\n"
        '      [ "$1" = -f ] && manifest=$2\n'
        "      shift\n"
        "    done\n"
        '    [ -f "$manifest" ] || exit 91\n'
        f"    touch '{container}' '{network}'\n"
        "    exit 0 ;;\n"
        f"  ps) [ -f '{container}' ] && printf 'c1\\tfixture-api\\tUp 1 second\\n'; exit 0 ;;\n"
        "  volume) exit 0 ;;\n"
        "  network)\n"
        f"    [ \"$2\" = ls ] && {{ [ -f '{network}' ] && "
        "printf 'n1\\tfixture-default\\n'; exit 0; }\n"
        f"    [ \"$2\" = rm ] && rm -f '{network}'\n"
        "    exit 0 ;;\n"
        f"  rm) rm -f '{container}'; exit 0 ;;\n"
        "esac\n"
        "exit 1\n"
    )


def _compose_world(tmp_path):
    world, repository, env = _world(tmp_path)
    manifest = repository / "docker/compose.yml"
    manifest.parent.mkdir()
    manifest.write_text("services: {}\n")
    git(repository, "add", "docker/compose.yml")
    git(repository, "commit", "-q", "-m", "Add stack")
    plot = world.root / "plots/slopmeister/plot.toml"
    plot.write_text(
        plot.read_text().replace("max = 2\n", 'max = 2\ncompose = "docker/compose.yml"\n')
    )
    log = tmp_path / "docker.log"
    container, network = tmp_path / "container", tmp_path / "network"
    executable(tmp_path / "bin/docker", _docker_script(log, container, network))
    return world, repository, env, log


def _task(env, *args, input_text=""):
    return subprocess.run(
        ["task", *args],
        cwd=ROOT,
        env=env,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=90,
    )


def _assert_allocated(repository, env):
    worktree = repository / ".worktrees/slopmeister-one"
    allocation = worktree / ".slot.env"
    assert allocation.is_file() and "SLOT=1\n" in allocation.read_text()
    status = _task(env, "slot:status", "--", str(repository))
    assert status.returncode == 0 and "slopmeister-one slot 1 slopmeister" in status.stdout
    return worktree


def _assert_released(repository, tmp_path, worktree):
    assert not worktree.exists() and not (tmp_path / "slots/slopmeister-slot1").exists()
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "show-ref",
            "--verify",
            "refs/heads/slopmeister-one",
        ]
    )
    assert result.returncode == 0


def test_public_up_status_down_round_trip_is_deterministic(tmp_path):
    """Bug: the Python port changed allocation, handoff, status or teardown user behavior."""
    _, repository, env = _world(tmp_path)
    kickoff = "Mode: freeform\nslot fixture\n"
    up = _task(
        env,
        "slot:up",
        "--",
        str(repository),
        "slopmeister",
        "slopmeister-one",
        "--tool",
        "claude",
        input_text=kickoff,
    )
    assert up.returncode == 0, up.stdout + up.stderr
    worktree = _assert_allocated(repository, env)
    down = _task(env, "slot:down", "--", str(repository), "slopmeister", "slopmeister-one")
    assert down.returncode == 0, down.stdout + down.stderr
    _assert_released(repository, tmp_path, worktree)


def test_public_compose_starts_from_prepared_worktree_and_reports_resources(tmp_path):
    """Bug: repository-owned Compose ran before preparation and status hid its live resources."""
    _, repository, env, log = _compose_world(tmp_path)
    up = _task(
        env,
        "slot:up",
        "--",
        str(repository),
        "slopmeister",
        "slopmeister-one",
        "--tool",
        "claude",
        input_text="Mode: freeform\ncompose fixture\n",
    )
    assert up.returncode == 0, up.stdout + up.stderr
    worktree = repository / ".worktrees/slopmeister-one"
    assert f"-f {worktree / 'docker/compose.yml'}" in log.read_text()
    status = _task(env, "slot:status", "--", str(repository))
    assert "slopmeister-one container fixture-api Up 1 second" in status.stdout
    assert "slopmeister-one network fixture-default" in status.stdout
    down = _task(env, "slot:down", "--", str(repository), "slopmeister", "slopmeister-one")
    assert down.returncode == 0, down.stdout + down.stderr
    assert "rm -f c1" in log.read_text() and "network rm n1" in log.read_text()
    _assert_released(repository, tmp_path, worktree)


def test_public_up_refuses_an_existing_compose_project_before_allocation(tmp_path):
    """Bug: slot:up silently adopted stale exact-label Docker resources."""
    _, repository, env, log = _compose_world(tmp_path)
    (tmp_path / "container").touch()
    result = _task(
        env,
        "slot:up",
        "--",
        str(repository),
        "slopmeister",
        "slopmeister-one",
        input_text="Mode: freeform\ncompose fixture\n",
    )
    assert result.returncode != 0
    assert "fixture-api occupies slopmeister-slot1" in result.stderr
    assert not (repository / ".worktrees/slopmeister-one").exists()
    assert not (tmp_path / "slots/slopmeister-slot1").exists()
    assert all(not line.startswith("compose ") for line in log.read_text().splitlines())


def test_public_down_refuses_a_worker_edited_slot_number(tmp_path):
    """Bug: an edited worktree SLOT redirected teardown to another allocation."""
    _, repository, env = _world(tmp_path)
    up = _task(
        env,
        "slot:up",
        "--",
        str(repository),
        "slopmeister",
        "slopmeister-one",
        input_text="Mode: freeform\nslot fixture\n",
    )
    assert up.returncode == 0, up.stdout + up.stderr
    worktree = repository / ".worktrees/slopmeister-one"
    path = worktree / ".slot.env"
    path.write_text(path.read_text().replace("SLOT=1\n", "SLOT=2\n"))
    down = _task(env, "slot:down", "--", str(repository), "slopmeister", "slopmeister-one")
    assert down.returncode != 0 and "owned state slot 1" in down.stderr
    assert worktree.is_dir() and (tmp_path / "slots/slopmeister-slot1").is_dir()
    path.write_text((tmp_path / "slots/slopmeister-slot1/.slot.env").read_text())
    released = _task(env, "slot:down", "--", str(repository), "slopmeister", "slopmeister-one")
    assert released.returncode == 0
    assert not worktree.exists() and not (tmp_path / "slots/slopmeister-slot1").exists()


def test_public_down_is_retry_safe_by_explicit_slot_number(tmp_path):
    """Bug: a repeated cleanup guessed the removed allocation or failed after success."""
    _, repository, env = _world(tmp_path)
    result = _task(
        env,
        "slot:down",
        "--",
        str(repository),
        "slopmeister",
        "slopmeister-missing",
        "--slot",
        "1",
    )
    assert result.returncode == 0 and "nothing live for slopmeister-slot1" in result.stdout


def test_public_down_by_number_refuses_another_live_slot(tmp_path):
    """Bug: a mistyped missing name tore resources out from under another live slot."""
    _, repository, env = _world(tmp_path)
    worktree = repository / ".worktrees/slopmeister-other"
    data = Path(env["SLOT_STATE_DIR"]) / "slopmeister-slot2"
    allocation = "SLOT=2\nSLOT_TARGET=slopmeister\nSLOT_NAME=slopmeister-other\n"
    worktree.mkdir(parents=True)
    data.mkdir(parents=True)
    (worktree / ".slot.env").write_text(allocation)
    result = _task(
        env,
        "slot:down",
        "--",
        str(repository),
        "slopmeister",
        "slopmeister-typo",
        "--slot",
        "2",
    )
    assert result.returncode != 0 and "slot 2" in result.stderr and "live" in result.stderr
    assert worktree.is_dir() and data.is_dir()
