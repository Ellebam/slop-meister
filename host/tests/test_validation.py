"""Validate retained host configuration before any start or forced restart."""

import os
from pathlib import Path
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
ROLE = ROOT / "host/ansible/roles/home_assistant"


def test_deployment_and_forced_handler_validate_before_service_commands():
    tasks = yaml.safe_load((ROLE / "tasks/deploy.yml").read_text())
    guard = next(
        i
        for i, task in enumerate(tasks)
        if task.get("ansible.builtin.import_tasks") == "validate.yml"
    )
    start = next(
        i
        for i, task in enumerate(tasks)
        if task.get("ansible.builtin.command") == "docker compose up -d"
    )
    assert guard < start
    handlers = yaml.safe_load((ROLE / "handlers/main.yml").read_text())
    assert handlers[0]["ansible.builtin.include_tasks"].endswith("/tasks/restart.yml")
    restart = yaml.safe_load((ROLE / "tasks/restart.yml").read_text())
    assert restart[0]["ansible.builtin.import_tasks"] == "validate.yml"
    assert restart[1]["ansible.builtin.command"] == "docker compose restart"


@pytest.fixture
def validation_scene(tmp_path):
    binary = tmp_path / "bin"
    binary.mkdir()
    docker = binary / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$*" >> "$CALLS"\n'
        'case "$*" in\n'
        '"compose config --images") printf "synthetic-image\\n";;\n'
        '"compose pull --quiet") exit 0;;\n'
        'run*) printf "%s\\n" "$CHECK_OUTPUT"; exit "$CHECK_STATUS";;\n'
        "*) exit 9;;\nesac\n"
    )
    docker.chmod(0o700)
    config = tmp_path / "config"
    config.mkdir()
    original = b"retained synthetic configuration\n"
    (config / "automations.yaml").write_bytes(original)
    log = tmp_path / "calls"
    return binary, config, original, log


@pytest.mark.parametrize(
    ("output", "status", "valid"),
    [
        ("Configuration valid", "0", True),
        ("ERROR:homeassistant.components.automation:Disabled automation", "0", False),
        ("CRITICAL:homeassistant.config:Invalid configuration", "0", False),
        ("Invalid YAML", "1", False),
        ("WARNING:homeassistant.config:Ignored package", "1", False),
        ("ERROR:homeassistant.util.file:Saving file failed", "0", True),
        (
            "ERROR:homeassistant.helpers.storage:Error writing config for core.restore_state",
            "0",
            True,
        ),
    ],
)
def test_validation_executes_read_only_check_and_suppresses_private_diagnostics(
    tmp_path, validation_scene, output, status, valid
):
    task = yaml.safe_load((ROLE / "tasks/validate.yml").read_text())[0]
    assert task["no_log"] is True and task["when"] == "not ansible_check_mode"
    binary, config, original, log = validation_scene
    result = subprocess.run(
        ["bash", "-c", task["ansible.builtin.shell"]],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{binary}:{os.environ['PATH']}",
            "CALLS": str(log),
            "CHECK_OUTPUT": output,
            "CHECK_STATUS": status,
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert (result.returncode == 0) is valid
    assert output not in result.stdout + result.stderr
    calls = log.read_text()
    assert f"{tmp_path}/config:/config:ro" in calls
    assert "--network none" in calls and "--fail-on-warnings" in calls
    assert all(flag in calls for flag in ("--cpus 1", "--memory 1g", "--pids-limit 128"))
    assert (config / "automations.yaml").read_bytes() == original
