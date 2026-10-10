"""A public request ID must never grant permission to collect its values."""

import os

import pytest

from slopmeister.secret_ask.broker import Broker

REQUEST = {
    "env": {"DEMO": "op://Example/Demo/password"},
    "argv": ["/usr/bin/true"],
    "cwd": "/",
    "reason": "proof",
    "session": "test-session",
    "host": "test-host",
}


@pytest.fixture
def broker(tmp_path):
    return Broker(tmp_path, "operator")


def submit(broker, **changes):
    return broker.submit(os.getuid(), {**REQUEST, **changes})


def event(action, user="operator"):
    return {"context": {"user_id": user}, "data": {"action": action}}


def test_public_id_and_other_users_cannot_approve(broker, tmp_path):
    """Bug: the agent can approve with its receipt, a household user's event, or a token read
    from the request history on disk."""
    receipt = submit(broker)
    assert not broker.decide(event(receipt["id"]))
    action = broker.pending()[0]["approve"]
    assert action not in str(receipt)
    assert action not in (tmp_path / "requests.json").read_text()
    assert not broker.decide(event(action, "family"))
    assert broker.collect(receipt["id"], os.getuid())["state"] == "pending"
    broker.close()


def test_first_decision_wins_and_later_press_is_logged(broker, tmp_path):
    """Bug: a second device can override denial or approve a request twice."""
    receipt = submit(broker)
    row = broker.pending()[0]
    assert broker.decide(event(row["deny"])) is None
    assert not broker.decide(event(row["approve"]))
    assert broker.collect(receipt["id"], os.getuid())["state"] == "denied"
    assert "decision_refused" in (tmp_path / "audit.log").read_text()
    assert row["approve"] not in (tmp_path / "audit.log").read_text()
    broker.close()


def test_expired_and_restarted_requests_never_deliver(broker, tmp_path):
    """Bug: late approval or a service restart delivers an interrupted request."""
    receipt = submit(broker)
    row = broker.pending()[0]
    broker.expire(row["expires"] + 1)
    assert not broker.decide(event(row["approve"]))
    assert broker.collect(receipt["id"], os.getuid())["state"] == "timed out"
    broker.close()
    resumed = Broker(tmp_path, "operator")
    assert resumed.pending() == []
    assert resumed.collect(receipt["id"], os.getuid())["state"] == "timed out"
    resumed.close()


def test_values_are_delivered_once_and_only_to_the_requester(broker, tmp_path):
    """Bug: a second collection or another account receives the values."""
    receipt = submit(broker)
    row = broker.pending()[0]
    approved = broker.decide(event(row["approve"]))
    assert approved == {"id": receipt["id"], "env": REQUEST["env"]}
    assert broker.collect(receipt["id"], os.getuid()) == {"id": receipt["id"], "state": "approved"}
    broker.ready(receipt["id"], {"DEMO": "synthetic-value"})
    with pytest.raises(ValueError):
        broker.collect(receipt["id"], os.getuid() + 1)
    first = broker.collect(receipt["id"], os.getuid())
    assert first == {
        "id": receipt["id"],
        "state": "delivered",
        "values": {"DEMO": "synthetic-value"},
    }
    assert broker.collect(receipt["id"], os.getuid()) == {"id": receipt["id"], "state": "delivered"}
    assert not broker.decide(event(row["approve"]))
    for name in ("audit.log", "requests.json"):
        assert "synthetic-value" not in (tmp_path / name).read_text()
    broker.close()


def test_uncollected_values_expire_and_late_values_are_dropped(broker):
    """Bug: approved values wait in memory forever, or arrive after the request ended."""
    receipt = submit(broker)
    row = broker.pending()[0]
    broker.decide(event(row["approve"]))
    broker.expire(broker.records[receipt["id"]]["expires"] + 1)
    broker.ready(receipt["id"], {"DEMO": "late"})
    assert broker.values == {}
    assert broker.collect(receipt["id"], os.getuid())["state"] == "timed out"
    broker.close()


@pytest.mark.parametrize(
    "changes",
    [
        {"env": {"DEMO": "plain-value"}},
        {"env": {"PATH": "op://A/B/C", "x y": "op://A/B/C"}},
        {"env": {}},
        {"argv": "true"},
        {"argv": []},
        {"reason": "two\nlines"},
        {"cwd": "relative"},
        {"extra": "field"},
    ],
)
def test_malformed_requests_are_refused(broker, changes):
    """Bug: caller text becomes a plain value, an injection or an unbounded record."""
    with pytest.raises(ValueError):
        submit(broker, **changes)
    broker.close()


def test_same_request_reattaches_while_active(broker):
    """Bug: a rerun after a tool timeout opens a second approval for the same command, or a
    request from another machine or session collects values approved for this one."""
    first = submit(broker)
    assert submit(broker) == first
    assert submit(broker, reason="other words") == first
    assert submit(broker, cwd="/tmp")["id"] != first["id"]
    assert submit(broker, host="other-host")["id"] != first["id"]
    assert submit(broker, session="other-session")["id"] != first["id"]
    row = next(r for r in broker.pending() if r["id"] == first["id"])
    broker.decide(event(row["approve"]))
    assert submit(broker) == {"id": first["id"], "state": "approved"}
    broker.ready(first["id"], {"DEMO": "v"})
    broker.collect(first["id"], os.getuid())
    assert submit(broker)["id"] != first["id"]
    broker.close()


@pytest.mark.parametrize("approved", [False, True])
def test_restart_marks_unfinished_work_interrupted_without_replay(broker, tmp_path, approved):
    """Bug: an old notification or recovered approval delivers after a broker restart."""
    receipt = submit(broker)
    action = broker.pending()[0]["approve"]
    if approved:
        assert broker.decide(event(action))
        broker.ready(receipt["id"], {"DEMO": "v"})
    broker.close()
    resumed = Broker(tmp_path, "operator")
    assert resumed.collect(receipt["id"], os.getuid()) == {
        "id": receipt["id"],
        "state": "interrupted",
    }
    assert resumed.decide(event(action)) is None
    assert resumed.pending() == [] and resumed.values == {}
    resumed.close()
