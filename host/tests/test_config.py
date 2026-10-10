"""The approval frontend must not expose raw HTTP outside host loopback."""

from pathlib import Path

import yaml

HOST = Path(__file__).resolve().parents[1]


def test_home_assistant_publishes_only_loopback_http():
    service = yaml.safe_load((HOST / "home-assistant/compose.yaml").read_text())["services"][
        "homeassistant"
    ]
    assert service.get("network_mode") != "host", "raw HA must stay off the host network"
    assert service["ports"] == ["127.0.0.1:8123:8123"]
    assert service["volumes"] == ["./config:/config"]
    assert not service.get("privileged", False)
    assert "@sha256:" in service["image"]
