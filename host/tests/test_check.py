"""The checker rejects HA's false success and removes only its own container."""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
CID = "a" * 64
DOCKER = """#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
with open(os.environ["FAKE_DOCKER_LOG"], "a") as log:
    log.write(json.dumps(args) + "\\n")
if args[0] == "create":
    pathlib.Path(args[args.index("--cidfile") + 1]).write_text("a" * 64)
    sys.exit(int(os.environ.get("FAKE_CREATE_EXIT", "0")))
elif args[0] == "start":
    sys.stdin.buffer.read()
    print(os.environ["FAKE_HA_OUTPUT"])
    sys.exit(int(os.environ["FAKE_HA_EXIT"]))
"""


@pytest.fixture
def checker(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "host/home-assistant", tmp_path / "host/home-assistant")
    shutil.copy2(ROOT / "taskfiles/host.yml", tmp_path / "Taskfile.yml")
    binary = tmp_path / "bin"
    binary.mkdir()
    docker = binary / "docker"
    docker.write_text(DOCKER)
    docker.chmod(0o755)
    monkeypatch.setenv("PATH", f"{binary}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_DOCKER_LOG", str(tmp_path / "docker.jsonl"))
    return tmp_path


@pytest.mark.parametrize(
    ("output", "exit_code", "success"),
    [
        ("Configuration valid", "0", True),
        ("Incorrect config: package", "0", False),
        (
            "ERROR:homeassistant.components.automation:Automation could not be validated "
            "and has been disabled",
            "0",
            False,
        ),
        ("WARNING:homeassistant.config:Deprecated configuration", "0", True),
        ("Checker failed", "2", False),
    ],
)
def test_checker_refuses_errors_and_keeps_container_contained(
    checker, monkeypatch, output, exit_code, success
):
    monkeypatch.setenv("FAKE_HA_OUTPUT", output)
    monkeypatch.setenv("FAKE_HA_EXIT", exit_code)
    result = subprocess.run(
        ["task", "ha:check"], cwd=checker, capture_output=True, text=True, check=False, timeout=15
    )
    assert (result.returncode == 0) == success, result.stdout + result.stderr
    assert output in result.stdout
    commands = [json.loads(line) for line in (checker / "docker.jsonl").read_text().splitlines()]
    create = commands[0]
    assert create[:1] == ["create"] and create[create.index("--network") + 1] == "none"
    assert all(flag in create for flag in ("--cpus", "--memory", "--pids-limit"))
    assert not any(flag in create for flag in ("-p", "--publish", "-v", "--volume", "--mount"))
    assert commands[1] == ["start", "-ai", CID]
    assert commands[2] == ["rm", "-f", CID]
    assert CID in result.stdout
    assert not list((checker / "host/.scratch").iterdir())


def test_failed_create_still_removes_its_recorded_container(checker, monkeypatch):
    monkeypatch.setenv("FAKE_CREATE_EXIT", "2")
    result = subprocess.run(
        ["task", "ha:check"], cwd=checker, capture_output=True, text=True, check=False, timeout=15
    )
    commands = [json.loads(line) for line in (checker / "docker.jsonl").read_text().splitlines()]
    assert result.returncode != 0
    assert [command[0] for command in commands] == ["create", "rm"]
    assert commands[-1] == ["rm", "-f", CID]
    assert not list((checker / "host/.scratch").iterdir())
