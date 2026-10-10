"""Provisioning keeps approval credentials outside the requesting account's control."""

import configparser
from pathlib import Path

import jinja2
import pytest
import yaml

HOST = Path(__file__).resolve().parents[1]
ROLE = HOST / "ansible/roles/secret_ask"


def test_broker_unit_separates_identity_and_contains_children():
    template = (ROLE / "templates/slopmeister-secret-ask.service.j2").read_text()
    text = jinja2.Template(template).render(
        secret_ask_agent_user="agent", secret_ask_root="/opt/broker"
    )
    unit = configparser.ConfigParser(interpolation=None)
    unit.read_string(text)
    service = unit["Service"]
    assert service["User"] == service["Group"] == "slopmeister-secret-ask"
    assert service["SupplementaryGroups"] == "agent"
    assert service["KillMode"] == "control-group" and service["UMask"] == "0077"
    assert service["ProtectSystem"] == "strict" and service["ProtectHome"] == "true"
    assert service["NoNewPrivileges"] == "true" and "EnvironmentFile" not in service
    assert " -I /opt/broker/current/bin/slopmeister secret-ask serve" in service["ExecStart"]


def test_credentials_are_only_inspected_as_metadata():
    tasks = yaml.safe_load((ROLE / "tasks/main.yml").read_text())
    inspected = next(task for task in tasks if "ansible.builtin.stat" in task)
    assert inspected["loop"] == ["onepassword-token", "home-assistant-token"]
    assert all(
        inspected["ansible.builtin.stat"][key] is False
        for key in ("follow", "get_checksum", "get_mime", "get_attributes")
    )
    assert not any(
        "ansible.builtin.slurp" in task or "ansible.builtin.fetch" in task for task in tasks
    )
    token_tasks = [task for task in tasks if any(name in str(task) for name in inspected["loop"])]
    assert token_tasks == [inspected]


@pytest.mark.parametrize(
    "change,ready",
    [
        ({}, True),
        ({"mode": "0644"}, False),
        ({"pw_name": "agent"}, False),
        ({"isreg": False}, False),
        ({"size": 0}, False),
        ({"exists": False}, False),
    ],
)
def test_broker_requires_two_protected_credentials(change, ready):
    tasks = yaml.safe_load((ROLE / "tasks/main.yml").read_text())
    fact = next(
        task["ansible.builtin.set_fact"]["secret_ask_credentials_ready"]
        for task in tasks
        if "secret_ask_credentials_ready" in task.get("ansible.builtin.set_fact", {})
    )
    protected = {
        "exists": True,
        "isreg": True,
        "pw_name": "slopmeister-secret-ask",
        "mode": "0600",
        "size": 1,
    }
    values = {"results": [{"stat": protected}, {"stat": protected | change}]}
    result = jinja2.Template(fact).render(secret_ask_credentials=values)
    assert (result == "True") == ready
    service = next(
        task["ansible.builtin.systemd_service"]
        for task in tasks
        if "ansible.builtin.systemd_service" in task
    )
    assert service["enabled"] == "{{ secret_ask_credentials_ready }}"
    assert "else 'stopped'" in service["state"]


def test_runtime_and_configuration_have_root_owned_parents():
    tasks = yaml.safe_load((ROLE / "tasks/main.yml").read_text())
    directories = [
        task["ansible.builtin.file"]
        for task in tasks
        if task.get("ansible.builtin.file", {}).get("state") == "directory"
    ]
    assert directories
    assert all(item["owner"] == item["group"] == "root" for item in directories)
    archive = next(
        task["ansible.builtin.unarchive"] for task in tasks if "ansible.builtin.unarchive" in task
    )
    assert archive["owner"] == archive["group"] == "root" and archive["mode"] == "go-w"
    install = next(task["ansible.builtin.pip"] for task in tasks if "ansible.builtin.pip" in task)
    assert install["extra_args"] == "--require-hashes --no-deps"
    assert "{{ secret_ask_python }}" in install["virtualenv_command"]


def test_ha_storage_and_its_parents_cannot_be_replaced_by_agent():
    role = HOST / "ansible/roles/home_assistant/tasks"
    deployment = yaml.safe_load((role / "deploy.yml").read_text())
    assert deployment[0]["ansible.builtin.import_tasks"] == "protect.yml"
    protection = yaml.safe_load((role / "protect.yml").read_text())
    files = [task["ansible.builtin.file"] for task in protection]
    assert all(entry["owner"] == entry["group"] == "root" for entry in files)
    storage = next(entry for entry in files if entry["path"].endswith("/.storage"))
    assert storage["mode"] == "0700"
    recursive = next(entry for entry in files if entry.get("recurse"))
    assert recursive["follow"] is False and recursive["mode"] == "go-w"
    seed = next(
        task["ansible.builtin.copy"]
        for task in deployment
        if task.get("ansible.builtin.copy", {}).get("force") is False
    )
    assert seed["owner"] == seed["group"] == "root"


def test_approval_actions_are_not_recorded():
    package = yaml.safe_load((HOST / "home-assistant/config/packages/secret_ask.yaml").read_text())
    assert "sensor.secret_ask" in package["recorder"]["exclude"]["entities"]
    assert package["script"]["secret_ask_decide"]["sequence"] == [
        {"event": "secret_ask_decision", "event_data": {"action": "{{ action }}"}}
    ]
