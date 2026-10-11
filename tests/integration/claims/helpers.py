"""Assertions shared by native claim tests."""

import json
from pathlib import Path
import subprocess


def writes(root):
    path = root / "github.log"
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text().splitlines()
        if json.loads(line)["method"] != "GET"
    ]


def receipt(workspace):
    command = ["git", "-C", str(workspace), "rev-parse", "--absolute-git-dir"]
    git_dir = subprocess.check_output(command, text=True).strip()
    return Path(git_dir) / "slopmeister-config/issue.json"
