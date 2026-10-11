"""Ask the operator in Home Assistant about one request and read the decision for it.

The route can send one question and read answers, nothing else. The question carries a random
request ID. Home Assistant records the first press of the operator's own user under that ID, and
only `approved` under this request's ID releases anything.
"""

import json
import secrets
import shlex
import time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from slopmeister.session import secret_tier

SETTINGS = "home-assistant.json"
FIELDS = {"ask_url", "answer_url", "token"}
WAIT_SECONDS = 600
POLL_SECONDS = 2
EXCHANGE_TIMEOUT = 5
ANSWER_LIMIT = 1048576
# A mobile push drops a larger body, so the operator would approve text they cannot see.
MESSAGE_LIMIT = 3800
DECISIONS = ("approved", "denied")
NO_REASON = (
    "a tier-two request needs a reason the operator can read. Put "
    'SECRET_ASK_REASON="<one line>" in front of the command and run it again.'
)
EXPIRED = "timed out"


class Unreachable(Exception):
    """Home Assistant did not take the question, the message names the cause."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("Home Assistant redirect refused")


def _address(value: object) -> bool:
    """HTTPS, or plain HTTP to this machine only."""
    parsed = urlsplit(value) if isinstance(value, str) else None
    if parsed is None or not parsed.hostname:
        return False
    return parsed.scheme == "https" or (parsed.scheme == "http" and parsed.hostname == "127.0.0.1")


def valid(data: object) -> bool:
    """Whether the data is a route: two safe addresses and a one-line token, nothing else."""
    try:
        return (
            set(data) == FIELDS
            and all(isinstance(v, str) and v.isprintable() for v in data.values())
            and _address(data["ask_url"])
            and _address(data["answer_url"])
        )
    except TypeError, AttributeError:
        return False


def route() -> dict[str, str]:
    """The two addresses and the read credential of the route, from its private file."""
    path = secret_tier.directory() / SETTINGS
    try:
        data = json.loads(secret_tier.private(path))
    except json.JSONDecodeError:
        data = None
    if not valid(data):
        raise ValueError(f"{path} does not hold the route's two HTTPS addresses and its token")
    return data


def question(request: dict) -> dict:
    """What the operator reads before deciding, the purpose and the origin first."""
    references = ", ".join(f"{name}={value}" for name, value in request["env"].items())
    # One line, so a reason cannot write a line that reads like the command or the host.
    reason = " ".join(request["reason"].split())
    text = (
        f"Why: {reason}\nSession: {request['session']}\nHost: {request['host']}\n"
        f"Command: {shlex.join(request['argv'])}\nReferences: {references}\n"
        f"Directory: {request['cwd']}"
    )
    body = {
        "id": secrets.token_hex(16),
        "title": "Secret approval: " + request["session"],
        "message": text,
    }
    if len(json.dumps(body).encode()) > MESSAGE_LIMIT:
        raise ValueError("the request text exceeds what one notification can show")
    return body


def _exchange(request: Request) -> bytes:
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    with opener.open(request, timeout=EXCHANGE_TIMEOUT) as response:
        data = response.read(ANSWER_LIMIT + 1)
    if len(data) > ANSWER_LIMIT:
        raise ValueError("Home Assistant's answer exceeds the limit")
    return data


def ask(settings: dict[str, str], body: dict) -> None:
    headers = {"Content-Type": "application/json"}
    try:
        _exchange(Request(settings["ask_url"], json.dumps(body).encode(), headers, method="POST"))
    except (OSError, ValueError) as error:
        raise Unreachable(str(getattr(error, "reason", None) or error)) from None


def answer(settings: dict[str, str], identifier: str) -> str:
    """The decision recorded for this request, or empty while there is none."""
    headers = {"Authorization": "Bearer " + settings["token"]}
    try:
        data = json.loads(_exchange(Request(settings["answer_url"], headers=headers)))
        # A Home Assistant state carries the map under its attributes.
        decisions = data.get("attributes", data).get("decisions", {})
        found = decisions.get(identifier, "")
    except OSError, ValueError, AttributeError:
        return ""
    return found if found in DECISIONS else ""


def decision(settings: dict[str, str], identifier: str) -> str:
    """Wait for this request's decision: approved, denied, or timed out after ten minutes."""
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        found = answer(settings, identifier)
        if found:
            return found
        time.sleep(POLL_SECONDS)
    return EXPIRED
