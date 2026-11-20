"""A recorded stand-in worker proves self-cleanup leaves no live descendants or worktree."""

import json
import os
from pathlib import Path
import shlex
import subprocess
import time

import pytest

from slopmeister.install.fileops import lock_service_actions
from slopmeister.removal import remove_tree
from slopmeister.session.verify import snapshot
from tests.support.fakes import fake_binary
from tests.support.repos import GIT_ENV, git, scratch_repo

ROOT = Path(__file__).resolve().parents[3]
REPORT = (
    "**Result** The task is unfinished.\n"
    "**Proven** Keep the draft, slot and claim.\n"
    "**Your move** Finish the draft. Keep $(false) and $HOME literal.\n"
)
WORKER = (
    """while [ ! -e "$GO" ]; do /bin/sleep 0.1; done
/bin/sleep 300 &
echo $! > "$CHILD"
/bin/sh -c 'cd "$REPO" && "$CLI" workspace-remove --self -- "$WORKSPACE"' \\
  <<'HARVEST_REPORT' > "$OUT" 2>&1
"""
    + REPORT
    + """HARVEST_REPORT
wait
"""
)
# An Orca double with one open tab. It lists the tab under $TAB until a close names it.
ORCA = """reply() { echo '{"ok":true,"result":{'"$1"'}}'; }
case "$1 $2" in
"status --json") reply '"app":{"running":true},"runtime":{"reachable":true}' ;;
"terminal list")
  [ -e "$CLOSED" ] || row='{"handle":"term_fixture","worktreePath":"'"$TAB"'"}'
  reply '"truncated":false,"terminals":['"$row"']' ;;
"terminal close") echo "$4" > "$CLOSED"; reply ;;
esac"""


def _until(check):
    deadline = time.monotonic() + 30
    while not check():
        assert time.monotonic() < deadline, "cleanup did not finish"
        time.sleep(0.1)


def _ps(pid, column):
    result = subprocess.run(["ps", "-p", str(pid), "-o", column], capture_output=True, text=True)
    return result.stdout.strip()


def _worker(path, env, script, kind="claude"):
    link = Path(env["TEST_ROOT"]) / f"standin-{path.name}/{kind}"
    link.parent.mkdir()
    link.symlink_to("/bin/bash")
    command = f"exec -a {kind} " + shlex.join([str(link), "-c", script])
    process = subprocess.Popen(
        ["/bin/bash", "-c", command], cwd=path, env=env, stdin=subprocess.PIPE
    )
    _until(lambda: _ps(process.pid, "comm=") == kind)
    return process


def _world(tmp_path):
    repo = scratch_repo(tmp_path / "main")
    git(repo, "worktree", "add", "-q", "-b", "scratch", ".worktrees/scratch")
    path = repo / ".worktrees/scratch"
    metadata = repo / ".git/worktrees/scratch/slopmeister-config"
    metadata.mkdir()
    (metadata / "issue.json").write_text(json.dumps({"phase": "closed", "issue": 7}))
    with (repo / ".git/info/exclude").open("a") as stream:
        stream.write(".claude\n.codex\n")
    for native in (".claude", ".codex"):
        action = path / native / "service-actions/jira-read"
        action.mkdir(parents=True)
        (action / "entry.py").touch()
    lock_service_actions(path, True)
    saved = {"plot": "slopmeister", "files": snapshot(path, [".claude", ".codex"])}
    (metadata / "state.json").write_text(json.dumps(saved))
    other = tmp_path / "neighbour"
    other.mkdir()
    env = {
        **os.environ,
        **GIT_ENV,
        "TEST_ROOT": str(tmp_path),
        "REPO": str(repo),
        "WORKSPACE": str(path),
        "CLI": str(ROOT / "bin/slopmeister"),
        **{key: str(tmp_path / key.lower()) for key in ("GO", "CHILD", "OUT")},
        "PLOT_SESSION_STATE_DIR": str(tmp_path / "logs"),
        "SLOT_STATE_DIR": str(tmp_path / "slots"),
    }
    return repo, path, env, other


def _stop_owned(worker, neighbour, env):
    for process in (worker, neighbour):
        if process.poll() is None:
            process.kill()
        process.wait()
    if Path(env["CHILD"]).exists():
        pid = int(Path(env["CHILD"]).read_text())
        if _ps(pid, "stat=") not in ("", "Z"):
            os.kill(pid, 15)
    remove_tree(Path(env["TEST_ROOT"]))


@pytest.mark.xdist_group("workspace-removal-processes")
def test_example_app_removes_the_owned_worker_and_descendants_but_keeps_a_neighbour(tmp_path):
    """Bug: cleanup died with the worker, left ghosts, or stopped a sibling or foreign caller."""
    repo, path, env, other = _world(tmp_path)
    neighbour = _worker(other, env, "read")
    worker = _worker(path, env, WORKER)
    try:
        for flags in (["--force"], ["--self"]):
            refused = subprocess.run(
                [env["CLI"], "workspace-remove", str(path), *flags],
                cwd=repo,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert refused.returncode != 0 and path.exists(), refused.stdout + refused.stderr
        Path(env["GO"]).touch()
        logs = Path(env["PLOT_SESSION_STATE_DIR"])
        _until(lambda: any("workspace removed:" in p.read_text() for p in logs.glob("*.log")))
        assert not path.exists() and str(path) not in git(repo, "worktree", "list")
        assert worker.wait(timeout=30) is not None and neighbour.poll() is None
        assert _ps(int(Path(env["CHILD"]).read_text()), "stat=") in ("", "Z")
        assert "cleanup pending" in Path(env["OUT"]).read_text()
        assert all(p.stat().st_mode & 0o077 == 0 for p in logs.glob("*.log"))
        assert Path(env["OUT"]).read_text().startswith(REPORT)
        assert all(p.read_text().startswith(REPORT) for p in logs.glob("*.log"))
    finally:
        _stop_owned(worker, neighbour, env)


def _directory_session(tmp_path, env, notes):
    """A launched directory session with its saved plot and the tab its launcher recorded."""
    session = tmp_path / "sessions/desk"
    (session / ".slopmeister-config").mkdir(parents=True)
    (session / ".slopmeister-config/state.json").write_text(json.dumps({"plot": "example-notes"}))
    (session / "desk-NOTES.md").write_text(notes)
    logs = Path(env["PLOT_SESSION_STATE_DIR"])
    logs.mkdir()
    (logs / "desk.orca").write_text("term_fixture\n")
    env.update(
        WORKSPACE=str(session),
        PLOT_SESSION_ROOT=str(session.parent),
        PLOT_SESSION_ORCA=str(fake_binary(tmp_path / "bin", "orca", ORCA)),
        CLOSED=str(tmp_path / "closed"),
        # Orca registers the new directory as its own folder.
        TAB=str(session),
    )
    return session, logs


def _run(command, repo, env):
    return subprocess.run(command, cwd=repo, env=env, capture_output=True, text=True, timeout=30)


def test_directory_session_keeps_unsaved_content_without_force(tmp_path):
    """Bug: a directory session's self-removal deletes unsaved content without --force."""
    repo, _, env, _ = _world(tmp_path)
    session, _ = _directory_session(tmp_path, env, "")
    (session / "draft.md").write_text("unsaved\n")
    command = [env["CLI"], "workspace-remove", "--self", "--", str(session)]
    refused = _run(command, repo, env)
    assert refused.returncode != 0 and "ignored work" in refused.stderr
    assert (session / "draft.md").read_text() == "unsaved\n"


@pytest.mark.xdist_group("workspace-removal-processes")
@pytest.mark.parametrize("stop_only", [False, True])
def test_directory_session_ends_itself_and_closes_its_terminal(tmp_path, stop_only):
    """Bug: a directory session cannot end itself or its tab is sought under the wrong path."""
    repo, _, env, other = _world(tmp_path)
    # Harvest empties finished notes before removal. A stop keeps them for the next worker.
    session, logs = _directory_session(tmp_path, env, "retain this decision\n" if stop_only else "")
    flags = ["--self", "--stop-only", "--"] if stop_only else ["--self", "--"]
    done = "session stopped; workspace kept:" if stop_only else "workspace removed:"
    neighbour = _worker(other, env, "read")
    worker = _worker(session, env, WORKER.replace("--self --", " ".join(flags)))
    command = [env["CLI"], "workspace-remove", *flags, str(session)]
    try:
        refused = _run(command, repo, env)
        assert refused.returncode != 0 and "--self requires the calling worker" in refused.stderr
        assert not Path(env["CLOSED"]).exists() and worker.poll() is None
        Path(env["GO"]).touch()
        _until(lambda: any(done in p.read_text() for p in logs.glob("*.log")))
        assert worker.wait(timeout=30) is not None and neighbour.poll() is None
        assert _ps(int(Path(env["CHILD"]).read_text()), "stat=") in ("", "Z")
        assert Path(env["CLOSED"]).read_text() == "term_fixture\n"
        assert (session / "desk-NOTES.md").exists() is stop_only
        assert not (logs / "desk.orca").exists()
        assert all(p.read_text().startswith(REPORT) for p in logs.glob("*.log"))
    finally:
        _stop_owned(worker, neighbour, env)
