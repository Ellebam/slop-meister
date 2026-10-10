"""Notification fan-out must not become a repeated broadcast after completion."""

from types import SimpleNamespace

import pytest

from slopmeister.secret_ask.broker import Broker
from slopmeister.secret_ask.home_assistant import Channel


@pytest.mark.parametrize("recovers", [True, False])
def test_failed_delivery_retries_without_repeating_success(tmp_path, monkeypatch, recovers):
    """Bug: one transient push failure suppresses that device for the whole request."""
    token = tmp_path / "token"
    token.write_text("synthetic-ha-token")
    token.chmod(0o600)
    broker = Broker(tmp_path, "operator")
    broker.records["request"] = {"id": "request", "state": "pending"}
    config = SimpleNamespace(ha_token=token, devices=("phone", "mac"))
    channel = Channel(config, broker, lambda approved: None)
    monkeypatch.setattr("slopmeister.secret_ask.home_assistant.notification", lambda row: {})
    attempts = {"phone": 0, "mac": 0}

    def send(device, body):
        attempts[device] += 1
        return device == "phone" or (recovers and attempts[device] > 1)

    channel._notify = send
    channel.http = lambda route, body: None
    for now in (10, 11, 14, 18, 22):
        monkeypatch.setattr(
            "slopmeister.secret_ask.home_assistant.time.monotonic", lambda now=now: now
        )
        channel._publish()
    channel.close()
    broker.close()
    assert attempts == {"phone": 1, "mac": 2 if recovers else 3}


def test_finished_retraction_is_not_repeated_after_reconnection(tmp_path):
    """Bug: reconnecting clears all historical tags again and exhausts push quotas."""
    token = tmp_path / "token"
    token.write_text("synthetic-ha-token")
    token.chmod(0o600)
    broker = Broker(tmp_path, "operator")
    broker.records["done"] = {"id": "done", "state": "denied", "retract": True}
    config = SimpleNamespace(ha_token=token, devices=("mobile_app_phone",), url="http://127.0.0.1")
    channel = Channel(config, broker, lambda approved: None)
    sent = []
    channel.http = lambda route, body: sent.append(body)
    channel._publish()
    channel.close()
    channel = Channel(config, broker, lambda approved: None)
    channel.http = lambda route, body: sent.append(body)
    channel._publish()
    assert len([b for b in sent if b.get("message") == "clear_notification"]) == 1
    channel.close()
    broker.close()


def test_one_failed_device_does_not_skip_the_others(tmp_path):
    """Bug: one unavailable Mac notification service suppresses phone delivery."""
    token = tmp_path / "token"
    token.write_text("synthetic-ha-token")
    token.chmod(0o600)
    broker = Broker(tmp_path, "operator")
    config = SimpleNamespace(ha_token=token, devices=("mobile_app_mac", "mobile_app_phone"))
    channel = Channel(config, broker, lambda approved: None)
    called = []

    def send(route, body):
        called.append(route)
        if route.endswith("mac"):
            raise OSError("synthetic failure")

    channel.http = send
    assert channel.fanout({"message": "proof"}) is False
    assert len(called) == 2
    channel.close()
    broker.close()


def test_decision_view_is_published_before_notification(tmp_path):
    """Bug: a fast body tap opens an unavailable request while another push blocks."""
    token = tmp_path / "token"
    token.write_text("synthetic-ha-token")
    token.chmod(0o600)
    broker = Broker(tmp_path, "operator")
    broker.records["request"] = {
        "id": "request",
        "state": "pending",
        "argv": ["/usr/bin/true"],
        "env": {"DEMO": "op://Example/Demo/password"},
        "reason": "proof",
        "session": "test",
        "host": "test-host",
        "cwd": "/",
        "approve": "private-approve",
        "deny": "private-deny",
    }
    config = SimpleNamespace(ha_token=token, devices=("mobile_app_phone", "mobile_app_mac"))
    channel = Channel(config, broker, lambda approved: None)
    routes = []
    channel.http = lambda route, body: routes.append(route)
    channel._publish()
    channel.close()
    broker.close()
    assert routes[0] == "/api/states/sensor.secret_ask"
    assert len([route for route in routes if "/notify/" in route]) == 2
