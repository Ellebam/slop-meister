"""The page reader is confined while the publisher owns only its content."""

import base64
import configparser
import json
from pathlib import Path

import jinja2
import yaml

HOST = Path(__file__).resolve().parents[1]
ROLE = HOST / "ansible/roles/grove"


def unit(name):
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(ROLE / "templates"))
    values = {
        "grove_jail": "/jail",
        "grove_pages": "/pages",
        "grove_backend_port": 8769,
        "grove_root": "/opt/grove",
        "grove_archive_sha256": "a" * 64,
        "grove_publisher": "publisher",
    }
    env.globals["lookup"] = lambda kind, path: env.get_template(path).render(**values)
    env.filters["b64encode"] = lambda text: base64.b64encode(text.encode()).decode()
    result = configparser.ConfigParser(interpolation=None)
    result.read_string(env.get_template(name + ".j2").render(**values))
    return result["Service"]


def test_reader_has_a_read_only_jail_and_no_host_configuration_path():
    service = unit("grove.service")
    assert service["User"] == service["Group"] == "grove"
    assert service["RootDirectory"] == "/jail" and service["MountAPIVFS"] == "no"
    assert "-+/proc" in service["InaccessiblePaths"].split()
    assert service["BindReadOnlyPaths"] == "/usr/local/libexec/grove/caddy:/.caddy /pages:/pages"
    assert service["CapabilityBoundingSet"] == ""
    assert service["NoNewPrivileges"] == "true" and service["ProtectSystem"] == "strict"
    assert service["StandardInput"] == "data"
    config = base64.b64decode(service["StandardInputData"]).decode()
    assert "http://:8769" in config and "bind 127.0.0.1" in config
    assert "root * /pages" in config
    assert "method GET HEAD" in config and "respond 404" in config
    assert "sandbox allow-scripts" in config and "default-src 'none'" in config


def test_cleanup_keeps_the_publisher_identity_and_one_writable_directory():
    service = unit("grove-cleanup.service")
    assert service["User"] == "publisher"
    assert service["ExecStart"] == "/usr/local/bin/grove cleanup"
    assert service["ReadWritePaths"] == "/pages"
    assert service["ProtectSystem"] == "strict" and service["ProtectHome"] == "true"


def test_archive_and_caddy_are_verified_before_installation():
    tasks = yaml.safe_load((ROLE / "tasks/main.yml").read_text())
    assertions = [
        task["ansible.builtin.assert"]["that"] for task in tasks if "ansible.builtin.assert" in task
    ]
    assert any(
        "grove_runtime_archive.stat.checksum == grove_archive_sha256" in a for a in assertions
    )
    download = next(
        task["ansible.builtin.get_url"] for task in tasks if "ansible.builtin.get_url" in task
    )
    assert download["checksum"] == "{{ grove_caddy_checksum }}"
    modes = [task["ansible.builtin.file"] for task in tasks if "ansible.builtin.file" in task]
    executable = next(task for task in modes if task["path"] == "/usr/local/libexec/grove/caddy")
    assert executable["mode"] == "0111" and executable["owner"] == executable["group"] == "root"
    pages = next(task for task in modes if task["path"] == "{{ grove_pages }}")
    assert pages["owner"] == "{{ grove_publisher }}" and pages["mode"] == "2750"


def test_tailnet_policy_admits_only_selected_sources_and_refuses_backends():
    policy = json.loads((HOST / "tailnet-policy.example.json").read_text())
    assert policy["acls"] == [
        {
            "action": "accept",
            "src": ["operator@example.invalid", "tag:workstation"],
            "dst": ["tag:agent-host:443,8443"],
        }
    ]
    refused = next(case for case in policy["tests"] if case["src"] == "other@example.invalid")
    assert set(refused["deny"]) == {f"tag:agent-host:{port}" for port in (443, 8443, 8123, 8769)}
    for case in policy["tests"]:
        assert {"tag:agent-host:8123", "tag:agent-host:8769"} <= set(case["deny"])
