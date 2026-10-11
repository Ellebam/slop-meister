"""Only the operator's approval of this very request, read from Home Assistant, releases it."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading

import pytest

from slopmeister.session import secret_approval, secret_tier

REQUEST = {
    "env": {"DEMO": "op://Production/Item/credential"},
    "argv": ["deploy", "the host"],
    "cwd": "/work/example-app",
    "reason": "Deploy the host",
    "session": "example-app-1-example",
    "host": "agent-host",
}


class HomeAssistant(BaseHTTPRequestHandler):
    """Takes questions on /ask and serves the decisions map on /answer, as the route does."""

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.asked.append((self.path, body))
        self.send_response(302 if self.path == "/moved" else 200)
        self.send_header("Location", "/ask")
        self.end_headers()

    def do_GET(self):
        self.server.read.append(self.headers.get("Authorization"))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps(self.server.answer).encode())

    def log_message(self, *args):
        pass


@pytest.fixture
def home_assistant(monkeypatch):
    server = ThreadingHTTPServer(("127.0.0.1", 0), HomeAssistant)
    server.asked, server.read, server.answer = [], [], {"decisions": {}}
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    monkeypatch.setattr(secret_approval, "POLL_SECONDS", 0.01)
    monkeypatch.setattr(secret_approval, "WAIT_SECONDS", 0.2)
    base = f"http://127.0.0.1:{server.server_port}"
    server.settings = {"ask_url": base + "/ask", "answer_url": base + "/answer", "token": "read"}
    yield server
    server.shutdown()
    thread.join()
    server.server_close()


def test_question_shows_what_the_operator_decides_on():
    """Bug: the operator approves without seeing the references, the command or its origin."""
    body = secret_approval.question(REQUEST)
    assert len(body["id"]) == 32 and body["id"] != secret_approval.question(REQUEST)["id"]
    assert body["title"] == "Secret approval: example-app-1-example"
    assert body["message"] == (
        "Why: Deploy the host\nSession: example-app-1-example\nHost: agent-host\n"
        "Command: deploy 'the host'\nReferences: DEMO=op://Production/Item/credential\n"
        "Directory: /work/example-app"
    )


def test_question_longer_than_a_notification_is_refused():
    """Bug: the phone cuts the text and the operator approves a command they cannot read."""
    with pytest.raises(ValueError, match="exceeds what one notification can show"):
        secret_approval.question({**REQUEST, "argv": ["x" * 4000]})


@pytest.mark.parametrize("shape", ["plain", "state"])
def test_only_this_requests_approval_counts(home_assistant, shape):
    """Bug: another request's approval, or an unknown word, releases this request."""
    decisions = {"other": "approved", "mine": "maybe"}
    home_assistant.answer = (
        {"decisions": decisions} if shape == "plain" else {"attributes": {"decisions": decisions}}
    )
    assert secret_approval.decision(home_assistant.settings, "mine") == "timed out"
    decisions["mine"] = "approved"
    assert secret_approval.decision(home_assistant.settings, "mine") == "approved"
    assert home_assistant.read[-1] == "Bearer read"


def test_denial_is_read_as_denial(home_assistant):
    """Bug: a pressed Deny is waited out as silence, or read as approval."""
    home_assistant.answer = {"decisions": {"mine": "denied"}}
    assert secret_approval.decision(home_assistant.settings, "mine") == "denied"


def test_answer_that_is_not_the_map_is_silence(home_assistant):
    """Bug: an error page or a list from Home Assistant crashes the wait or approves."""
    home_assistant.answer = ["approved"]
    assert secret_approval.decision(home_assistant.settings, "mine") == "timed out"


def test_question_reaches_home_assistant_once(home_assistant):
    """Bug: the question is not sent, or is sent to a redirect target that never asked for it."""
    body = secret_approval.question(REQUEST)
    secret_approval.ask(home_assistant.settings, body)
    assert home_assistant.asked == [("/ask", body)]
    moved = {
        **home_assistant.settings,
        "ask_url": home_assistant.settings["ask_url"][:-4] + "/moved",
    }
    with pytest.raises(secret_approval.Unreachable):
        secret_approval.ask(moved, body)
    assert [path for path, _ in home_assistant.asked] == ["/ask", "/moved"]


def test_stopped_home_assistant_is_unreachable(home_assistant):
    """Bug: with Home Assistant stopped the question vanishes and the agent waits ten minutes."""
    home_assistant.shutdown()
    home_assistant.server_close()
    with pytest.raises(secret_approval.Unreachable):
        secret_approval.ask(home_assistant.settings, secret_approval.question(REQUEST))


@pytest.mark.parametrize(
    "settings",
    [
        {"ask_url": "http://ha.example/a", "answer_url": "https://ha.example/b", "token": "t"},
        {"ask_url": "https://ha.example/a", "token": "t"},
        {"ask_url": "https://ha.example/a", "answer_url": "https://ha.example/b", "token": "t\nx"},
        ["https://ha.example/a"],
    ],
)
def test_route_file_must_hold_two_safe_addresses(tmp_path, monkeypatch, settings):
    """Bug: the read credential travels over plain HTTP, or a broken file crashes op run."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    path = tmp_path / secret_tier.DIRECTORY / secret_approval.SETTINGS
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(settings))
    path.chmod(0o600)
    with pytest.raises(ValueError, match="does not hold the route"):
        secret_approval.route()
