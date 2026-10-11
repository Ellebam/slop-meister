"""The kickoff reaches its file byte for byte, and a Codex launch registers its follow-up."""

import hashlib
import json
from pathlib import Path

import pytest

from tests.integration.launch.helpers import declare, executable, launch, machine, reported, target

AWKWARD = 'Probe: "quoted" $HOME ~user `tick` and a $(sub). Reply ok and stop.'


def _kickoff(result) -> bytes:
    return Path(reported(result.stdout, "kickoff file")).read_bytes()


@pytest.mark.parametrize(
    "text", [AWKWARD, "---\ntype: ticket\n---\nBody after frontmatter."], ids=["shell", "dashes"]
)
def test_kickoff_bytes_survive(tmp_path, text):
    """Bug: a shell layer expands a quote, dollar, tilde, backtick or substitution, or a leading
    frontmatter fence is lost, and the session works from a corrupted brief."""
    world = machine(tmp_path)
    repo = target(tmp_path / "repo")
    result = launch(world, str(repo), "example-client", "example-client-wt1", kickoff=text)
    assert _kickoff(result) == text.encode() + b"\n"


@pytest.mark.parametrize(
    ("fetcher", "tasks", "flag"),
    [
        ("gh", "github", ["--issue", "7"]),
        ("file", "vault", ["--note", "a/note.md"]),
    ],
    ids=["issue", "note"],
)
def test_fetched_body_is_the_kickoff(tmp_path, fetcher, tasks, flag):
    """Bug: a fetch flag never calls its fetcher, asks for the wrong item, or mangles the body."""
    world = machine(tmp_path)
    repo = target(tmp_path / "repo")
    body = f'{fetcher} body with "quotes", $HOME, ~user, `ticks` and $(sub).\nSecond line.'
    if fetcher == "gh":
        executable(
            tmp_path / "bin/gh",
            f'#!/bin/sh\ncase " $* " in *" 7 "*) cat <<\'EOF\'\n{body}\nEOF\n;; esac\n',
        )
    else:
        note = world.vault / "a/note.md"
        note.parent.mkdir()
        note.write_text(body + "\n")
    plots = str(declare(tmp_path / "plots", "example-client", "inject", commit="deny", tasks=tasks))
    result = launch(
        world,
        str(repo),
        "example-client",
        "example-client-wt1",
        *flag,
        kickoff="",
        PLOT_DECLARATIONS=plots,
    )
    assert _kickoff(result) == body.encode() + b"\n"


def test_codex_launch_prepares_protected_task_identity(tmp_path):
    """Bug: a reused workspace keeps a confirmed identity for its predecessor."""
    world = machine(tmp_path)
    repo = target(tmp_path / "repo")
    launch(world, str(repo), "example-client", "example-client-wt1", "--tool", "codex")
    worktree = (repo / ".worktrees/example-client-wt1").resolve()
    digest = hashlib.sha256(str(worktree).encode()).hexdigest()
    identity = Path(world.env["HOME"]) / ".local/state/slopmeister/launch" / f"{digest}.json"
    assert json.loads(identity.read_text()) == {
        "version": 1,
        "state": "prepared",
        "workspace": str(worktree),
        "task": "example-client-wt1",
        "tool": "codex",
    }
    assert identity.stat().st_mode & 0o777 == 0o600
