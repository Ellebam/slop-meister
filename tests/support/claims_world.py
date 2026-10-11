"""Disposable native and GitHub doubles for claim launcher tests."""

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import uuid

from tests.support import fakes, repos, trees

SLOPMEISTER = Path(__file__).resolve().parents[2]


class ClaimWorld:
    def __init__(self, root: Path):
        self.root = root
        self.bin = root / "bin"
        self.children = []
        self._make_tree()
        self.codex_home = Path(os.path.relpath(root / "codex", SLOPMEISTER))
        self.env = self._environment()
        self.repo = repos.scratch_repo(root / "repo")
        repos.git(self.repo, "remote", "add", "origin", "git@github.com:owner/project.git")

    def _make_tree(self):
        paths = ("bin", "vault", "claude", "codex", "state", "runtime", "home/.local/bin")
        for relative in paths:
            (self.root / relative).mkdir(parents=True, exist_ok=True)
        driver = SLOPMEISTER / "tests/support/claims_driver.py"
        for name in ("gh", "ps", "pgrep", "lsof", "orca", "claude", "sleep"):
            script = f'CLAIMS_FAKE_NAME="{name}" exec "{sys.executable}" "{driver}" "$@"'
            fakes.fake_binary(self.bin, name, script)
        fakes.fake_binary(self.root / "home/.local/bin", "codex", "exit 98")
        trees.write(self.root, "remote.json", json.dumps(self._issue(7)))
        trees.write(self.root, "case.json", "{}")
        trees.write(self.root, "plots/slopmeister/plot.toml", self._plot())

    def _environment(self):
        env = dict(os.environ)
        for key in (
            "GIT_DIR",
            "GIT_WORK_TREE",
            "GIT_COMMON_DIR",
            "GIT_INDEX_FILE",
            "GIT_CONFIG_COUNT",
        ):
            env.pop(key, None)
        env.update(repos.GIT_ENV)
        env.update(self._paths())
        return env

    def _paths(self):
        return {
            "HOME": str(self.root / "home"),
            "CLAIMS_FIXTURE": str(self.root),
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "PLOT_DECLARATIONS": str(self.root / "plots"),
            "SLOPMEISTER_VAULT": str(self.root / "vault"),
            "CLAUDE_CONFIG_DIR": str(self.root / "claude"),
            # Absolute for the product, the short relative path above only binds the socket.
            "CODEX_HOME": str(self.root / "codex"),
            "XDG_STATE_HOME": str(self.root / "runtime"),
            "PLOT_SESSION_STATE_DIR": str(self.root / "state"),
            "PLOT_SESSION_NO_LAUNCH": "0",
            "PLOT_SESSION_ORCA": str(self.root / "bin/orca"),
        }

    @staticmethod
    def _issue(number):
        return {"number": number, "state": "open", "title": "Fixture work", "labels": []}

    @staticmethod
    def _plot():
        return (
            '[plot]\nbase="code"\n[target]\ntasks="github"\n'
            '[target.repository]\ncommit="allow"\nshipping="allow"\n[slots]\nnone=true\n'
        )

    def worker(self, name, tool):
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(300)"], cwd=self.root
        )
        self.children.append(process)
        threading.Thread(target=process.wait, daemon=True).start()
        item = {
            "name": name,
            "tool": tool,
            "pid": process.pid,
            "workspace": str(self.repo / ".worktrees" / name),
            "session": str(uuid.uuid4()),
        }
        trees.write(self.root, f"worker-{process.pid}.json", json.dumps(item))
        return process, Path(item["workspace"])

    def launch(self, name, tool, *args):
        command = [str(SLOPMEISTER / "bin/slopmeister"), "plot-session", str(self.repo)]
        command += ["slopmeister", name, "--tool", tool, *args]
        return subprocess.run(
            command,
            input="Mode: spine\nFixture work.\n",
            capture_output=True,
            text=True,
            env=self.env,
            timeout=90,
        )

    def cli(self, action, *args):
        command = [str(SLOPMEISTER / "bin/slopmeister"), "claims", action, *map(str, args)]
        return subprocess.run(command, capture_output=True, text=True, env=self.env, timeout=30)

    def values(self):
        return self.root, self.repo, self.env, self.worker, self.launch, self.cli

    def close(self):
        for child in self.children:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=5)
