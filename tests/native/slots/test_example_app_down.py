"""A real stand-in worker releases its own slot, read through the real process inventory."""

from pathlib import Path
import shlex
import subprocess
import tempfile
import time

from tests.integration.launch.helpers import CLI, ROOT
from tests.integration.slots.test_public_commands import _task, _world
from tests.support.repos import git

NAME = "slopmeister-one"
# The stand-in waits for the test, starts a child, runs the cleanup as a real worker would, waits.
WORKER = """\
while [ ! -e "$GO" ]; do /bin/sleep 0.1; done
/bin/sleep 300 &
echo $! > "$CHILD"
/bin/sh -c 'cd "$ROOT" && exec "$CLI" slots down "$REPO" slopmeister "$NAME" --self' > "$OUT" 2>&1
wait
"""


def _stand_in(cwd: Path, argv: list[str], env: dict[str, str]) -> subprocess.Popen:
    """A process the census reads as a Claude worker in `cwd`."""
    # macOS names a process by its first argument and Linux by the file it executed, so the
    # program runs through a link called claude and under that name. The program must keep
    # that name: Ubuntu's sleep is a multi-call binary and refuses it, and a Python that starts
    # through a launcher, as Homebrew's does, replaces itself under another one.
    link = Path(tempfile.mkdtemp(dir=Path(env["GO"]).parent)) / "claude"
    link.symlink_to(argv[0])
    line = "exec -a claude " + " ".join(shlex.quote(part) for part in (str(link), *argv[1:]))
    worker = subprocess.Popen(["/bin/bash", "-c", line], cwd=cwd, env=env, stdin=subprocess.PIPE)
    _until(lambda: _ps(worker.pid, "comm=") == "claude")
    return worker


def _ps(pid: int, column: str) -> str:
    result = subprocess.run(["ps", "-p", str(pid), "-o", column], capture_output=True, text=True)
    return result.stdout.strip()


def _until(done, seconds: float = 30) -> None:
    deadline = time.monotonic() + seconds
    while not done():
        assert time.monotonic() < deadline, "the awaited state never arrived"
        time.sleep(0.1)


def _down(env: dict[str, str], repository: Path, flag: str) -> subprocess.CompletedProcess[str]:
    command = [str(CLI), "slots", "down", str(repository), "slopmeister", NAME, flag]
    return subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=90)


def _slot(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    _, repository, env = _world(tmp_path)
    up = _task(env, "slot:up", "--", str(repository), "slopmeister", NAME, input_text="Mode: x\n")
    assert up.returncode == 0, up.stdout + up.stderr
    (tmp_path / "worker.sh").write_text(WORKER)
    (tmp_path / "other").mkdir()
    paths = {key: str(tmp_path / key.lower()) for key in ("GO", "CHILD", "OUT")}
    return repository, dict(
        env, ROOT=str(ROOT), CLI=str(CLI), REPO=str(repository), NAME=NAME, **paths
    )


def _assert_released(tmp_path: Path, repository: Path, env: dict[str, str]) -> None:
    worktree, log = repository / ".worktrees" / NAME, tmp_path / f"slots/{NAME}.down.log"
    _until(lambda: log.is_file() and "released" in log.read_text())
    assert "slopmeister-slot1 released, data worktree" in log.read_text()
    assert str(log) in Path(env["OUT"]).read_text()
    assert _ps(int(Path(env["CHILD"]).read_text()), "stat=") in ("", "Z")
    assert not worktree.exists() and not (tmp_path / "slots/slopmeister-slot1").exists()
    assert str(worktree) not in git(repository, "worktree", "list")


def test_worker_releases_its_own_slot_and_nobody_else_can(tmp_path):
    """Bug: the cleanup died with its worker, hit a neighbour, or ran without the worker's word."""
    repository, env = _slot(tmp_path)
    worktree = repository / ".worktrees" / NAME
    # Idle without a child: bash waits on the pipe that the test holds open.
    neighbour = _stand_in(tmp_path / "other", ["/bin/bash", "-c", "read"], env)
    worker = _stand_in(worktree, ["/bin/bash", str(tmp_path / "worker.sh")], env)
    try:
        plain = _down(env, repository, "--force")
        assert plain.returncode != 0 and "worker still occupies" in plain.stderr
        foreign = _down(env, repository, "--self")
        assert foreign.returncode != 0 and f"claude pid {worker.pid}" in foreign.stderr
        assert "--self requires" in foreign.stderr and worktree.is_dir()
        Path(env["GO"]).touch()
        _assert_released(tmp_path, repository, env)
        assert worker.wait(timeout=30) is not None and neighbour.poll() is None
    finally:
        for process in (worker, neighbour):
            process.kill()
            process.wait()
