"""OpenCode occupancy: the worker in the worktree counts, servers and other directories do not."""

import subprocess

from slopmeister.threads import occupants

WORKTREE = "/work/repo/.worktrees/demo"
PROCESSES = {
    101: ("/opt/bin/opencode", f"/opt/bin/opencode {WORKTREE} --prompt kickoff", WORKTREE),
    102: ("/opt/bin/opencode", "/opt/bin/opencode serve --port 4096", WORKTREE),
    103: ("/opt/bin/opencode", "/opt/bin/opencode /elsewhere", "/elsewhere"),
    104: ("/opt/bin/opencode", "/opt/bin/opencode run --format json", f"{WORKTREE}/sub"),
}


def _run(args):
    def done(out):
        return subprocess.CompletedProcess(args, 0, out, "")

    if args[:3] == ["ps", "-ww", "-axo"]:
        return done("".join(f"{pid} ttys001 {row[0]}\n" for pid, row in PROCESSES.items()))
    pids = [int(pid) for pid in args[args.index("-p") + 1].split(",")]
    if args[0] == "lsof":
        return done("".join(f"p{pid}\nfcwd\nn{PROCESSES[pid][2]}\n" for pid in pids))
    if args[-1] == "pid=,args=":
        return done("".join(f"{pid} {PROCESSES[pid][1]}\n" for pid in pids))
    return done("".join(f"{pid} S Mon Jan 1 {PROCESSES[pid][0]}\n" for pid in pids))


def test_only_opencode_workers_inside_the_worktree_occupy_it(monkeypatch):
    """Bug: a background `opencode serve` blocks a launch, or a worker elsewhere counts here."""
    monkeypatch.setattr(occupants, "run", _run)
    monkeypatch.setattr(occupants.os.path, "realpath", lambda path: path)
    found = {p.pid: p for p in occupants.processes(WORKTREE, None)}
    assert sorted(found) == [101, 103, 104]
    assert [p.pid for p in found.values() if p.inside] == [101, 104]
    assert all(p.kind == "opencode" for p in found.values())
