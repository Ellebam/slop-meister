#!/usr/bin/env python3
"""Launch an opted-in weekly session with an operator-selected checkout and repository."""

from datetime import date
import json
import os
from pathlib import Path
import re
import stat
import sys

JOBS = {"weekly": "update-kickoff.md", "glean": "glean-kickoff.md"}


def configuration(config):
    try:
        descriptor = os.open(config, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return
    with os.fdopen(descriptor) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("the schedule file must be an owner-only regular file")
        if info.st_size > 8192:
            raise ValueError("schedule file exceeds 8 KiB")
        settings = json.loads(stream.read(8193))
    if not isinstance(settings, dict) or set(settings) != {"checkout", "repository", "plot"}:
        raise ValueError("set checkout, repository and plot in the schedule file")
    return settings


def run(job):
    settings = configuration(Path.home() / ".config/slopmeister" / (job + ".json"))
    if settings is None:
        return
    checkout, repo = (Path(settings[k]).expanduser() for k in ("checkout", "repository"))
    plot = settings["plot"]
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", plot):
        raise ValueError("invalid plot name")
    if not all(path.is_absolute() and path.is_dir() for path in (checkout, repo)):
        raise ValueError("checkout and repository must be absolute directories")
    launcher = checkout / "bin/slopmeister"
    args = [str(launcher), "plot-session", str(repo), plot, f"{plot}-{job}-{date.today():%Y%m%d}"]
    if job == "weekly":
        args.extend(["--weekly-update", "--tool", "claude"])
    with (checkout / "plots/home/launchd" / JOBS[job]).open("rb") as kickoff:
        os.dup2(kickoff.fileno(), 0)
        os.chdir(checkout)
        os.execv(launcher, args)


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in JOBS:
        sys.exit("usage: slopmeister-weekly glean|weekly")
    try:
        run(sys.argv[1])
    except (ValueError, OSError, TypeError) as error:
        sys.exit(f"slopmeister-weekly: {error}")
