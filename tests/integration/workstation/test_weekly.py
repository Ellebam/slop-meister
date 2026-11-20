"""The optional timers start the configured session and leave an unconfigured host idle."""

import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]
ENTRY = ROOT / "plots/home/launchd/weekly.py"


@pytest.mark.parametrize(
    "job,kickoff", [("glean", "glean-kickoff.md"), ("weekly", "update-kickoff.md")]
)
def test_weekly_launch_is_opt_in_and_uses_its_own_kickoff(tmp_path, job, kickoff):
    home, checkout, repo = (tmp_path / name for name in ("home", "tool checkout", "demo shop"))
    repo.mkdir()
    dest = checkout / "bin/slopmeister"
    dest.parent.mkdir(parents=True)
    dest.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\ncat\n')
    dest.chmod(0o700)
    note = checkout / "plots/home/launchd" / kickoff
    note.parent.mkdir(parents=True)
    note.write_bytes((ROOT / "plots/home/launchd" / kickoff).read_bytes())
    config = home / ".config/slopmeister" / f"{job}.json"
    config.parent.mkdir(parents=True)

    def launch():
        return subprocess.run(
            [ENTRY, job],
            env={**os.environ, "HOME": str(home)},
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    empty = launch()
    assert (empty.returncode, empty.stdout) == (0, "")
    config.write_text(
        json.dumps({"checkout": str(checkout), "plot": "shop", "repository": str(repo)})
    )
    config.chmod(0o600)
    done = launch()
    assert done.returncode == 0 and done.stdout.startswith(
        f"plot-session\n{repo}\nshop\nshop-{job}-"
    )
    assert done.stdout.endswith(note.read_text())
    assert ("--weekly-update\n--tool\nclaude\n" in done.stdout) == (job == "weekly")
    config.chmod(0o644)
    refused = launch()
    assert refused.returncode != 0 and not refused.stdout and "owner-only" in refused.stderr
