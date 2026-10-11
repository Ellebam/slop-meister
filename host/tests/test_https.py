"""Evaluate route assertions with synthetic Serve state, without running a playbook."""

from pathlib import Path
import re

import jinja2
import pytest
import yaml

HOST = Path(__file__).resolve().parents[1]


def accepted(role, state):
    tasks = yaml.safe_load((HOST / f"ansible/roles/{role}/tasks/https.yml").read_text())
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.tests["search"] = lambda value, pattern: bool(re.search(pattern, value))
    values = {f"{role}_serve": state, "grove_https_port": 8443, "grove_backend_port": 8769}
    results = []
    for task in tasks:
        if "ansible.builtin.assert" not in task:
            continue
        rows = state.get("Web", {}).items() if "loop" in task else [("", {})]
        for key, item in rows:
            context = values | {"item": {"key": key, "value": item}}
            condition = task.get("when", "true")
            if env.compile_expression(condition)(**context):
                checks = task["ansible.builtin.assert"]["that"]
                results.extend(env.compile_expression(check)(**context) for check in checks)
    return all(results)


@pytest.mark.parametrize(
    "role,port,backend", [("home_assistant", 443, 8123), ("grove", 8443, 8769)]
)
def test_existing_routes_survive_and_conflicts_refuse(role, port, backend):
    handler = {"/": {"Proxy": f"http://127.0.0.1:{backend}"}}
    own = {
        "TCP": {str(port): {"HTTPS": True}},
        "Web": {f"agent.example.invalid:{port}": {"Handlers": handler}},
    }
    assert accepted(role, {})
    assert accepted(role, own)
    assert accepted(
        role, {"Web": {"other.example.invalid:9443": {"Handlers": {"/": {"Text": "other"}}}}}
    )
    assert not accepted(role, own | {"AllowFunnel": {"other.example.invalid:9443": True}})
    assert not accepted(role, {"TCP": {str(port): {"TCPForward": "localhost:9999"}}})
    conflict = {"Web": {f"agent.example.invalid:{port}": {"Handlers": {"/": {"Text": "other"}}}}}
    assert not accepted(role, conflict)
