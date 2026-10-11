"""Approval bootstrap uses only credential metadata and preserves protected HA storage."""

from pathlib import Path

import jinja2
import pytest
import yaml

HOST = Path(__file__).resolve().parents[1]


def test_ha_storage_and_its_parents_cannot_be_replaced_by_agent():
    role = HOST / "ansible/roles/home_assistant/tasks"
    deployment = yaml.safe_load((role / "deploy.yml").read_text())
    assert any(task.get("ansible.builtin.import_tasks") == "protect.yml" for task in deployment)
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


def bootstrap_accepts(secrets, package_exists=False):
    tasks = yaml.safe_load((HOST / "ansible/roles/home_assistant/tasks/deploy.yml").read_text())
    environment = jinja2.Environment(undefined=jinja2.StrictUndefined)
    context = {
        "home_assistant_approval_secrets": {"stat": secrets},
        "home_assistant_approval_package": {"stat": {"exists": package_exists}},
    }
    return all(
        environment.compile_expression(check)(**context)
        for task in tasks
        for check in task.get("ansible.builtin.assert", {}).get("that", [])
    )


@pytest.mark.parametrize(
    ("change", "accepted"),
    [
        ({}, True),
        ({"mode": "0644"}, False),
        ({"pw_name": "agent"}, False),
        ({"isreg": False}, False),
        ({"size": 0}, False),
    ],
)
def test_existing_route_requires_protected_settings(change, accepted):
    secrets = {"exists": True, "isreg": True, "pw_name": "root", "mode": "0600", "size": 1}
    assert bootstrap_accepts(secrets | change, package_exists=True) == accepted


def test_first_deploy_needs_no_settings_but_existing_route_cannot_lose_them():
    assert bootstrap_accepts({"exists": False})
    assert not bootstrap_accepts({"exists": False}, package_exists=True)


def test_settings_are_only_inspected_as_metadata_before_protection():
    tasks = yaml.safe_load((HOST / "ansible/roles/home_assistant/tasks/deploy.yml").read_text())
    assert tasks[0]["ansible.builtin.stat"]["path"].endswith("/secrets.yaml")
    assert all(
        tasks[0]["ansible.builtin.stat"][key] is False
        for key in ("follow", "get_checksum", "get_mime", "get_attributes")
    )
    assert not any(
        "ansible.builtin.slurp" in task or "ansible.builtin.fetch" in task for task in tasks
    )
    copies = [task for task in tasks if "ansible.builtin.copy" in task]
    package = next(
        task for task in copies if "packages/" in task["ansible.builtin.copy"].get("src", "")
    )
    assert package["when"] == "home_assistant_approval_secrets.stat.exists"
    assert all(
        "secrets.yaml" not in task["ansible.builtin.copy"]["src"]
        for task in copies
        if "src" in task["ansible.builtin.copy"]
    )


def test_package_uses_private_settings_and_no_sensor_or_decision_script():
    package = (HOST / "home-assistant/config/packages/secret_approval.yaml").read_text()
    assert all(
        f"!secret secret_approval_route_{key}" in package
        for key in ("ask_url", "answer_url", "credential", "operator", "devices")
    )
    assert "sensor." not in package and "script:" not in package
    assert not (HOST / "ansible/playbooks/secret-ask.yml").exists()
