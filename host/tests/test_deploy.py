"""Only reviewed deployment inputs may reach the privileged playbook runner."""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from tests.support.repos import git, scratch_repo

ROOT = Path(__file__).resolve().parents[2]
PANEL = "host/home-assistant/config/www/secret-approval.js"
ROLE = "host/ansible/roles/home_assistant/tasks/deploy.yml"
PAYLOADS = (
    PANEL,
    ROLE,
    "pyproject.toml",
    "uv.lock",
    "bin/slopmeister",
    "slopmeister/__init__.py",
    "slopmeister/session/__init__.py",
    "slopmeister/session/bloom.py",
    "slopmeister/session/bloom_storage.py",
    "slopmeister/session/git_environment.py",
    "slopmeister/session/remote_ssh.py",
    "slopmeister/session/launch_identity.py",
)
UV = """#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
with open(os.environ["DEPLOY_LOG"], "a") as log:
    log.write(json.dumps(args) + "\\n")
if args[0] == "export":
    pathlib.Path(args[args.index("--output-file") + 1]).write_text("# synthetic requirements\\n")
else:
    assert "ansible-playbook" in args
    print("ANSIBLE_STANDIN_REACHED")
"""


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    # The outer host:test task exports empty defaults that would override child CLI inputs.
    for name in ("HOST_INVENTORY", "HOST_SETTINGS", "HOST_REVISION"):
        monkeypatch.delenv(name, raising=False)
    repo = scratch_repo(tmp_path / "repo")
    for name in PAYLOADS:
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("reviewed fixture\n")
    (repo / "taskfiles").mkdir()
    shutil.copy2(ROOT / "taskfiles/host.yml", repo / "taskfiles/host.yml")
    shutil.copy2(ROOT / "host/.gitignore", repo / "host/.gitignore")
    (repo / "Taskfile.yml").write_text("version: '3'\nincludes:\n  host: taskfiles/host.yml\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "Review deployment inputs")
    binary = tmp_path / "bin"
    binary.mkdir()
    (binary / "uv").write_text(UV)
    (binary / "uv").chmod(0o755)
    monkeypatch.setenv("PATH", f"{binary}:{os.environ['PATH']}")
    log = tmp_path / "runner.jsonl"
    monkeypatch.setenv("DEPLOY_LOG", str(log))
    return repo, git(repo, "rev-parse", "HEAD").strip(), log


def deploy(subject, target):
    repo, revision, _ = subject
    return subprocess.run(
        [
            "task",
            f"host:{target}:deploy",
            "HOST_INVENTORY=/synthetic/inventory.yml",
            "HOST_SETTINGS=/synthetic/settings.yml",
            f"HOST_REVISION={revision}",
        ],
        cwd=repo,
        env={**os.environ, "NO_COLOR": "1"},
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )


@pytest.mark.parametrize("target", ["ha", "grove"])
def test_reviewed_deployment_reaches_only_the_stand_in(deployment, target):
    result = deploy(deployment, target)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ANSIBLE_STANDIN_REACHED" in result.stdout
    calls = [json.loads(line) for line in deployment[2].read_text().splitlines()]
    assert sum("ansible-playbook" in call for call in calls) == 1


@pytest.mark.parametrize("target", ["ha", "grove"])
@pytest.mark.parametrize(
    ("path", "change"),
    [
        pytest.param(PANEL, "worktree", id="panel"),
        pytest.param(ROLE, "worktree", id="role"),
        pytest.param(PANEL, "staged", id="staged"),
        pytest.param(PANEL, "index-only", id="index-only"),
        pytest.param(ROLE, "deleted", id="deleted"),
        pytest.param(
            "host/ansible/roles/home_assistant/library/unreviewed.py", "untracked", id="plugin"
        ),
        pytest.param(
            "host/ansible/roles/home_assistant/templates/unreviewed.j2", "untracked", id="template"
        ),
        pytest.param("Taskfile.yml", "worktree", id="root-taskfile"),
        pytest.param("pyproject.toml", "worktree", id="project"),
        pytest.param("uv.lock", "worktree", id="lock"),
        pytest.param("uv.toml", "untracked", id="uv-config"),
        pytest.param(".python-version", "untracked", id="python-version"),
    ],
)
def test_unreviewed_inputs_refuse_before_any_runner(deployment, target, path, change):
    file = deployment[0] / path
    original = file.read_text() if file.exists() else ""
    if change == "deleted":
        file.unlink()
    else:
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(original + "# unreviewed\n")
    if change in {"staged", "index-only"}:
        git(deployment[0], "add", path)
    if change == "index-only":
        file.write_text(original)
    result = deploy(deployment, target)
    assert result.returncode != 0
    assert any(
        line.startswith("Host deployment inputs must match HOST_REVISION")
        for line in (result.stdout + result.stderr).splitlines()
    )
    assert not deployment[2].exists()


@pytest.mark.parametrize("target", ["ha", "grove"])
def test_ignored_scratch_and_unrelated_changes_do_not_block(deployment, target):
    repo = deployment[0]
    scratch = repo / "host/.scratch/private.txt"
    scratch.parent.mkdir(parents=True)
    scratch.write_text("synthetic private scratch\n")
    (repo / "README.md").write_text("unrelated local edit\n")
    result = deploy(deployment, target)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ANSIBLE_STANDIN_REACHED" in result.stdout
    assert scratch.read_text() == "synthetic private scratch\n"
