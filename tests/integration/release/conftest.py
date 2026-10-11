"""Drive the release entry point with a local repository and a stand-in GitHub CLI."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.support.repos import GIT_ENV, git, scratch_repo

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / ".github/scripts/release.py"


@dataclass
class ReleaseRepository:
    path: Path
    env: dict[str, str]

    def state(self, **updates: object) -> dict:
        file = self.path / "remote.json"
        value = json.loads(file.read_text())
        value.update(updates)
        file.write_text(json.dumps(value))
        return value

    def run(self, **updates: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT)],
            cwd=self.path,
            env=self.env | updates,
            capture_output=True,
            text=True,
            check=False,
        )

    def writes(self) -> list[dict]:
        return [call for call in self.state()["calls"] if call["method"] != "GET"]


@pytest.fixture
def release_repo(tmp_path: Path) -> ReleaseRepository:
    scratch_repo(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.1.0"\n')
    git(tmp_path, "add", "pyproject.toml")
    git(tmp_path, "commit", "-m", "Set version")
    sha = git(tmp_path, "rev-parse", "HEAD").strip()
    stub = tmp_path / "gh"
    stub.write_text(f"#!{sys.executable}\n" + Path(__file__).with_name("gh_stub.py").read_text())
    stub.chmod(0o700)
    state = tmp_path / "remote.json"
    state.write_text(json.dumps({"tag": None, "release": None, "calls": []}))
    return ReleaseRepository(
        tmp_path,
        os.environ
        | GIT_ENV
        | {
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "RELEASE_STATE": str(state),
            "GITHUB_EVENT_NAME": "push",
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_SHA": sha,
            "GITHUB_REPOSITORY": "example/project",
            "GH_TOKEN": "synthetic-token-never-print",
        },
    )
