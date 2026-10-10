import json
import os
from pathlib import Path
import re
import shutil

import pytest

from tests.support.standin import Command, run

ROOT = Path(__file__).resolve().parents[2]
CLAUDE = shutil.which("claude")
CODEX = Path.home() / ".local/bin/codex"
TASK = (
    "Mode: spine\n\nTask SMOKE-1. Make this notes app keep notes between runs. "
    "The product direction is undecided: should notes stay local to this computer "
    "or sync across devices? For local storage, the file must live in the operator's home "
    "and work from every current directory."
)
SUMMARY = ("Goal", "Plan", "Your call", "Risk")
SUMMARY_WORDS = 150
MESSAGE_WORDS = 350
UNREADABLE = {
    "code or a command": r"`",
    "a file path": r"(?:^|\s)[~.]?/\w|\w/[\w.-]+/\w|\b[\w-]+\.[a-z][a-z0-9]+\b",
    "a link": r"https?://",
    "a line reference": r"\blines? \d+\b|[A-Za-z_]:\d+\b",
    "a commit hash": r"\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b",
    "a step name": r"\bstep \d",
}
SESSION_SECONDS = 300


@pytest.mark.timeout(SESSION_SECONDS + 30)
@pytest.mark.parametrize("tool", ["claude", "codex"])
def test_sow_sends_the_one_message_before_editing(tmp_path, tool):
    workspace = prepare(tmp_path)
    reply = claude(tmp_path, workspace) if tool == "claude" else codex(tmp_path, workspace)
    changes = git(tmp_path, workspace, ["status", "--porcelain"]).splitlines()
    assert [line for line in changes if not line.endswith("-NOTES.md")] == [], changes
    assert opening_faults(reply) == [], reply


def opening_faults(reply):
    """Why a reply is not the plain opening message. An empty list means it is."""
    starts, ends = [], []
    for name in (*SUMMARY, "Details"):
        part = re.search(rf"(?im)^[\s#*>-]*{name}\b", reply)
        if not part or (starts and part.start() < starts[-1]):
            return [f"{name} is missing or out of order"]
        starts.append(part.start())
        ends.append(part.end())
    bodies = [reply[end:start] for end, start in zip(ends, [*starts[1:], len(reply)], strict=True)]
    summary = reply[: starts[-1]]
    faults = [
        f"the summary contains {what}"
        for what, sign in UNREADABLE.items()
        if re.search(sign, summary, re.M | re.I)
    ]
    if reply[: starts[0]].strip():
        faults.append("text stands before Goal")
    if not all(re.search(r"\w", body) for body in bodies):
        faults.append("a part is empty")
    if len(summary.split()) > SUMMARY_WORDS:
        faults.append(f"the summary exceeds {SUMMARY_WORDS} words")
    if len(reply.split()) > MESSAGE_WORDS:
        faults.append(f"the message exceeds {MESSAGE_WORDS} words")
    if not asks_the_fork(bodies[2]):
        faults.append("Your call lacks both options or one recommendation")
    return faults


def asks_the_fork(forks):
    local = re.search(r"\blocal(?:ly)?\b|\bon this computer\b", forks, re.I)
    sync = re.search(r"\bsync", forks, re.I)
    decided = (
        r"\bno recommendation\b|\bexcluded?\b|\bout of scope\b|\brejected\b|\bI (?:cho|decid|pick)"
    )
    option = r"(?i:\blocal|\bon this computer\b|\bsync)|\b[AB]\b"
    picks = [line for line in forks.splitlines() if re.search(r"\brecommend", line, re.I)]
    recommends = any(re.search(option, line) for line in picks)
    affirmed = re.findall(r"(?<!not )(?<!n't )(?<!never )\brecommend", forks, re.I)
    recommends = recommends and len(affirmed) == 1
    recommends = recommends and not re.search(decided, forks, re.I)
    return bool(local and sync and recommends)


def environment():
    drop = ("GIT_CONFIG", "CLAUDE_CONFIG_DIR")
    return {key: value for key, value in os.environ.items() if not key.startswith(drop)}


def git(root, cwd, arguments):
    identity = ["-c", "user.name=Smoke", "-c", "user.email=smoke@example.invalid"]
    quiet = ["-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null"]
    argv = ["git", *identity, *quiet, *arguments]
    return run(Command(argv, cwd, environment(), root / ("git-" + arguments[0])))


def prepare(root):
    repo, workspace = root / "repo", root / "workspace"
    repo.mkdir()
    (repo / "README.md").write_text(
        "# Notes app\n\nA command-line notes app with in-memory notes.\n"
    )
    (repo / "notes.py").write_text("notes = []\n\ndef add(note):\n    notes.append(note)\n")
    git(root, repo, ["init", "-q", "-b", "main"])
    # A session may run the app to reproduce the bug, and bytecode is not an edit.
    (repo / ".gitignore").write_text("__pycache__/\n")
    git(root, repo, ["add", ".gitignore", "README.md", "notes.py"])
    git(root, repo, ["commit", "-qm", "Start the notes app"])
    git(root, repo, ["worktree", "add", "-q", "-b", "smoke-1", str(workspace)])
    argv = [str(ROOT / "bin/slopmeister"), "install", "--prepare", "slopmeister", str(workspace)]
    run(Command(argv, root, environment(), root / "prepare"))
    return workspace


def claude(root, workspace):
    argv = [
        CLAUDE,
        "-p",
        "--output-format",
        "json",
        "--strict-mcp-config",
        "--append-system-prompt-file",
        str(workspace / "CLAUDE.md"),
        "--setting-sources",
        "user,project",
        "--settings",
        str(workspace / ".claude/access-settings.json"),
        "--permission-mode",
        "auto",
        "--",
        "/sow " + TASK,
    ]
    out = run(Command(argv, workspace, environment(), root / "claude", SESSION_SECONDS))
    return json.loads(out)["result"]


def codex(root, workspace):
    last = root / "codex-last-message.txt"
    roots = ["-c", 'project_root_markers=["AGENTS.md"]', "-c", "project_doc_fallback_filenames=[]"]
    argv = [str(CODEX), "exec", *roots, "--sandbox", "workspace-write"]
    argv += ["-C", str(workspace), "--json"]
    argv += ["--output-last-message", str(last), "$sow " + TASK]
    run(Command(argv, workspace, environment(), root / "codex", SESSION_SECONDS))
    return last.read_text()
